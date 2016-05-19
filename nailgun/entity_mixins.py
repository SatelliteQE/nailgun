# -*- encoding: utf-8 -*-
"""Defines a set of mixins that provide tools for interacting with entities."""
from collections import Iterable
from fauxfactory import gen_choice
from inflection import pluralize
from nailgun import client, config, signals
from nailgun.entity_fields import IntegerField, OneToManyField, OneToOneField
import threading
import time

from sys import version_info
if version_info.major == 2:  # pragma: no cover
    # pylint:disable=import-error
    from urlparse import urljoin
    import httplib as http_client
    import thread
else:  # pragma: no cover
    from urllib.parse import urljoin  # pylint:disable=F0401,E0611
    import _thread as thread  # pylint:disable=import-error
    import http.client as http_client  # pylint:disable=import-error

# pylint:disable=too-many-lines
# This module contains very extensive docstrings, so this module is easier to
# understand than its size suggests. That said, it could be useful to split
# each mixin in to a separate module. That would help to ensure that each
# mixin stays independent.


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

#: Used by :meth:`nailgun.entity_mixins.EntityCreateMixin.create_raw`.
#:
#: This is the default value for the ``create_missing`` argument to
#: :meth:`nailgun.entity_mixins.EntityCreateMixin.create_raw`. Keep in mind
#: that this variable also affects methods which call ``create_raw``, such as
#: :meth:`nailgun.entity_mixins.EntityCreateMixin.create_json`.
CREATE_MISSING = False


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
    path = '{0}/foreman_tasks/api/tasks/{1}'.format(server_config.url, task_id)
    try:
        timer.start()
        while True:
            response = client.get(path, **server_config.get_client_kwargs())
            response.raise_for_status()
            task_info = response.json()
            if task_info['state'] in ('paused', 'stopped'):
                break
            time.sleep(poll_rate)
    except KeyboardInterrupt:
        # raise_task_timeout will raise a KeyboardInterrupt when the timeout
        # expires. Catch the exception and raise TaskTimedOutError
        raise TaskTimedOutError(
            'Timed out polling task {0}. Task information: {1}'
            .format(task_id, task_info)
        )
    finally:
        timer.cancel()

    # Check for task success or failure.
    if task_info['result'] != 'success':
        raise TaskFailedError(
            'Task {0} did not succeed. Task information: {1}'
            .format(task_id, task_info)
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
        :class:`nailgun.entity_mixins.Entity` objects and/or entity IDs. All of
        the entities in this iterable should be of type ``entity_cls``.
    :returns: A list of ``entity_cls`` objects.

    """
    return [
        _make_entity_from_id(entity_cls, entity_or_id, server_config)
        for entity_or_id
        in entity_objs_and_ids
    ]


def _payload(fields, values):
    """Implement the ``*_payload`` methods.

    It's frequently useful to create a dict of values that can be encoded to
    JSON and sent to the server. Unfortunately, there are mismatches between
    the field names used by NailGun and the field names the server expects.
    This method provides a default translation that works in many cases. For
    example:

    >>> from nailgun.entities import Product
    >>> product = Product(name='foo', organization=1)
    >>> set(product.get_fields())
    {
        'description',
        'gpg_key',
        'id',
        'label',
        'name',
        'organization',
        'sync_plan',
    }
    >>> set(product.get_values())
    {'name', 'organization'}
    >>> product.create_payload()
    {'organization_id': 1, 'name': 'foo'}

    :param fields: A value like what is returned by
        :meth:`nailgun.entity_mixins.Entity.get_fields`.
    :param values: A value like what is returned by
        :meth:`nailgun.entity_mixins.Entity.get_values`.
    :returns: A dict mapping field names to field values.

    """
    for field_name, field in fields.items():
        if field_name in values:
            if isinstance(field, OneToOneField):
                values[field_name + '_id'] = (
                    getattr(values.pop(field_name), 'id', None)
                )
            elif isinstance(field, OneToManyField):
                values[field_name + '_ids'] = [
                    entity.id for entity in values.pop(field_name)
                ]
    return values


def _get_server_config():
    """Search for a :class:`nailgun.config.ServerConfig`.

    :returns: :data:`nailgun.entity_mixins.DEFAULT_SERVER_CONFIG` if it is not
        ``None``, or whatever is returned by
        :meth:`nailgun.config.ServerConfig.get` otherwise.
    :rtype: nailgun.config.ServerConfig

    """
    if DEFAULT_SERVER_CONFIG is not None:
        return DEFAULT_SERVER_CONFIG
    return config.ServerConfig.get()


def _get_entity_id(field_name, attrs):
    """Find the ID for a one to one relationship.

    The server may return JSON data in the following forms for a
    :class:`nailgun.entity_fields.OneToOneField`::

        'user': None
        'user': {'name': 'Alice Hayes', 'login': 'ahayes', 'id': 1}
        'user_id': 1
        'user_id': None

    Search ``attrs`` for a one to one ``field_name`` and return its ID.

    :param field_name: A string. The name of a field.
    :param attrs: A dict. A JSON payload as returned from a server.
    :returns: Either an entity ID or None.

    """
    field_name_id = field_name + '_id'
    if field_name in attrs:
        if attrs[field_name] is None:
            return None
        else:
            return attrs[field_name]['id']
    elif field_name_id in attrs:
        return attrs[field_name_id]
    else:
        raise MissingValueError(
            'Cannot find a value for the "{0}" field. Searched for keys named '
            '{1}, but available keys are {2}.'
            .format(field_name, (field_name, field_name_id), attrs.keys())
        )


def _get_entity_ids(field_name, attrs):
    """Find the IDs for a one to many relationship.

    The server may return JSON data in the following forms for a
    :class:`nailgun.entity_fields.OneToManyField`::

        'user': [{'id': 1, …}, {'id': 42, …}]
        'users': [{'id': 1, …}, {'id': 42, …}]
        'user_ids': [1, 42]

    Search ``attrs`` for a one to many ``field_name`` and return its ID.

    :param field_name: A string. The name of a field.
    :param attrs: A dict. A JSON payload as returned from a server.
    :returns: An iterable of entity IDs.

    """
    field_name_ids = field_name + '_ids'
    plural_field_name = pluralize(field_name)
    if field_name_ids in attrs:
        return attrs[field_name_ids]
    elif field_name in attrs:
        return [entity['id'] for entity in attrs[field_name]]
    elif plural_field_name in attrs:
        return [entity['id'] for entity in attrs[plural_field_name]]
    else:
        raise MissingValueError(
            'Cannot find a value for the "{0}" field. Searched for keys named '
            '{1}, but available keys are {2}.'
            .format(
                field_name,
                (field_name_ids, field_name, plural_field_name),
                attrs.keys()
            )
        )


# -----------------------------------------------------------------------------
# Definition of parent Entity class and its dependencies.
# -----------------------------------------------------------------------------


class NoSuchPathError(Exception):
    """Indicates that the requested path cannot be constructed."""


class NoSuchFieldError(Exception):
    """Indicates that the referenced field does not exist."""


class BadValueError(Exception):
    """Indicates that an inappropriate value was assigned to an entity."""


class MissingValueError(Exception):
    """Indicates that no value can be found for a field."""


class Entity(object):
    """A representation of a logically related set of API paths.

    This class is rather useless as is, and it is intended to be subclassed.
    Subclasses can specify two useful types of information:

    * fields
    * metadata

    Fields and metadata are represented by the ``_fields`` and ``_meta``
    instance attributes, respectively. Here is an example of how to define and
    instantiate an entity:

    >>> class User(Entity):
    ...     def __init__(self, server_config=None, **kwargs):
    ...         self._fields = {
    ...             'name': StringField(),
    ...             'supervisor': OneToOneField('User'),
    ...             'subordinate': OneToManyField('User'),
    ...         }
    ...         self._meta = {'api_path': 'api/users'}
    ...         return super(User, self).__init__(server_config, **kwargs)
    ...
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
    is powerful but verbose. It is tiresome to write statements such as
    ``[User(id=3), User(id=4)]``. As a convenience, entity IDs may be given:

    >>> User(name='Alice', supervisor=1, subordinate=[3, 4])
    >>> user.name == 'Alice'
    True
    >>> user.supervisor.id = 1
    True

    An entity object is useless if you are unable to use it to communicate with
    a server. The solution is to provide a :class:`nailgun.config.ServerConfig`
    when instantiating a new entity.

    1. If the ``server_config`` argument is specified, then that is used.
    2. Otherwise, if :data:`nailgun.entity_mixins.DEFAULT_SERVER_CONFIG` is
       set, then that is used.
    3. Otherwise, call :meth:`nailgun.config.ServerConfig.get`.

    An entity's server configuration is stored as a private instance variaable
    and is used by mixin methods, such as
    :meth:`nailgun.entity_mixins.Entity.path`. For more information on server
    configuration objects, see :class:`nailgun.config.BaseServerConfig`.

    :raises nailgun.entity_mixins.NoSuchFieldError: If a value is assigned to a
        non-existent field.
    :raises nailgun.entity_mixins.BadValueError: If an inappropriate value is
        assigned to a field.

    """

    def __init__(self, server_config=None, **kwargs):
        if server_config is None:
            server_config = _get_server_config()
        self._server_config = server_config

        # Subclasses usually define a set of fields and metadata before calling
        # `super`, but that's not always the case.
        if not hasattr(self, '_fields'):
            self._fields = {}
        self._fields.setdefault('id', IntegerField())
        if not hasattr(self, '_meta'):
            self._meta = {}

        # Check that a valid set of field values has been passed in.
        if not set(kwargs.keys()).issubset(self._fields.keys()):
            raise NoSuchFieldError(
                'Valid fields are {0}, but received {1} instead.'
                .format(self._fields.keys(), kwargs.keys())
            )

        # Iterate through the values passed in and assign them as instance
        # variable to `self`. Make sure to transform entity IDs into entity
        # objects. (This feature is described in the docstring.)
        for field_name, field_value in kwargs.items():  # e.g. ('admin', True)
            field = self._fields[field_name]  # e.g. A BooleanField object
            if isinstance(field, OneToOneField):
                if field_value is None:
                    setattr(self, field_name, field_value)
                else:
                    setattr(self, field_name, _make_entity_from_id(
                        field.gen_value(),
                        field_value,
                        self._server_config
                    ))
            elif isinstance(field, OneToManyField):
                # `try:; …; except TypeError:; raise BadValueError(…)` better
                # follows the "ask forgiveness" principle. However, a TypeError
                # could be raised for any number of reasons. For example,
                # `field_value` could have a faulty __iter__ implementation.
                if not isinstance(field_value, Iterable):
                    raise BadValueError(
                        'An inappropriate value was assigned to the "{0}" '
                        'field. An iterable of entities and/or entity IDs '
                        'should be assigned, but the following was given: {1}'
                        .format(field_name, field_value)
                    )
                setattr(self, field_name, _make_entities_from_ids(
                    field.gen_value(),
                    field_value,
                    self._server_config
                ))
            else:
                setattr(self, field_name, field_value)

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
        # It is OK that member ``self._meta`` is not found. Subclasses are
        # required to set that attribute if they wish to use this method.
        #
        # Beware of leading and trailing slashes:
        #
        #     urljoin('example.com', 'foo') => 'foo'
        #     urljoin('example.com/', 'foo') => 'example.com/foo'
        #     urljoin('example.com', '/foo') => '/foo'
        #     urljoin('example.com/', '/foo') => '/foo'
        #
        base = urljoin(
            self._server_config.url + '/',
            self._meta['api_path']  # pylint:disable=no-member
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
        attrs.pop('_meta')
        return attrs

    def __repr__(self):
        return '{0}.{1}({2}{3})'.format(
            self.__module__,
            type(self).__name__,
            repr(self._server_config),
            ''.join(
                ', {0}={1}'.format(key, repr(value))
                for key, value
                in self.get_values().items()
            )
        )


class EntityDeleteMixin(object):
    """This mixin provides the ability to delete an entity.

    The methods provided by this class work together. The call tree looks like
    this::

        delete → delete_raw

    In short, here is what the methods do:

    :meth:`delete_raw`
        Make an HTTP DELETE request to the server.
    :meth:`delete`
        Check the server's response for errors and decode the response.

    """

    def delete_raw(self):
        """Delete the current entity.

        Make an HTTP DELETE call to ``self.path('base')``. Return the response.

        :return: A ``requests.response`` object.

        """
        return client.delete(
            self.path(which='self'),
            **self._server_config.get_client_kwargs()
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
        signals.pre_delete.send(self, synchronous=synchronous)

        response = self.delete_raw()
        response.raise_for_status()

        if (synchronous is True and
                response.status_code == http_client.ACCEPTED):
            result = _poll_task(response.json()['id'], self._server_config)
        elif response.status_code == http_client.NO_CONTENT:
            # "The server successfully processed the request, but is not
            # returning any content. Usually used as a response to a successful
            # delete request."
            result = None
        else:
            result = response.json()

        signals.post_delete.send(self, synchronous=synchronous, result=result)

        return result


class EntityReadMixin(object):
    """This mixin provides the ability to read an entity.

    The methods provided by this class work together. The call tree looks like
    this::

        read → read_json → read_raw

    In short, here is what the methods do:

    :meth:`read_raw`
        Make an HTTP GET request to the server.
    :meth:`read_json`
        Check the server's response for errors and decode the response.
    :meth:`read`
        Create a :class:`nailgun.entity_mixins.Entity` object representing the
        created entity and populate its fields with data returned from the
        server.

    See the individual methods for more detailed information.

    """

    def read_raw(self):
        """Get information about the current entity.

        Make an HTTP PUT call to ``self.path('self')``. Return the response.

        :return: A ``requests.response`` object.

        """
        return client.get(
            self.path('self'),
            **self._server_config.get_client_kwargs()
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

    def read(self, entity=None, attrs=None, ignore=None):
        """Get information about the current entity.

        1. Create a new entity of type ``type(self)``.
        2. Call :meth:`read_json` and capture the response.
        3. Populate the entity with the response.
        4. Return the entity.

        Step one is skipped if the ``entity`` argument is specified. Step two
        is skipped if the ``attrs`` argument is specified. Step three is
        modified by the ``ignore`` argument.

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
        :param ignore: A set of attributes which should not be read from the
            server. This is mainly useful for attributes like a password which
            are not returned.
        :return: An instance of type ``type(self)``.
        :rtype: nailgun.entity_mixins.Entity

        """
        if entity is None:
            entity = type(self)(self._server_config)
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()

        for field_name, field in entity.get_fields().items():
            if field_name in ignore:
                continue
            if isinstance(field, OneToOneField):
                entity_id = _get_entity_id(field_name, attrs)
                if entity_id is None:
                    referenced_entity = None
                else:
                    referenced_entity = field.entity(
                        self._server_config,
                        id=entity_id,
                    )
                setattr(entity, field_name, referenced_entity)
            elif isinstance(field, OneToManyField):
                referenced_entities = [
                    field.entity(self._server_config, id=entity_id)
                    for entity_id
                    in _get_entity_ids(field_name, attrs)
                ]
                setattr(entity, field_name, referenced_entities)
            else:
                setattr(entity, field_name, attrs[field_name])
        return entity


class EntityCreateMixin(object):
    """This mixin provides the ability to create an entity.

    The methods provided by this class work together. The call tree looks like
    this::

        create
        └── create_json
            └── create_raw
                ├── create_missing
                └── create_payload

    In short, here is what the methods do:

    :meth:`create_missing`
        Populate required fields with random values. Required fields that
        already have a value are not populated. This method is not called
        by default.
    :meth:`create_payload`
        Assemble a payload of data that can be encoded and sent to the server.
    :meth:`create_raw`
        Make an HTTP POST request to the server, including the payload.
    :meth:`create_json`
        Check the server's response for errors and decode the response.
    :meth:`create`
        Create a :class:`nailgun.entity_mixins.Entity` object representing the
        created entity and populate its fields with data returned from the
        server.

    See the individual methods for more detailed information.

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
                # returns the referenced class.
                if hasattr(field, 'default'):
                    value = field.default
                elif hasattr(field, 'choices'):
                    value = gen_choice(field.choices)
                elif isinstance(field, OneToOneField):
                    value = field.gen_value()(self._server_config).create(True)
                elif isinstance(field, OneToManyField):
                    value = [
                        field.gen_value()(self._server_config).create(True)
                    ]
                else:
                    value = field.gen_value()
                setattr(self, field_name, value)

    def create_payload(self):
        """Create a payload of values that can be sent to the server.

        See :func:`_payload`.

        """
        return _payload(self.get_fields(), self.get_values())

    def create_raw(self, create_missing=None):
        """Create an entity.

        Possibly call :meth:`create_missing`. Then make an HTTP POST call to
        ``self.path('base')``. The request payload consists of whatever is
        returned by :meth:`create_payload`. Return the response.

        :param create_missing: Should :meth:`create_missing` be called? In
            other words, should values be generated for required, empty fields?
            Defaults to :data:`nailgun.entity_mixins.CREATE_MISSING`.
        :return: A ``requests.response`` object.

        """
        if create_missing is None:
            create_missing = CREATE_MISSING
        if create_missing:
            self.create_missing()
        return client.post(
            self.path('base'),
            self.create_payload(),
            **self._server_config.get_client_kwargs()
        )

    def create_json(self, create_missing=None):
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

    def create(self, create_missing=None):
        """Create an entity.

        Call :meth:`create_json`, use the response to populate a new object
        of type ``type(self)`` and return that object.

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
        signals.pre_create.send(self, create_missing=create_missing)
        entity = self.read(attrs=self.create_json(create_missing))
        signals.post_create.send(self, entity=entity)
        return entity


class EntityUpdateMixin(object):
    """This mixin provides the ability to update an entity.

    The methods provided by this class work together. The call tree looks
    like this::

        update → update_json → update_raw → update_payload

    In short, here is what the methods do:

    :meth:`update_payload`
        Assemble a payload of data that can be encoded and sent to the
        server.
    :meth:`update_raw`
        Make an HTTP PUT request to the server, including the payload.
    :meth:`update_json`
        Check the server's response for errors and decode the response.
    :meth:`update`
        Create a :class:`nailgun.entity_mixins.Entity` object representing
        the created entity and populate its fields.

    See the individual methods for more detailed information.

    """

    def update_payload(self, fields=None):
        """Create a payload of values that can be sent to the server.

        By default, this method behaves just like :func:`_payload`. However,
        one can also specify a certain set of fields that should be returned.
        For more information, see :meth:`update`.

        """
        values = self.get_values()
        if fields is not None:
            values = {field: values[field] for field in fields}
        return _payload(self.get_fields(), values)

    def update_raw(self, fields=None):
        """Update the current entity.

        Make an HTTP PUT call to ``self.path('base')``. The request payload
        consists of whatever is returned by :meth:`update_payload`. Return the
        response.

        :param fields: See :meth:`update`.
        :return: A ``requests.response`` object.

        """
        return client.put(
            self.path('self'),
            self.update_payload(fields),
            **self._server_config.get_client_kwargs()
        )

    def update_json(self, fields=None):
        """Update the current entity.

        Call :meth:`update_raw`. Check the response status code, decode JSON
        and return the decoded JSON as a dict.

        :param fields: See :meth:`update`.
        :return: A dict consisting of the decoded JSON in the server's
            response.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON can not be decoded.

        """
        response = self.update_raw(fields)
        response.raise_for_status()
        return response.json()

    def update(self, fields=None):
        """Update the current entity.

        Call :meth:`update_json`, use the response to populate a new object
        of type ``type(self)`` and return that object.

        This method requires that
        :meth:`nailgun.entity_mixins.EntityReadMixin.read` or some other
        identical method be available on the current object. A more thorough
        explanation is available at
        :meth:`nailgun.entity_mixins.EntityCreateMixin.create`.

        :param fields: An iterable of field names. Only the fields named in
            this iterable will be updated. No fields are updated if an empty
            iterable is passed in. All fields are updated if ``None`` is passed
            in.
        :raises: ``KeyError`` if asked to update a field but no value is
            available for that field on the current entity.

        """
        signals.pre_update.send(self, fields=fields)
        entity = self.read(attrs=self.update_json(fields))
        signals.post_update.send(self, entity=entity, fields=fields)
        return entity


class EntitySearchMixin(object):
    """This mixin provides the ability to search for entities.

    The methods provided by this class work together. The call tree looks like
    this::

        search
        ├── search_json
        │   └── search_raw
        │       └── search_payload
        ├── search_normalize
        └── search_filter

    In short, here is what the methods do:

    :meth:`search_payload`
        Assemble a search query that can be encoded and sent to the server.
    :meth:`search_raw`
        Make an HTTP GET request to the server, including the payload.
    :meth:`search_json`
        Check the server's response for errors and decode the response.
    :meth:`search_normalize`
        Normalize search results so they can be used to create new entities.
    :meth:`search`
        Create one or more :class:`nailgun.entity_mixins.Entity` objects
        representing the found entities and populate their fields.
    :meth:`search_filter`
        Read all ``entities`` and locally filter them.

    See the individual methods for more detailed information.

    """

    def search_payload(self, fields=None, query=None):
        """Create a search query.

        Do the following:

        1. Generate a search query. By default, all values returned by
           :meth:`nailgun.entity_mixins.Entity.get_values` are used. If
           ``fields`` is specified, only the named values are used.
        2. Merge ``query`` in to the generated search query.
        3. Return the result.

        The rules for generating a search query can be illustrated by example.
        Let's say that we have an entity with an
        :class:`nailgun.entity_fields.IntegerField`, a
        :class:`nailgun.entity_fields.OneToOneField` and a
        :class:`nailgun.entity_fields.OneToManyField`::

            >>> some_entity = SomeEntity(id=1, one=2, many=[3, 4])
            >>> fields = some_entity.get_fields()
            >>> isinstance(fields['id'], IntegerField)
            True
            >>> isinstance(fields['one'], OneToOneField)
            True
            >>> isinstance(fields['many'], OneToManyField)
            True

        This method appends "_id" and "_ids" on to the names of each
        ``OneToOneField`` and ``OneToManyField``, respectively::

            >>> some_entity.search_payload()
            {'id': 1, 'one_id': 2, 'many_ids': [3, 4]}

        By default, all fields are used. But you can specify a set of field
        names to use::

            >>> some_entity.search_payload({'id'})
            {'id': 1}
            >>> some_entity.search_payload({'one'})
            {'one_id': 2}
            >>> some_entity.search_payload({'id', 'one'})
            {'id': 1, 'one_id': 2}

        If a ``query`` is specified, it is merged in to the generated query::

            >>> some_entity.search_payload(query={'id': 5})
            {'id': 5, 'one_id': 2, 'many_ids': [3, 4]}
            >>> some_entity.search_payload(query={'per_page': 1000})
            {'id': 1, 'one_id': 2, 'many_ids': [3, 4], 'per_page': 1000}

        .. WARNING:: This method currently generates an extremely naive search
            query that will be wrong in many cases. In addition, Satellite
            currently accepts invalid search queries without complaint. Make
            sure to check the API documentation for your version of Satellite
            against what this method produces.

        :param fields: See :meth:`search`.
        :param query: See :meth:`search`.
        :returns: A dict that can be encoded as JSON and used in a search.

        """
        if fields is None:
            fields = set(self.get_values().keys())
        if query is None:
            query = {}

        payload = {}
        fields_dict = self.get_fields()
        for field in fields:
            value = getattr(self, field)
            if isinstance(fields_dict[field], OneToOneField):
                payload[field + '_id'] = value.id
            elif isinstance(fields_dict[field], OneToManyField):
                payload[field + '_ids'] = [entity.id for entity in value]
            else:
                payload[field] = value
        payload.update(query)
        return payload

    def search_raw(self, fields=None, query=None):
        """Search for entities.

        Make an HTTP GET call to ``self.path('base')``. Return the response.

        .. WARNING:: Subclasses that override this method should not alter the
            ``fields`` or ``query`` arguments. (However, subclasses that
            override this method may still alter the server's response.) See
            :meth:`search_normalize` for details.

        :param fields: See :meth:`search`.
        :param query: See :meth:`search`.
        :return: A ``requests.response`` object.

        """
        return client.get(
            self.path('base'),
            data=self.search_payload(fields, query),
            **self._server_config.get_client_kwargs()
        )

    def search_json(self, fields=None, query=None):
        """Search for entities.

        Call :meth:`search_raw`. Check the response status code, decode JSON
        and return the decoded JSON as a dict.

        .. WARNING:: Subclasses that override this method should not alter the
            ``fields`` or ``query`` arguments. (However, subclasses that
            override this method may still alter the server's response.) See
            :meth:`search_normalize` for details.

        :param fields: See :meth:`search`.
        :param query: See :meth:`search`.
        :return: A dict. The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON can not be decoded.

        """
        response = self.search_raw(fields, query)
        response.raise_for_status()
        return response.json()

    def search_normalize(self, results):
        """Normalize search results so they can be used to create new entities.

        See :meth:`search` for an example of how to use this method. Here's a
        simplified example::

            results = self.search_json()
            results = self.search_normalize(results)
            entity = SomeEntity(some_cfg, **results[0])

        At this time, it is possible to parse all search results without
        knowing what search query was sent to the server. However, it is
        possible that certain responses can only be parsed if the search query
        is known. If that is the case, this method will be given a new
        ``payload`` argument, where ``payload`` is the query sent to the
        server.

        As a precaution, the following is higly recommended:

        * :meth:`search` may alter ``fields`` and ``query`` at will.
        * :meth:`search_payload` may alter ``fields`` and ``query`` in an
          idempotent manner.
        * No other method should alter ``fields`` or ``query``.

        :param results: A list of dicts, where each dict is a set of attributes
            for one entity. The contents of these dicts are as is returned from
            the server.
        :returns: A list of dicts, where each dict is a set of attributes for
            one entity. The contents of these dicts have been normalized and
            can be used to instantiate entities.

        """
        fields = self.get_fields()
        normalized = []
        for result in results:
            # For each field that we know about, copy the corresponding field
            # from the server's search result. If any extra attributes are
            # copied over, Entity.__init__ will raise a NoSuchFieldError.
            # Examples of problematic results from server:
            #
            # * organization_id (denormalized OneToOne. see above)
            # * organizations, organization_ids (denormalized OneToMany. above)
            # * updated_at, created_at (these may be handled in the future)
            # * sp_subnet (Host.sp_subnet is an undocumented field)
            #
            attrs = {}
            for field_name, field in fields.items():
                if isinstance(field, OneToOneField):
                    try:
                        attrs[field_name] = _get_entity_id(field_name, result)
                    except MissingValueError:
                        pass
                elif isinstance(field, OneToManyField):
                    try:
                        attrs[field_name] = _get_entity_ids(field_name, result)
                    except MissingValueError:
                        pass
                else:
                    try:
                        attrs[field_name] = result[field_name]
                    except KeyError:
                        pass
            normalized.append(attrs)
        return normalized

    def search(self, fields=None, query=None, filters=None):
        """Search for entities.

        At its simplest, this method searches for all entities of a given kind.
        For example, to ask for all
        :class:`nailgun.entities.LifecycleEnvironment` entities::

            LifecycleEnvironment().search()

        Values on an entity are used to generate a search query, and the
        ``fields`` argument can be used to specify which fields should be used
        when generating a search query::

            lc_env = LifecycleEnvironment(name='foo', organization=1)
            results = lc_env.search()  # Search by name and organization.
            results = lc_env.search({'name', 'organization'})  # Same.
            results = lc_env.search({'name'})  # Search by name.
            results = lc_env.search({'organization'})  # Search by organization
            results = lc_env.search(set())  # Search for all lifecycle envs.
            results = lc_env.search({'library'})  # Error!

        In some cases, the simple search queries that can be generated by
        NailGun are not sufficient. In this case, you can pass in a raw search
        query instead. For example, to search for all lifecycle environments
        with a name of 'foo'::

            LifecycleEnvironment().search(query={'search': 'name="foo"'})

        The example above is rather pointless: it is easier and more concise to
        use a generated query. But — and this is a **very** important "but" —
        the manual search query is melded in to the generated query. This can
        be used to great effect::

            LifecycleEnvironment(name='foo').search(query={'per_page': 50})

        For examples of what the final search queries look like, see
        :meth:`search_payload`. (That method also accepts the ``fields`` and
        ``query`` arguments.)

        In some cases, the server's search facilities may be insufficient, or
        it may be inordinately difficult to craft a search query. In this case,
        you can filter search results locally. For example, to ask the server
        for a list of all lifecycle environments and then locally search
        through the results for the lifecycle environment named "foo"::

            LifecycleEnvironment().search(filters={'name': 'foo'})

        Be warned that filtering locally can be **very** slow. NailGun must
        ``read()`` every single entity returned by the server before filtering
        results. This is because the values used in the filtering process may
        not have been returned by the server in the initial response to the
        search.

        The fact that all entities are read when ``filters`` is specified can
        be used to great effect. For example, this search returns a fully
        populated list of every single lifecycle environment::

            LifecycleEnvironment().search(filters={})

        :param fields: A set naming which fields should be used when generating
            a search query. If ``None``, all values on the entity are used. If
            an empty set, no values are used.
        :param query: A dict containing a raw search query. This is melded in
            to the generated search query like so:  ``{generated:
            query}.update({manual: query})``.
        :param filters: A dict. Used to filter search results locally.
        :return: A list of entities, all of type ``type(self)``.

        """
        # Goals:
        #
        # * Be tolerant of missing values. It's reasonable for the server to
        #   return an incomplete set of attributes for each search result.
        # * Use as many returned values as possible. There's no point in
        #   letting returned data go to waste. This implies that we must…
        # * …parse irregular server responses. This includes pluralized field
        #   names, misnamed attributes (e.g. BZ 1233245) and weirdly named
        #   fields (e.g. Media.path_).
        #
        signals.pre_search.send(self, fields=fields, query=query,
                                filters=filters)
        results = self.search_json(fields, query)['results']
        results = self.search_normalize(results)
        entities = [
            type(self)(self._server_config, **result)
            for result in results
        ]
        if filters is not None:
            entities = self.search_filter(entities, filters)

        signals.post_search.send(self, entities=entities, fields=fields,
                                 query=query, filters=filters)
        return entities

    @staticmethod
    def search_filter(entities, filters):
        """Read all ``entities`` and locally filter them.

        This method can be used like so::

            entities = EntitySearchMixin(entities, {'name': 'foo'})

        In this example, only entities where ``entity.name == 'foo'`` holds
        true are returned. An arbitrary number of field names and values may be
        provided as filters.

        .. NOTE:: This method calls :meth:`EntityReadMixin.read`. As a result,
            this method only works when called on a class that also inherits
            from :class:`EntityReadMixin`.

        :param entities: A list of :class:`Entity` objects. All list items
            should be of the same type.
        :param filters: A dict in the form ``{field_name: field_value, …}``.
        :raises nailgun.entity_mixins.NoSuchFieldError: If any of the fields
            named in ``filters`` do not exist on the entities being filtered.
        :raises: ``NotImplementedError`` If any of the fields named in
            ``filters`` are a :class:`nailgun.entity_fields.OneToOneField` or
            :class:`nailgun.entity_fields.OneToManyField`.

        """
        # Check to make sure all arguments are sane.
        if len(entities) == 0:
            return entities
        fields = entities[0].get_fields()  # assume all entities are identical
        if not set(filters).issubset(fields):
            raise NoSuchFieldError(
                'Valid filters are {0}, but received {1} instead.'
                .format(fields.keys(), filters.keys())
            )
        for field_name in filters:
            if isinstance(fields[field_name], (OneToOneField, OneToManyField)):
                raise NotImplementedError(
                    'Search results cannot (yet?) be locally filtered by '
                    '`OneToOneField`s and `OneToManyField`s. {0} is a {1}.'
                    .format(field_name, type(fields[field_name]).__name__)
                )

        # The arguments are sane. Filter away!
        filtered = [entity.read() for entity in entities]  # don't alter inputs
        for field_name, field_value in filters.items():
            filtered = [
                entity for entity in filtered
                if getattr(entity, field_name) == field_value
            ]
        return filtered
