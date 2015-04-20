# -*- encoding: utf-8 -*-
"""Defines a set of mixins that provide tools for interacting with entities."""
from fauxfactory import gen_choice
from nailgun import client, config
from nailgun.entity_fields import IntegerField, OneToManyField, OneToOneField
import threading
import time

from sys import version_info
if version_info.major == 2:
    # pylint:disable=import-error
    from urlparse import urljoin
    import httplib as http_client
    import thread
else:
    from urllib.parse import urljoin  # pylint:disable=F0401,E0611
    import _thread as thread  # pylint:disable=import-error
    import http.client as http_client  # pylint:disable=import-error


#: Default for ``poll_rate`` argument to
#: :func:`nailgun.entity_mixins._poll_task`.
TASK_POLL_RATE = 5
#: Default for ``timeout`` argument to
#: :func:`nailgun.entity_mixins._poll_task`.
TASK_TIMEOUT = 300

#: A :class:`nailgun.config.ServerConfig` object.
#:
#: Used by :class:`nailgun.entity_mixins.Entity`.
DEFAULT_SERVER_CONFIG = None


class TaskTimedOutError(Exception):
    """Indicates that a task did not finish before the timout limit."""


class TaskFailedError(Exception):
    """Indicates that a task finished with a result other than "success"."""


def _poll_task(task_id, server_config, poll_rate=None, timeout=None):
    """Implement :meth:`nailgun.entities.ForemanTask.poll`.

    See :meth:`nailgun.entities.ForemanTask.poll` for a full description of how
    this method acts. Other methods may also call this method, such as
    :meth:`nailgun.entity_mixins.EntityDeleteMixin.delete`.

    Certain mixins benefit from being able to poll the server after performing
    an operation. However, this module cannot use
    :meth:`nailgun.entities.ForemanTask.poll`, as that would be a circular
    import. Placing the implementation of
    :meth:`nailgun.entities.ForemanTask.poll` here allows both that method and
    the mixins in this module to use the same logic.

    """
    if poll_rate is None:
        poll_rate = TASK_POLL_RATE
    if timeout is None:
        timeout = TASK_TIMEOUT

    # Implement the timeout.
    def raise_task_timeout():
        """Raise a KeyboardInterrupt exception in the main thread."""
        thread.interrupt_main()
    timer = threading.Timer(timeout, raise_task_timeout)

    # Poll until the task finishes. The timeout prevents an infinite loop.
    try:
        timer.start()
        path = '{0}/foreman_tasks/api/tasks/{1}'.format(
            server_config.url,
            task_id
        )
        while True:
            response = client.get(
                path,
                auth=server_config.auth,
                verify=server_config.verify,
            )
            response.raise_for_status()
            task_info = response.json()
            if task_info['state'] != 'running':
                break
            time.sleep(poll_rate)
    except KeyboardInterrupt:
        # raise_task_timeout will raise a KeyboardInterrupt when the timeout
        # expires. Catch the exception and raise TaskTimedOutError
        raise TaskTimedOutError('Timed out polling task {0}'.format(task_id))
    finally:
        timer.cancel()

    # Check for task success or failure.
    if task_info['result'] != 'success':
        raise TaskFailedError(
            'Task {0} completed with result {1}. Error message(s): {2}'.format(
                task_id,
                task_info['result'],
                task_info['humanized']['errors']
            )
        )
    return task_info


def _make_entity_from_id(entity_cls, entity_obj_or_id, server_config):
    """Given an entity object or an ID, return an entity object.

    If the value passed in is an object that is a subclass of :class:`Entity`,
    return that value. Otherwise, create an object of the type that ``field``
    references, give that object an ID of ``field_value``, and return that
    object.

    :param entity_cls: An :class:`Entity` subclass.
    :param entity_obj_or_id: Either a :class:`nailgun.entity_mixins.Entity`
        object or an entity ID.
    :returns: An ``entity_cls`` object.
    :rtype: nailgun.entity_mixins.Entity

    """
    if isinstance(entity_obj_or_id, entity_cls):
        return entity_obj_or_id
    return entity_cls(server_config, id=entity_obj_or_id)


def _make_entities_from_ids(entity_cls, entity_objs_and_ids, server_config):
    """Given an iterable of entities and/or IDs, return a list of entities.

    :param entity_cls: An :class:`Entity` subclass.
    :param entity_obj_or_id: An iterable of
        :class:`nailgun.entity_mixins.Entity` objects and/or entity IDs.
    :returns: A list of ``entity_cls`` objects.

    """
    return [
        _make_entity_from_id(entity_cls, entity_or_id, server_config)
        for entity_or_id
        in entity_objs_and_ids
    ]


# -----------------------------------------------------------------------------
# Definition of parent Entity class and its dependencies.
# -----------------------------------------------------------------------------


class NoSuchPathError(Exception):
    """Indicates that the requested path cannot be constructed."""


class NoSuchFieldError(Exception):
    """Indicates that the assigned-to :class:`Entity` field does not exist."""


class Entity(object):
    """A logical representation of a Foreman entity.

    This class is rather useless as is, and it is intended to be subclassed.
    Subclasses can specify two useful types of information:

    * fields
    * metadata

    Fields are represented by setting class attributes, and metadata is
    represented by settings attributes on the inner class named ``Meta``. For
    example, consider this class declaration:

    >>> class User(Entity):
    ...     def __init__(self, server_config=None, **kwargs):
    ...         fields = {
    ...             'name': StringField(),
    ...             'supervisor': OneToOneField('User'),
    ...             'subordinate': OneToManyField('User'),
    ...         }
    ...     class Meta(object):
    ...         api_path = 'api/users'

    In the example above, the class attributes of ``User`` are fields, and the
    class attributes of ``Meta`` are metadata. Here is one way to instantiate
    the ``User`` object shown above:

    >>> user = User(
    ...     name='Alice',
    ...     supervisor=User(id=1),
    ...     subordinate=[User(id=3), User(id=4)],
    ... )
    >>> user.name == 'Alice'
    True
    >>> user.supervisor.id = 1
    True

    The canonical procedure for initializing foreign key fields, shown above,
    is powerful but verbose. As an alternative, the following convenience is
    offered:

    >>> User(name='Alice', supervisor=1, subordinate=[3, 4])
    >>> user.name == 'Alice'
    True
    >>> user.supervisor.id = 1
    True

    An entity object is useless if you are unable to use it to communicate with
    a server. The solution is to provide a :class:`nailgun.config.ServerConfig`
    when instantiating a new entity. This configuration object is stored as an
    instance variable named ``_server_config`` and used by methods such as
    :meth:`nailgun.entity_mixins.Entity.path`.

    1. If the ``server_config`` argument is specified, then that is used.
    2. Otherwise, if :data:`nailgun.entity_mixins.DEFAULT_SERVER_CONFIG` is
       set, then that is used.
    3. Otherwise, call :meth:`nailgun.config.ServerConfig.get`.

    """

    def __init__(self, server_config=None, **kwargs):
        # server_config > DEFAULT_SERVER_CONFIG > ServerConfig.get()
        if server_config is not None:
            self._server_config = server_config
        elif DEFAULT_SERVER_CONFIG is not None:
            self._server_config = DEFAULT_SERVER_CONFIG
        else:
            self._server_config = config.ServerConfig.get()

        # Subclasses usually define a set of fields before calling `super`, but
        # that's not always the case.
        if not hasattr(self, '_fields'):
            self._fields = {}
        self._fields.setdefault('id', IntegerField())

        # Check that a valid set of field values has been passed in.
        if not set(kwargs.keys()).issubset(self._fields.keys()):
            raise NoSuchFieldError(
                'Valid fields are {0}, but received {1} instead.'.format(
                    self._fields.keys(), kwargs.keys()
                )
            )

        # Iterate through the values passed in and assign them as instance
        # variable to `self`. Make sure to transform entity IDs into entity
        # objects. (This feature is described in the docstring.)
        for field_name, field_value in kwargs.items():  # e.g. ('admin', True)
            field = self._fields[field_name]  # e.g. A BooleanField object
            if isinstance(field, OneToOneField):
                setattr(self, field_name, _make_entity_from_id(
                    field.gen_value(),
                    field_value,
                    self._server_config
                ))
            elif isinstance(field, OneToManyField):
                setattr(self, field_name, _make_entities_from_ids(
                    field.gen_value(),
                    field_value,
                    self._server_config
                ))
            else:
                setattr(self, field_name, field_value)

    class Meta(object):  # pylint:disable=too-few-public-methods
        """Non-field information about this entity.

        This class is a convenient place to store any non-field information
        about an entity. For example, the ``api_path`` variable is used by
        :meth:`nailgun.entity_mixins.Entity.path`.

        """

    def path(self, which=None):
        """Return the path to the current entity.

        Return the path to base entities of this entity's type if:

        * ``which`` is ``'base'``, or
        * ``which`` is ``None`` and instance attribute ``id`` is unset.

        Return the path to this exact entity if instance attribute ``id`` is
        set and:

        * ``which`` is ``'self'``, or
        * ``which`` is ``None``.

        Raise :class:`NoSuchPathError` otherwise.

        Child classes may choose to extend this method, especially if a child
        entity offers more than the two URLs supported by default. If extended,
        then the extending class should check for custom parameters before
        calling ``super``::

            def path(self, which):
                if which == 'custom':
                    return urljoin(…)
                super(ChildEntity, self).__init__(which)

        This will allow the extending method to accept a custom parameter
        without accidentally raising a :class:`NoSuchPathError`.

        :param which: A string. Optional. Valid arguments are 'self' and
            'base'.
        :return: A string. A fully qualified URL.
        :raises nailgun.entity_mixins.NoSuchPathError: If no path can be built.

        """
        # It is OK that member ``self.Meta.api_path`` is not found. Subclasses
        # are required to set that attribute if they wish to use this method.
        #
        # Beware of leading and trailing slashes:
        #
        # urljoin('example.com', 'foo') => 'foo'
        # urljoin('example.com/', 'foo') => 'example.com/foo'
        # urljoin('example.com', '/foo') => '/foo'
        # urljoin('example.com/', '/foo') => '/foo'
        base = urljoin(
            self._server_config.url + '/',
            self.Meta.api_path  # pylint:disable=no-member
        )
        if which == 'base' or (which is None and not hasattr(self, 'id')):
            return base
        elif (which == 'self' or which is None) and hasattr(self, 'id'):
            return urljoin(base + '/', str(self.id))  # pylint:disable=E1101
        raise NoSuchPathError

    def get_fields(self):
        """Return a copy of the fields on the current object.

        :return: A dict mapping field names to
            :class`nailgun.entity_fields.Field` objects.

        """
        return self._fields.copy()

    def get_values(self):
        """Return a copy of field values on the current object.

        This method is almost identical to ``vars(self).copy()``. However, only
        instance attributes that correspond to a field are included in the
        returned dict.

        :return: A dict mapping field names to user-provided values.

        """
        attrs = vars(self).copy()
        attrs.pop('_server_config')
        attrs.pop('_fields')
        return attrs


class EntityDeleteMixin(object):
    """A mixin that adds the ability to delete an entity."""

    def delete_raw(self):
        """Delete the current entity.

        Send an HTTP DELETE request to :meth:`Entity.path`. Return the
        response. Do not check the response for any errors, such as an HTTP 4XX
        or 5XX status code.

        """
        return client.delete(
            self.path(which='self'),
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )

    def delete(self, synchronous=True):
        """Delete the current entity.

        Call :meth:`delete_raw` and check for an HTTP 4XX or 5XX response.
        Return either the JSON-decoded response or information about a
        completed foreman task.

        :param synchronous: A boolean. What should happen if the server returns
            an HTTP 202 (accepted) status code? Wait for the task to complete
            if ``True``. Immediately return a response otherwise.
        :returns: A dict. Either the JSON-decoded response or information about
            a foreman task.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If an HTTP 202 response is received and the
            response JSON can not be decoded.
        :raises nailgun.entity_mixins.TaskTimedOutError: If an HTTP 202
            response is received, ``synchronous is True`` and the task times
            out.

        """
        response = self.delete_raw()
        response.raise_for_status()
        if (synchronous is True and
                response.status_code == http_client.ACCEPTED):
            return _poll_task(response.json()['id'], self._server_config)
        if response.status_code == http_client.NO_CONTENT:
            # "The server successfully processed the request, but is not
            # returning any content. Usually used as a response to a successful
            # delete request."
            return
        return response.json()


class EntityReadMixin(object):
    """A mixin that provides the ability to read an entity."""

    def read_raw(self):
        """Get information about the current entity.

        Send an HTTP GET request to :meth:`Entity.path`. Return the response.
        Do not check the response for any errors, such as an HTTP 4XX or 5XX
        status code.

        :return: A ``requests.response`` object.

        """
        return client.get(
            self.path('self'),
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )

    def read_json(self):
        """Get information about the current entity.

        Call :meth:`read_raw`. Check the response status code, decode JSON and
        return the decoded JSON as a dict.

        :return: A dict. The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON can not be decoded.

        """
        response = self.read_raw()
        response.raise_for_status()
        return response.json()

    def read(self, entity=None, attrs=None, ignore=()):
        """Get information about the current entity.

        Call :meth:`read_json`. Use this information to populate an object of
        type ``type(self)`` and return that object.

        All of an entity's one-to-one and one-to-many relationships are
        populated with objects of the correct type. For example, if
        ``SomeEntity.other_entity`` is a one-to-one relationship, this should
        return ``True``::

            isinstance(
                SomeEntity(id=N).read().other_entity,
                nailgun.entity_mixins.Entity
            )

        Additionally, both of these commands should succeed::

            SomeEntity(id=N).read().other_entity.id
            SomeEntity(id=N).read().other_entity.read().other_attr

        In the example above, ``other_entity.id`` is the **only** attribute
        with a meaningful value. Calling ``other_entity.read`` populates the
        remaining entity attributes.

        :param nailgun.entity_mixins.Entity entity: The object to be populated
            and returned. An object of type ``type(self)`` by default.
        :param attrs: A dict. Data used to populate the object's attributes.
            The response from
            :meth:`nailgun.entity_mixins.EntityReadMixin.read_json` by default.
        :param ignore: A tuple of attributes which should not be read from the
            server. This is mainly useful for attributes like a password which
            are not returned.
        :return: An instance of type ``type(self)``.
        :rtype: nailgun.entity_mixins.Entity

        """
        if entity is None:
            entity = type(self)(self._server_config)
        if attrs is None:
            attrs = self.read_json()

        # Rename fields using entity.Meta.api_names, if present.
        if hasattr(entity.Meta, 'api_names'):
            for local_name, remote_name in entity.Meta.api_names.items():
                attrs[local_name] = attrs.pop(remote_name)

        # The server returns OneToOneFields as a hash of attributes, like so:
        #
        #     {'name': 'Alice Hayworth', 'login': 'ahayworth', 'id': 1}
        #
        # OneToManyFields are a list of hashes.
        for field_name, field_type in entity.get_fields().items():
            if field_name in ignore:
                continue
            if isinstance(field_type, OneToOneField):
                if attrs[field_name] is None:
                    referenced_entity = None
                else:
                    referenced_entity = field_type.gen_value()(
                        self._server_config,
                        id=attrs[field_name]['id']
                    )
                setattr(entity, field_name, referenced_entity)
            elif isinstance(field_type, OneToManyField):
                other_cls = field_type.gen_value()
                referenced_entities = [
                    other_cls(self._server_config, id=referenced_entity['id'])
                    for referenced_entity
                    in attrs[field_name + 's']  # e.g. "users"
                ]
                setattr(entity, field_name, referenced_entities)
            else:
                setattr(entity, field_name, attrs[field_name])
        return entity


class EntityCreateMixin(object):
    """A mixin that provides the ability to create an entity.

    The methods provided by this mixin work together to create an entity. A
    typical tree of method calls looks like this::

        create
        └── create_json
            └── create_raw
                ├── create_missing
                └── create_payload

    Only :meth:`create_raw` communicates with the server.

    """

    def create_missing(self):
        """Automagically populate all required instance attributes.

        Iterate through the set of all required class
        :class:`nailgun.entity_fields.Field` defined on ``type(self)`` and
        create a corresponding instance attribute if none exists. Subclasses
        should override this method if there is some relationship between two
        required fields.

        :return: Nothing. This method relies on side-effects.

        """
        for field_name, field in self.get_fields().items():
            if field.required and not hasattr(self, field_name):
                # Most `gen_value` methods return a value such as an integer,
                # string or dictionary, but OneTo{One,Many}Field.gen_value
                # returns the referenced class. Thus, for foreign key fields,
                # this is possible:
                #
                #     value = field.gen_value()().create()
                #
                # However, `create` is more susceptible to unexpected data
                # returned by the server. This is expecially problematic so
                # long as NailGun has no facility for dealing with different
                # server API versions. Until then, the more kludgy
                # `create_json` is used.
                if hasattr(field, 'default'):
                    value = field.default
                elif hasattr(field, 'choices'):
                    value = gen_choice(field.choices)
                elif isinstance(field, OneToOneField):
                    value = field.gen_value()()
                    value.id = field.gen_value()().create_json()['id']
                elif isinstance(field, OneToManyField):
                    value = [field.gen_value()()]
                    value[0].id = field.gen_value()().create_json()['id']
                else:
                    value = field.gen_value()
                setattr(self, field_name, value)

    def create_payload(self):
        """Create a payload that can be POSTed to the server.

        Make a copy of the instance attributes on ``self``. This payload will
        be POSTed to the server. Then change the payload's keys. (The payload
        is a dict.) Rename keys using ``self.Meta.api_names`` if it is present
        and append "_id" and "_ids" as appropriate.

        :return: A dict. A copy of the instance attributes on ``self``, with
            key names adjusted as appropriate.

        """
        data = self.get_values().copy()
        api_names = getattr(self.Meta, 'api_names', {})
        for field_name, field in self.get_fields().items():
            if field_name in data:
                if field_name in api_names:
                    # e.g. rename filter_type to type for ContentViewFilter
                    data[api_names[field_name]] = data.pop(field_name)
                if isinstance(field, OneToOneField):
                    data[field_name + '_id'] = data.pop(field_name).id
                elif isinstance(field, OneToManyField):
                    data[field_name + '_ids'] = [
                        entity.id for entity in data.pop(field_name)
                    ]
        return data

    def create_raw(self, create_missing=True):
        """Create an entity.

        Generate values for required, unset fields by calling
        :meth:`create_missing`. Only do this if ``create_missing`` is true.
        Then make an HTTP POST call to ``self.path('base')``. Return the
        response received from the server.

        :param create_missing: A boolean. Should :meth:`create_missing` be
            called? In other words, should values be generated for required,
            empty fields?
        :return: A ``requests.response`` object.

        """
        if create_missing:
            self.create_missing()
        return client.post(
            self.path('base'),
            self.create_payload(),
            auth=self._server_config.auth,
            verify=self._server_config.verify,
        )

    def create_json(self, create_missing=True):
        """Create an entity.

        Call :meth:`create_raw`. Check the response status code, decode JSON
        and return the decoded JSON as a dict.

        :return: A dict. The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON can not be decoded.

        """
        response = self.create_raw(create_missing)
        response.raise_for_status()
        return response.json()

    def create(self, create_missing=True):
        """Create an entity.

        Call :meth:`create_json`. Use this information to populate an object of
        type ``type(self)`` and return that object.

        This method requires that a method named "read" be available on the
        current object. A method named "read" will be available if
        :class:`EntityReadMixin` is present in the inheritance tree, and using
        the method provided by that mixin is the recommended technique for
        making a "read" method available.

        This method makes use of :meth:`EntityReadMixin.read` for two reasons.
        First, calling that method is simply convenient. Second, the server
        frequently returns weirdly structured, inconsistently named or
        straight-up broken responses, and quite a bit of effort has gone in to
        decoding server responses so :meth:`EntityReadMixin.read` can function
        correctly. Calling ``read`` allows this method to re-use the decoding
        work that has been done for that method.

        :return: An instance of type ``type(self)``.
        :rtype: nailgun.entity_mixins.Entity
        :raises: ``AttributeError`` if a method named "read" is not available
            on the current object.

        """
        return self.read(attrs=self.create_json(create_missing))
