# -*- encoding: utf-8 -*-
"""This module defines all entities which Foreman exposes.

Each class in this module allows you to work with a certain set of logically
related API paths exposed by the server. For example,
:class:`nailgun.entities.Host` lets you work with the ``/api/v2/hosts`` API
path and sub-paths. Each class attribute corresponds an attribute of that
entity. For example, the ``Host.name`` class attribute represents the name of a
host. These class attributes are used by the various mixins, such as
``nailgun.entity_mixins.EntityCreateMixin``.

Several classes contain work-arounds for bugs. These bugs often affect only
specific server releases, and ideally, the work-arounds should only be
attempted if communicating with an affected server. However, work-arounds can
only be conditionally triggered if NailGun has a facility for determining which
software version the server is running. Until then, the safe route will be
taken, and all work-arounds will be attempted all the time. Each method that
makes use of a work-around notes so in its docstring.

:class:`nailgun.entity_mixins.Entity` provides more insight into the inner
workings of entity classes.

"""
from datetime import datetime
from sys import version_info
import hashlib
import os.path
from fauxfactory import gen_alphanumeric, gen_choice
from packaging.version import Version

from nailgun import client, entity_fields
from nailgun.entity_mixins import (
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
    _poll_task,
    _get_entity_ids,
    _payload,
)
from nailgun.entity_mixins import to_json_serializable  # noqa: F401

if version_info.major == 2:  # pragma: no cover
    from httplib import ACCEPTED, NO_CONTENT  # pylint:disable=import-error
    from urlparse import urljoin  # pylint:disable=import-error
else:  # pragma: no cover
    from http.client import ACCEPTED, NO_CONTENT  # pylint:disable=import-error
    from urllib.parse import urljoin  # pylint:disable=F0401,E0611

# pylint:disable=too-many-lines
# The size of this file is a direct reflection of the size of Satellite's API.
# This file's size has already been significantly cut down through the use of
# mixins and fields, and cutting the file down in size further would simply
# obfuscate the design of the entities. It might be possible to place entity
# definitions in separate modules, though.

# pylint:disable=attribute-defined-outside-init
# NailGun aims to be like a traditional database ORM and allow uses of the dot
# operator such as these:
#
#     product = Product(server_config, id=5).read()
#     product.name
#     product.organization.id
#
# Unfortunately, these fields cannot simply be initialized with `None`. These
# have different effects:
#
#     product.description = None; product.update()
#     del product.description; product.update()
#
# The first will delete the product's description, and the second will not
# touch the product's description.


_FAKE_YUM_REPO = 'http://inecas.fedorapeople.org/fakerepos/zoo3/'
_OPERATING_SYSTEMS = (
    'AIX',
    'Altlinux',
    'Archlinux',
    'Debian',
    'Freebsd',
    'Gentoo',
    'Junos',
    'Redhat',
    'Solaris',
    'Suse',
    'Windows',
)


class APIResponseError(Exception):
    """Indicates an error if response returns unexpected result."""


def _handle_response(response, server_config, synchronous=False, timeout=None):
    """Handle a server's response in a typical fashion.

    Do the following:

    1. Check the server's response for an HTTP status code indicating an error.
    2. Poll the server for a foreman task to complete if an HTTP 202 (accepted)
       status code is returned and ``synchronous is True``.
    3. Immediately return if an HTTP "NO CONTENT" response is received.
    4. Determine what type of the content returned from server. Depending on
       the type method should return server's response, with all JSON decoded
       or just response content itself.

    :param response: A response object as returned by one of the functions in
        :mod:`nailgun.client` or the requests library.
    :param server_config: A `nailgun.config.ServerConfig` object.
    :param synchronous: Should this function poll the server?
    :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.

    """
    response.raise_for_status()
    if synchronous is True and response.status_code == ACCEPTED:
        return ForemanTask(
            server_config, id=response.json()['id']).poll(timeout=timeout)
    if response.status_code == NO_CONTENT:
        return
    if 'application/json' in response.headers.get('content-type', '').lower():
        return response.json()
    elif isinstance(response.content, bytes):
        return response.content.decode('utf-8')
    else:
        return response.content


def _check_for_value(field_name, field_values):
    """Check to see if ``field_name`` is present in ``field_values``.

    An entity may use this function in its ``__init__`` method to ensure that a
    parameter required for object instantiation has been passed in. For
    example, in :class:`nailgun.entities.ContentViewPuppetModule`:

    >>> def __init__(self, server_config=None, **kwargs):
    >>>     _check_for_value('content_view', kwargs)
    >>>     # …
    >>>     self._meta = {
    >>>         'api_path': '{0}/content_view_puppet_modules'.format(
    >>>             self.content_view.path('self')
    >>>         )
    >>>     }

    :param field_name: A string. A key with this name must be present in
        ``field_values``.
    :param field_values: A dict containing field-name to field-value mappings.
    :raises: ``TypeError`` if ``field_name`` is not present in
        ``field_values``.
    :returns: Nothing.

    """
    if field_name not in field_values:
        raise TypeError(
            'A value must be provided for the "{0}" field.'.format(field_name)
        )


def _get_org(server_config, label):
    """Find an :class:`nailgun.entities.Organization` object.

    :param nailgun.config.ServerConfig server_config: The server that should be
        searched.
    :param label: A string. The label of the organization to find.
    :raises APIResponseError: If exactly one organization is not found.
    :returns: An :class:`nailgun.entities.Organization` object.

    """
    organizations = Organization(server_config).search(
        query={u'search': u'label={0}'.format(label)}
    )
    if len(organizations) != 1:
        raise APIResponseError(
            u'Could not find exactly one organization with label "{0}". '
            u'Actual search results: {1}'.format(label, organizations)
        )
    return organizations[0].read()


def _get_version(server_config):
    """Return ``server_config.version``, or a default version if not present.

    This method is especially useful when an entity must determine what version
    the server is. :class:`nailgun.config.ServerConfig` does not currently
    require the "version" attribute, and if none is provided then none is set.
    This is often problematic - what version should the server be assumed to be
    running? This method provides an answer to that question.

    Also see #163.

    :param nailgun.config.ServerConfig server_config: Any old server config may
        be passed in.
    :returns: A ``packaging.version.Version`` object. The version on
        ``server_config`` is returned if present, or a default version of '1!0'
        (epoch 1, version 0) otherwise.

    """
    return getattr(server_config, 'version', Version('1!0'))


class ActivationKey(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Activation Key entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'auto_attach': entity_fields.BooleanField(),
            'content_view': entity_fields.OneToOneField(ContentView),
            'description': entity_fields.StringField(),
            'environment': entity_fields.OneToOneField(LifecycleEnvironment),
            'host_collection': entity_fields.OneToManyField(HostCollection),
            'max_hosts': entity_fields.IntegerField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'service_level': entity_fields.StringField(),
            'unlimited_hosts': entity_fields.BooleanField(),
        }
        self._meta = {
            'api_path': 'katello/api/v2/activation_keys',
            'server_modes': ('sat', 'sam'),
        }
        super(ActivationKey, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        add_subscriptions
            /activation_keys/<id>/add_subscriptions
        copy
            /activation_keys/<id>/copy
        content_override
            /activation_keys/<id>/content_override
        product_content
            /activation_keys/<id>/product_content
        releases
            /activation_keys/<id>/releases
        remove_subscriptions
            /activation_keys/<id>/remove_subscriptions
        subscriptions
            /activation_keys/<id>/subscriptions

        ``super`` is called otherwise.

        """
        if which in (
                'add_subscriptions',
                'content_override',
                'copy',
                'host_collections',
                'product_content',
                'releases',
                'remove_subscriptions',
                'subscriptions'):
            return '{0}/{1}'.format(
                super(ActivationKey, self).path(which='self'),
                which
            )
        return super(ActivationKey, self).path(which)

    def add_host_collection(self, synchronous=True, **kwargs):
        """Helper for associating host collection with activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('host_collections'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def add_subscriptions(self, synchronous=True, **kwargs):
        """Helper for adding subscriptions to activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('add_subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def copy(self, synchronous=True, **kwargs):
        """Copy provided activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        if 'data' in kwargs and 'id' not in kwargs['data']:
            kwargs['data']['id'] = self.id  # pylint:disable=no-member
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('copy'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def remove_subscriptions(self, synchronous=True, **kwargs):
        """Helper for removing subscriptions from an activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('remove_subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def subscriptions(self, synchronous=True, **kwargs):
        """Helper for retrieving subscriptions on an activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def content_override(self, synchronous=True, **kwargs):
        """Override the content of an activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('content_override'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def product_content(self, synchronous=True, **kwargs):
        """Helper for showing content available for activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('product_content'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def remove_host_collection(self, synchronous=True, **kwargs):
        """Helper for disassociating host collection from the activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('host_collections'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class Architecture(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Architecture entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'operatingsystem': entity_fields.OneToManyField(OperatingSystem),
        }
        self._meta = {
            'api_path': 'api/v2/architectures',
            'server_modes': ('sat'),
        }
        super(Architecture, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'architecture': super(Architecture, self).create_payload()}

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1234964
        <https://bugzilla.redhat.com/show_bug.cgi?id=1234964>`_.

        """
        self.update_json(fields)
        return self.read()


class ArfReport(
        Entity,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin):
    """A representation of a Arf Report entity.

    # Read Arf report
    ArfReport(id=<id>).read()
    # Delete Arf report
    ArfReport(id=<id>).delete()
    # Download Arf report in HTML
    ArfReport(id=<id>).download_html()
    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location),
            'organization': entity_fields.OneToManyField(Organization),
            'host': entity_fields.OneToOneField(Host),
            'openscap_proxy': entity_fields.OneToOneField(Capsule),
            'policy': entity_fields.OneToOneField(CompliancePolicies)
        }
        self._meta = {
            'api_path': 'api/compliance/arf_reports',
        }
        super(ArfReport, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.
        The format of the returned path depends on the value of ``which``:

        download_html
            /api/compliance/arf_reports/:id/download_html

        Otherwise, call ``super``.

        """
        if which in ('download_html',):
            return '{0}/{1}'.format(
                super(ArfReport, self).path(which='self'),
                which
            )
        return super(ArfReport, self).path(which)

    def download_html(self, synchronous=True, **kwargs):
        """Download ARF report in HTML

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('download_html'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class Audit(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of Audit entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'action': entity_fields.StringField(),
            'associated_type': entity_fields.StringField(),
            'associated_name': entity_fields.StringField(),
            'associated_id': entity_fields.IntegerField(),
            'audited_changes': entity_fields.DictField(),
            'auditable_type': entity_fields.StringField(),
            'auditable_name': entity_fields.StringField(),
            'auditable_id': entity_fields.IntegerField(),
            'comment': entity_fields.StringField(),
            'remote_address': entity_fields.IPAddressField(),
            'version': entity_fields.StringField(),
            'user': entity_fields.OneToOneField(User),
        }
        self._meta = {
            'api_path': 'api/v2/audits',
            'server_modes': ('sat'),
        }
        super(Audit, self).__init__(server_config, **kwargs)


class AuthSourceLDAP(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin,
        EntitySearchMixin):
    """A representation of a AuthSourceLDAP entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'account': entity_fields.StringField(),
            'attr_photo': entity_fields.StringField(),
            'base_dn': entity_fields.StringField(),
            'groups_base': entity_fields.StringField(),
            'host': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(1, 60),
            ),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(1, 60),
                unique=True
            ),
            'onthefly_register': entity_fields.BooleanField(),
            'port': entity_fields.IntegerField(),
            'server_type': entity_fields.StringField(
                choices=('active_directory', 'free_ipa', 'posix')),
            'tls': entity_fields.BooleanField(),

            # required if onthefly_register is true,
            'account_password': entity_fields.StringField(),
            'attr_firstname': entity_fields.StringField(),
            'attr_lastname': entity_fields.StringField(),
            'attr_login': entity_fields.StringField(),
            'attr_mail': entity_fields.EmailField(),
            'location': entity_fields.OneToManyField(Location),
            'organization': entity_fields.OneToManyField(Organization),
        }
        self._meta = {
            'api_path': 'api/v2/auth_source_ldaps',
            'server_modes': ('sat'),
        }
        super(AuthSourceLDAP, self).__init__(server_config, **kwargs)

    def create_missing(self):
        """Possibly set several extra instance attributes.

        If ``onthefly_register`` is set and is true, set the following instance
        attributes:

        * account_password
        * account_firstname
        * account_lastname
        * attr_login
        * attr_mail

        """
        super(AuthSourceLDAP, self).create_missing()
        if getattr(self, 'onthefly_register', False) is True:
            for field in (
                    'account_password',
                    'attr_firstname',
                    'attr_lastname',
                    'attr_login',
                    'attr_mail'):
                if not hasattr(self, field):
                    setattr(self, field, self._fields[field].gen_value())

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Do not read the ``account_password`` attribute. Work around a bug.

        For more information, see `Bugzilla #1243036
        <https://bugzilla.redhat.com/show_bug.cgi?id=1243036>`_.

        """
        if attrs is None:
            attrs = self.update_json([])
        if ignore is None:
            ignore = set()
        ignore.add('account_password')
        return super(AuthSourceLDAP, self).read(entity, attrs, ignore, params)


class Bookmark(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Bookmark entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'controller': entity_fields.StringField(required=True),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'public': entity_fields.BooleanField(),
            'query': entity_fields.StringField(required=True),
        }
        self._meta = {'api_path': 'api/v2/bookmarks', 'server_modes': ('sat')}
        super(Bookmark, self).__init__(server_config, **kwargs)


class Capsule(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Capsule entity."""
    # pylint:disable=invalid-name

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'features': entity_fields.ListField(),
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'url': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': 'katello/api/capsules',
            'server_modes': ('sat'),
        }
        super(Capsule, self).__init__(server_config, **kwargs)

    def content_add_lifecycle_environment(self, synchronous=True, **kwargs):
        """Helper to associate lifecycle environment with capsule

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(
            self.path('content_lifecycle_environments'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def content_lifecycle_environments(self, synchronous=True, **kwargs):
        """Helper to get all the lifecycle environments, associated with
        capsule

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(
            self.path('content_lifecycle_environments'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def content_sync(self, synchronous=True, **kwargs):
        """Helper to sync content on a capsule

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('content_sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def content_get_sync(self, synchronous=True, **kwargs):
        """Helper to get content sync status on capsule

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('content_sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        content_lifecycle_environments
            /capsules/<id>/content/lifecycle_environments
        content_sync
            /capsules/<id>/content/sync


        ``super`` is called otherwise.

        """
        if which and which.startswith('content_'):
            return '{0}/content/{1}'.format(
                super(Capsule, self).path(which='self'),
                which.split('content_')[1]
            )
        return super(Capsule, self).path(which)


class CommonParameter(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Common Parameter entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(required=True, unique=True),
            'value': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': 'api/v2/common_parameters',
            'server_modes': ('sat'),
        }
        super(CommonParameter, self).__init__(server_config, **kwargs)


class ComputeAttribute(
        Entity,
        EntityCreateMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Compute Attribute entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'compute_profile': entity_fields.OneToOneField(
                ComputeProfile,
                required=True,
            ),
            'compute_resource': entity_fields.OneToOneField(
                AbstractComputeResource,
                required=True,
            ),
            'vm_attrs': entity_fields.DictField(),
            'attributes': entity_fields.DictField(),
        }
        self._meta = {
            'api_path': 'api/v2/compute_attributes',
            'server_modes': ('sat'),
        }
        super(ComputeAttribute, self).__init__(server_config, **kwargs)


class ComputeProfile(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Compute Profile entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'compute_attribute': entity_fields.OneToManyField(ComputeAttribute),
        }
        self._meta = {
            'api_path': 'api/v2/compute_profiles',
            'server_modes': ('sat'),
        }
        super(ComputeProfile, self).__init__(server_config, **kwargs)


class AbstractComputeResource(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Compute Resource entity."""

    def __init__(self, server_config=None, **kwargs):
        # A user may decide to write this if trying to figure out what provider
        # a compute resource has:
        #
        #     entities.AbstractComputeResource(id=…).read().provider
        #
        # A user may also decide to instantiate a concrete compute resource
        # class:
        #
        #     entities.LibvirtComputeResource(id=…).read()
        #
        # In the former case, we define a set of fields — end of story. In the
        # latter case, that set of fields is updated with values provided by
        # the child class.
        fields = {
            'description': entity_fields.StringField(),
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True,
                str_type='alphanumeric',  # cannot contain whitespace
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'provider': entity_fields.StringField(
                choices=(
                    'Docker',
                    'EC2',
                    'GCE',
                    'Libvirt',
                    'Openstack',
                    'Ovirt',
                    'Rackspace',
                    'Vmware',
                ),
            ),
            'provider_friendly_name': entity_fields.StringField(),
            'url': entity_fields.URLField(required=True),
        }
        fields.update(getattr(self, '_fields', {}))
        self._fields = fields
        self._meta = {
            'api_path': 'api/v2/compute_resources',
            'server_modes': ('sat'),
        }
        super(AbstractComputeResource, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {
            u'compute_resource': super(
                AbstractComputeResource,
                self
            ).create_payload()
        }

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {
            u'compute_resource': super(
                AbstractComputeResource,
                self
            ).update_payload(fields)
        }

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1250922
        <https://bugzilla.redhat.com/show_bug.cgi?id=1250922>`_.

        """
        self.update_json(fields)
        return self.read()


class DiscoveredHost(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Foreman Discovered Host entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'ip': entity_fields.IPAddressField(required=True),
            'mac': entity_fields.MACAddressField(required=True),
        }
        self._meta = {
            'api_path': '/api/v2/discovered_hosts',
            'server_modes': ('sat'),
        }
        super(DiscoveredHost, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        facts
            /discovered_hosts/facts

        ``super`` is called otherwise.

        """
        if which == 'facts':
            return '{0}/{1}'.format(
                super(DiscoveredHost, self).path(which='base'),
                which
            )
        return super(DiscoveredHost, self).path(which)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {
            u'discovered_host': super(DiscoveredHost, self).create_payload()
        }

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {
            u'discovered_host': super(
                DiscoveredHost,
                self
            ).update_payload(fields)
        }

    def facts(self, synchronous=True, **kwargs):
        """Helper to update facts for discovered host, and create the host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('facts'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class DiscoveryRule(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Foreman Discovery Rule entity.

    .. NOTE:: The ``search_`` field is named as such due to a naming conflict
        with :meth:`nailgun.entity_mixins.Entity.path`.

    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'enabled': entity_fields.BooleanField(),
            'hostgroup': entity_fields.OneToOneField(HostGroup, required=True),
            'hostname': entity_fields.StringField(),
            'location': entity_fields.OneToManyField(Location),
            'max_count': entity_fields.IntegerField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'priority': entity_fields.IntegerField(),
            'search_': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': '/api/v2/discovery_rules',
            'server_modes': ('sat'),
        }
        super(DiscoveryRule, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        In addition, rename the ``search_`` field to ``search``.

        """
        payload = super(DiscoveryRule, self).create_payload()
        if 'search_' in payload:
            payload['search'] = payload.pop('search_')
        return {u'discovery_rule': payload}

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1381129
        <https://bugzilla.redhat.com/show_bug.cgi?id=1381129>`_.

        """
        return type(self)(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Work around a bug. Rename ``search`` to ``search_``.

        For more information on the bug, see `Bugzilla #1257255
        <https://bugzilla.redhat.com/show_bug.cgi?id=1257255>`_.

        """
        if attrs is None:
            attrs = self.read_json()
        attrs['search_'] = attrs.pop('search')

        # Satellite doesn't return this attribute. See BZ 1257255.
        attr = 'max_count'
        if ignore is None:
            ignore = set()
        if attr not in ignore:
            # We cannot call `self.update_json([])`, as an ID might not be
            # present on self. However, `attrs` is guaranteed to have an ID.
            attrs[attr] = DiscoveryRule(
                self._server_config,
                id=attrs['id'],
            ).update_json([])[attr]
        return super(DiscoveryRule, self).read(entity, attrs, ignore, params)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1381129
        <https://bugzilla.redhat.com/show_bug.cgi?id=1381129>`_.

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super(DiscoveryRule, self).update_payload(fields)
        if 'search_' in payload:
            payload['search'] = payload.pop('search_')
        return {u'discovery_rule': payload}


class DockerComputeResource(AbstractComputeResource):  # pylint:disable=R0901
    """A representation of a Docker Compute Resource entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'email': entity_fields.EmailField(),
            'password': entity_fields.StringField(),
            'url': entity_fields.URLField(required=True),
            'user': entity_fields.StringField(),
        }
        super(DockerComputeResource, self).__init__(server_config, **kwargs)
        self._fields['provider'].default = 'Docker'
        self._fields['provider'].required = True
        self._fields['provider_friendly_name'].default = 'Docker'

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1223540
        <https://bugzilla.redhat.com/show_bug.cgi?id=1223540>`_.

        """
        return DockerComputeResource(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1223540
        <https://bugzilla.redhat.com/show_bug.cgi?id=1223540>`_.

        Also, do not try to read the "password" field. No value is returned for
        the field, for obvious reasons.

        """
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()
        ignore.add('password')
        if 'email' not in attrs and 'email' not in ignore:
            response = client.put(
                self.path('self'),
                {},
                **self._server_config.get_client_kwargs()
            )
            response.raise_for_status()
            attrs['email'] = response.json().get('email')
        return super(DockerComputeResource, self).read(
            entity, attrs, ignore, params)


class ExternalUserGroup(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityUpdateMixin,
        EntityReadMixin):
    """A representation of a External Usergroup entity.

   ``usergroup`` must be passed in when this entity is instantiated.

   :raises: ``TypeError`` if ``usergroup`` is not passed in.

    # Create external usergroup
    ExternalUserGroup(name='foobargroup',usergroup=usergroup,auth_source=auth).create()
    # Read external usergroup
    ExternalUserGroup(id=<id>, usergroup=usergroup).read()
    # Delete external usergroup
    ExternalUserGroup(id=<id>, usergroup=usergroup).delete()
    # Refresh external usergroup
    ExternalUserGroup(id=<id>, usergroup=usergroup).refresh()
    """
    def __init__(self, server_config=None, **kwargs):
        _check_for_value('usergroup', kwargs)
        self._fields = {
            'name': entity_fields.StringField(required=True),
            'usergroup': entity_fields.OneToOneField(
                UserGroup,
                required=True,
            ),
            'auth_source': entity_fields.OneToOneField(AuthSourceLDAP, required=True)
        }
        super(ExternalUserGroup, self).__init__(server_config, **kwargs)
        self._meta = {
            # pylint:disable=no-member
            'api_path': '{0}/external_usergroups'.format(self.usergroup.path()),
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Ignore usergroup from read and alter auth_source_ldap with auth_source
        """
        if entity is None:
            entity = type(self)(
                self._server_config,
                usergroup=self.usergroup,  # pylint:disable=no-member
            )
        if ignore is None:
            ignore = set()
        ignore.add('usergroup')
        if attrs is None:
            attrs = self.read_json()
        attrs['auth_source'] = attrs.pop('auth_source_ldap')
        return super(ExternalUserGroup, self).read(entity, attrs, ignore, params)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        refresh
            /api/usergroups/:usergroup_id/external_usergroups/:id/refresh
        """
        if which == 'refresh':
            return '{0}/{1}'.format(
                super(ExternalUserGroup, self).path(which='self'),
                which
            )
        return super(ExternalUserGroup, self).path(which)

    def refresh(self, synchronous=True, **kwargs):
        """Refresh external usergroup.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.

        :param kwargs: Arguments to pass to requests.

        :returns: The server's response, with all JSON decoded.

        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('refresh'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class KatelloStatus(Entity, EntityReadMixin):
    """A representation of a Status entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'version': entity_fields.StringField(),
            'timeUTC': entity_fields.DateTimeField(),
        }
        self._meta = {
            'api_path': 'katello/api/v2/status',
            'server_modes': ('sat'),
            'read_type': 'base',
        }
        super(KatelloStatus, self).__init__(server_config, **kwargs)


class LibvirtComputeResource(AbstractComputeResource):  # pylint:disable=R0901
    """A representation of a Libvirt Compute Resource entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'display_type': entity_fields.StringField(
                choices=(u'vnc', u'spice'),
                required=True,
            ),
            'set_console_password': entity_fields.BooleanField(),
        }
        super(LibvirtComputeResource, self).__init__(server_config, **kwargs)
        self._fields['provider'].default = 'Libvirt'
        self._fields['provider'].required = True
        self._fields['provider_friendly_name'].default = 'Libvirt'


class OVirtComputeResource(AbstractComputeResource):
    # pylint: disable=too-many-ancestors
    """A representation for compute resources with Ovirt provider
    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'password': entity_fields.StringField(),
            'user': entity_fields.StringField(),
            'use_v4': entity_fields.BooleanField(),
            'datacenter': entity_fields.StringField(),
            'ovirt_quota': entity_fields.StringField(),
        }
        super(OVirtComputeResource, self).__init__(server_config, **kwargs)
        self._fields['provider'].default = 'Ovirt'
        self._fields['provider'].required = True
        self._fields['provider_friendly_name'].default = 'OVirt'

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Make sure, ``password`` is in the ignore list for read
        """
        if ignore is None:
            ignore = set()
        ignore.add('password')
        return super(OVirtComputeResource, self).read(
            entity, attrs, ignore, params)


class VMWareComputeResource(AbstractComputeResource):
    # pylint: disable=too-many-ancestors
    """A representation for compute resources with Vmware provider
    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'datacenter': entity_fields.StringField(),
            'password': entity_fields.StringField(),
            'set_console_password': entity_fields.BooleanField(),
            'user': entity_fields.StringField(),
        }
        super(VMWareComputeResource, self).__init__(server_config, **kwargs)
        self._fields['provider'].default = 'Vmware'
        self._fields['provider'].required = True
        self._fields['provider_friendly_name'].default = 'VMware'

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Make sure, ``password`` is in the ignore list for read
        """
        if ignore is None:
            ignore = set()
        ignore.add('password')
        return super(VMWareComputeResource, self).read(
            entity, attrs, ignore, params)


class ConfigGroup(
        Entity,
        EntityCreateMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Config Group entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
        }
        self._meta = {
            'api_path': 'api/v2/config_groups',
            'server_modes': ('sat'),
        }
        super(ConfigGroup, self).__init__(server_config, **kwargs)


class ConfigTemplate(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Config Template entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'audit_comment': entity_fields.StringField(),
            'locked': entity_fields.BooleanField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'operatingsystem': entity_fields.OneToManyField(OperatingSystem),
            'organization': entity_fields.OneToManyField(Organization),
            'location': entity_fields.OneToManyField(Location),
            'snippet': entity_fields.BooleanField(required=True),
            'template': entity_fields.StringField(required=True),
            'template_combinations': entity_fields.ListField(),
            'template_kind': entity_fields.OneToOneField(TemplateKind),
        }
        self._meta = {
            'api_path': 'api/v2/config_templates',
            'server_modes': ('sat'),
        }
        super(ConfigTemplate, self).__init__(server_config, **kwargs)

    def create_missing(self):
        """Customize the process of auto-generating instance attributes.

        Populate ``template_kind`` if:

        * this template is not a snippet, and
        * the ``template_kind`` instance attribute is unset.

        """
        super(ConfigTemplate, self).create_missing()
        if (getattr(self, 'snippet', None) is False and
                not hasattr(self, 'template_kind')):
            self.template_kind = TemplateKind(self._server_config, id=1)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        payload = super(ConfigTemplate, self).create_payload()
        if 'template_combinations' in payload:
            payload['template_combinations_attributes'] = payload.pop(
                'template_combinations')
        return {u'config_template': payload}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super(ConfigTemplate, self).update_payload(fields)
        if 'template_combinations' in payload:
            payload['template_combinations_attributes'] = payload.pop(
                'template_combinations')
        return {u'config_template': payload}

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        build_pxe_default
            /config_templates/build_pxe_default
        clone
            /config_templates/clone
        revision
            /config_templates/revision

        ``super`` is called otherwise.

        """
        if which in ('build_pxe_default', 'clone', 'revision'):
            prefix = 'self' if which == 'clone' else 'base'
            return '{0}/{1}'.format(
                super(ConfigTemplate, self).path(prefix),
                which
            )
        return super(ConfigTemplate, self).path(which)

    def build_pxe_default(self, synchronous=True, **kwargs):
        """Helper to build pxe default template.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('build_pxe_default'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def clone(self, synchronous=True, **kwargs):
        """Helper to clone an existing provision template

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('clone'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class TemplateInput(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin
):
    """A representation of a Template Input entity."""
    def __init__(self, server_config=None, **kwargs):
        _check_for_value('template', kwargs)
        self._fields = {
            'advanced': entity_fields.BooleanField(),
            'description': entity_fields.StringField(),
            'fact_name': entity_fields.StringField(),
            'input_type': entity_fields.StringField(),
            'name': entity_fields.StringField(),
            'options': entity_fields.StringField(),
            'puppet_class_name': entity_fields.StringField(),
            'puppet_parameter_name': entity_fields.StringField(),
            'required': entity_fields.BooleanField(),
            # There is no Template base class yet
            'template': entity_fields.OneToOneField(
                JobTemplate, required=True),
            'variable_name': entity_fields.StringField(),
        }
        super(TemplateInput, self).__init__(server_config, **kwargs)
        self._meta = {
            'api_path': '/api/v2/templates/{0}/template_inputs'
            .format(self.template.id),
            'server_modes': ('sat')
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Create a JobTemplate object before calling read()
        ignore 'advanced'
        """
        if entity is None:
            entity = TemplateInput(self._server_config, template=self.template)
        if ignore is None:
            ignore = set()
        ignore.add('advanced')
        return super(TemplateInput, self).read(entity=entity, attrs=attrs,
                                               ignore=ignore, params=params)


class JobInvocation(
        Entity,
        EntityReadMixin,
        EntitySearchMixin):
    """A representation of a Job invocation entity."""
    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'description': entity_fields.StringField(),
            'dynflow_task': entity_fields.OneToOneField(ForemanTask),
            'failed': entity_fields.IntegerField(),
            'job_category': entity_fields.StringField(),
            'pending': entity_fields.IntegerField(),
            'start_at': entity_fields.DateTimeField(),
            'status': entity_fields.IntegerField(),
            'status_label': entity_fields.StringField(),
            'succeeded': entity_fields.IntegerField(),
            'task': entity_fields.OneToOneField(ForemanTask),
            'targeting': entity_fields.DictField(),
            'targeting_id': entity_fields.IntegerField(),
            'template_invocations': entity_fields.ListField(),
            'total': entity_fields.IntegerField(),
        }
        self._meta = {
            'api_path': 'api/job_invocations',
            'server_modes': ('sat')}
        super(JobInvocation, self).__init__(server_config, **kwargs)

    def run(self, synchronous=True, **kwargs):
        """Helper to run existing job template

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
            'data' supports next fields:

                required:
                    job_template_id/feature,
                    targeting_type,
                    search_query/bookmark_id,
                    inputs
                optional:
                    description_format,
                    concurrency_control
                    scheduling,
                    ssh,
                    recurrence,
                    execution_timeout_interval
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        if 'data' in kwargs:
            if 'job_template_id' not in kwargs['data'] and 'feature' not in kwargs['data']:
                raise KeyError('Provide either job_template_id or feature value')
            if 'search_query' not in kwargs['data'] and 'bookmark_id' not in kwargs['data']:
                raise KeyError('Provide either search_query or bookmark_id value')
            for param_name in ['targeting_type', 'inputs']:
                if param_name not in kwargs['data']:
                    raise KeyError('Provide {} value'.format(param_name))
            kwargs['data'] = {u'job_invocation': kwargs['data']}
        response = client.post(self.path('base'), **kwargs)
        response.raise_for_status()
        if synchronous is True:
            return ForemanTask(
                server_config=self._server_config, id=response.json()['task']['id']).poll()
        return response.json()


class JobTemplate(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin
):
    """A representation of a Job Template entity."""
    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'audit_comment': entity_fields.StringField(),
            'description_format': entity_fields.StringField(),
            'effective_user': entity_fields.DictField(),
            'job_category': entity_fields.StringField(),
            'location': entity_fields.OneToManyField(Location),
            'locked': entity_fields.BooleanField(),
            'name': entity_fields.StringField(),
            'organization': entity_fields.OneToManyField(Organization),
            'provider_type': entity_fields.StringField(),
            'snippet': entity_fields.BooleanField(),
            'template': entity_fields.StringField(),
            'template_inputs': entity_fields.OneToManyField(TemplateInput),
        }
        self._meta = {
            'api_path': 'api/v2/job_templates',
            'server_modes': ('sat')}
        super(JobTemplate, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict."""

        payload = super(JobTemplate, self).create_payload()
        effective_user = payload.pop(u'effective_user', None)
        if effective_user:
            payload[u'ssh'] = {u'effective_user': effective_user}

        return {u'job_template': payload}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super(JobTemplate, self).update_payload(fields)
        effective_user = payload.pop(u'effective_user', None)
        if effective_user:
            payload[u'ssh'] = {u'effective_user': effective_user}
        return {u'job_template': payload}

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Ignore the template inputs when initially reading the job template.
            Look up each TemplateInput entity separately
            and afterwords add them to the JobTemplate entity."""
        if attrs is None:
            attrs = self.read_json(params=params)
        if ignore is None:
            ignore = set()
        ignore.add('template_inputs')
        entity = super(JobTemplate, self).read(entity=entity, attrs=attrs,
                                               ignore=ignore, params=params)
        referenced_entities = [
            TemplateInput(entity._server_config, id=entity_id,
                          template=JobTemplate(entity._server_config,
                                               id=entity.id))
            for entity_id
            in _get_entity_ids('template_inputs', attrs)
        ]
        setattr(entity, 'template_inputs', referenced_entities)
        return entity


class ProvisioningTemplate(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Provisioning Template entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'audit_comment': entity_fields.StringField(),
            'locked': entity_fields.BooleanField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'operatingsystem': entity_fields.OneToManyField(OperatingSystem),
            'organization': entity_fields.OneToManyField(Organization),
            'location': entity_fields.OneToManyField(Location),
            'snippet': entity_fields.BooleanField(required=True),
            'template': entity_fields.StringField(required=True),
            'template_combinations': entity_fields.ListField(),
            'template_kind': entity_fields.OneToOneField(TemplateKind),
        }
        self._meta = {
            'api_path': 'api/v2/provisioning_templates',
            'server_modes': ('sat'),
        }
        super(ProvisioningTemplate, self).__init__(server_config, **kwargs)

    def create_missing(self):
        """Customize the process of auto-generating instance attributes.

        Populate ``template_kind`` if:

        * this template is not a snippet, and
        * the ``template_kind`` instance attribute is unset.

        """
        super(ProvisioningTemplate, self).create_missing()
        if (getattr(self, 'snippet', None) is False and
                not hasattr(self, 'template_kind')):
            self.template_kind = TemplateKind(self._server_config, id=1)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        payload = super(ProvisioningTemplate, self).create_payload()
        if 'template_combinations' in payload:
            payload['template_combinations_attributes'] = payload.pop(
                'template_combinations')
        return {u'provisioning_template': payload}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super(ProvisioningTemplate, self).update_payload(fields)
        if 'template_combinations' in payload:
            payload['template_combinations_attributes'] = payload.pop(
                'template_combinations')
        return {u'provisioning_template': payload}

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        build_pxe_default
            /provisioning_templates/build_pxe_default
        clone
            /provisioning_templates/clone
        revision
            /provisioning_templates/revision

        ``super`` is called otherwise.

        """
        if which in ('build_pxe_default', 'clone', 'revision'):
            prefix = 'self' if which == 'clone' else 'base'
            return '{0}/{1}'.format(
                super(ProvisioningTemplate, self).path(prefix),
                which
            )
        return super(ProvisioningTemplate, self).path(which)

    def build_pxe_default(self, synchronous=True, **kwargs):
        """Helper to build pxe default template.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('build_pxe_default'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def clone(self, synchronous=True, **kwargs):
        """Helper to clone an existing provision template

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('clone'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class ReportTemplate(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Report Template entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'location': entity_fields.OneToManyField(Location),
            'template': entity_fields.StringField(required=True),
            'default': entity_fields.BooleanField(required=True),
        }
        self._meta = {
            'api_path': 'api/v2/report_templates',
            'server_modes': ('sat'),
        }
        super(ReportTemplate, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        payload = super(ReportTemplate, self).create_payload()
        if 'template_combinations' in payload:
            payload['template_combinations_attributes'] = payload.pop(
                'template_combinations')
        return {u'report_template': payload}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super(ReportTemplate, self).update_payload(fields)
        if 'template_combinations' in payload:
            payload['template_combinations_attributes'] = payload.pop(
                'template_combinations')
        return {u'report_template': payload}

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        clone
            /report_templates/clone

        ``super`` is called otherwise.

        """
        if which == 'clone':
            prefix = 'self' if which == 'clone' else 'base'
            return '{0}/{1}'.format(
                super(ReportTemplate, self).path(prefix),
                which
            )
        return super(ReportTemplate, self).path(which)

    def clone(self, synchronous=True, **kwargs):
        """Helper to clone an existing report template

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('clone'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class AbstractDockerContainer(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin):
    """A representation of a docker container.

    This class is abstract because all containers must come from somewhere, but
    this class does not have attributes for specifying that information.

    .. WARNING:: A docker compute resource must be specified when creating a
        docker container.

    """

    def __init__(self, server_config=None, **kwargs):
        fields = {
            'attach_stderr': entity_fields.BooleanField(),
            'attach_stdin': entity_fields.BooleanField(),
            'attach_stdout': entity_fields.BooleanField(),
            'command': entity_fields.StringField(required=True, default='top'),
            'compute_resource': entity_fields.OneToOneField(
                AbstractComputeResource,
                required=True,
            ),
            'cpu_set': entity_fields.StringField(),
            'cpu_shares': entity_fields.StringField(),
            'entrypoint': entity_fields.StringField(),
            'location': entity_fields.OneToManyField(Location),
            'memory': entity_fields.StringField(),
            # The "name" field may be any of a-zA-Z0-9_.-,
            # "alphanumeric" is a subset of those legal characters.
            'name': entity_fields.StringField(
                length=(2, 30),
                required=True,
                str_type='alphanumeric',
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'tty': entity_fields.BooleanField(),
        }
        fields.update(getattr(self, '_fields', {}))
        self._fields = fields
        self._meta = {
            'api_path': 'docker/api/v2/containers',
            'server_modes': ('sat'),
        }
        super(AbstractDockerContainer, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        logs
            /containers/<id>/logs
        power
            /containers/<id>/power

        ``super`` is called otherwise.

        """
        if which in ('logs', 'power'):
            return '{0}/{1}'.format(
                super(AbstractDockerContainer, self).path(which='self'),
                which
            )
        return super(AbstractDockerContainer, self).path(which)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {
            u'container': super(AbstractDockerContainer, self).create_payload()
        }

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1223540
        <https://bugzilla.redhat.com/show_bug.cgi?id=1223540>`_.

        """
        return type(self)(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def power(self, synchronous=True, **kwargs):
        """Run a power operation on a container.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('power'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def logs(self, synchronous=True, **kwargs):
        """Get logs from this container.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('logs'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class DockerHubContainer(AbstractDockerContainer):
    """A docker container that comes from Docker Hub.

    .. WARNING:: The ``repository_name`` field references an image repository
        on the `Docker Hub <https://hub.docker.com/>`, not a locally created
        :class:`nailgun.entities.Repository`.

    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'repository_name': entity_fields.StringField(
                default='busybox',
                required=True,
            ),
            'tag': entity_fields.StringField(required=True, default='latest'),
        }
        super(DockerHubContainer, self).__init__(server_config, **kwargs)


class DockerRegistryContainer(AbstractDockerContainer):
    """A docker container that comes from custom external registry.

    .. WARNING:: The ``repository_name`` field references an image repository
        on the custom registry, not a locally created
        :class:`nailgun.entities.Repository`.

    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'registry': entity_fields.OneToOneField(Registry, required=True),
            'repository_name': entity_fields.StringField(required=True),
            'tag': entity_fields.StringField(required=True, default='latest'),
        }
        super(DockerRegistryContainer, self).__init__(server_config, **kwargs)


class ContentCredential(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Content Credential entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'content': entity_fields.StringField(required=True),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'content_type': entity_fields.StringField(
                choices=('cert', 'gpg_key'),
                default='gpg_key',
                required=True,
            ),
        }
        self._meta = {
            'api_path': 'katello/api/v2/content_credentials',
            'server_modes': ('sat'),
        }
        super(ContentCredential, self).__init__(server_config, **kwargs)


class ContentUpload(
        Entity,
        EntityCreateMixin,
        EntityReadMixin,
        EntityUpdateMixin,
        EntityDeleteMixin):
    """A representation of a Content Upload entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('repository', kwargs)
        self._fields = {
            'upload_id': entity_fields.StringField(length=36, unique=True),
            'repository': entity_fields.OneToOneField(
                Repository,
                required=True,
            )
        }
        super(ContentUpload, self).__init__(server_config, **kwargs)
        # a ContentUpload does not have an id field, only an upload_id
        self._fields.pop('id')
        self._meta = {
            # pylint:disable=no-member
            'api_path': '{0}/content_uploads'.format(self.repository.path()),
            'server_modes': ('sat'),
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read`` provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`ContentUpload` requires that a ``repository`` be
        provided, so this technique will not work. Do this instead::

            entity = type(self)(repository=self.repository.id)

        """
        # read() should not change the state of the object it's called on, but
        # super() alters the attributes of any entity passed in. Creating a new
        # object and passing it to super() lets this one avoid changing state.
        if entity is None:
            entity = type(self)(
                self._server_config,
                repository=self.repository,  # pylint:disable=no-member
            )
        if ignore is None:
            ignore = set()
        ignore.add('repository')
        return super(ContentUpload, self).read(entity, attrs, ignore, params)

    def update(self, fields=None, **kwargs):
        """Update the current entity.

        Make an HTTP PUT call to ``self.path('base')``. Return the response.

        :param fields: An iterable of field names. Only the fields named in
            this iterable will be updated. No fields are updated if an empty
            iterable is passed in. All fields are updated if ``None`` is passed
            in.
        :return: A ``requests.response`` object.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        # a content upload is always multipart
        headers = kwargs.pop('headers', {})
        headers['content-type'] = 'multipart/form-data'
        kwargs['headers'] = headers
        return client.put(
            self.path('self'),
            fields,
            **kwargs
        )

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.
        """
        base = urljoin(
            self._server_config.url + '/',
            self._meta['api_path']  # pylint:disable=no-member
        )
        if (which == 'self' or which is None) and hasattr(self, 'upload_id'):
            # pylint:disable=E1101
            return urljoin(base + '/', str(self.upload_id))
        return super(ContentUpload, self).path(which)

    def upload(self, filepath, filename=None):
        """Upload content.

        :param filepath: path to the file that should be chunked and uploaded
        :param filename: name of the file on the server, defaults to the
            last part of the ``filepath`` if not set
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        :raises nailgun.entities.APIResponseError: If the response has a status
            other than "success".

        .. _POST a Multipart-Encoded File:
            http://docs.python-requests.org/en/latest/user/quickstart/#post-a-multipart-encoded-file
        .. _POST Multiple Multipart-Encoded Files:
            http://docs.python-requests.org/en/latest/user/advanced/#post-multiple-multipart-encoded-files

        """
        if not filename:
            filename = os.path.basename(filepath)

        content_upload = self.create()

        try:
            offset = 0
            content_chunk_size = 2 * 1024 * 1024

            with open(filepath, 'rb') as contentfile:
                chunk = contentfile.read(content_chunk_size)
                while len(chunk) > 0:
                    data = {'offset': offset,
                            'content': chunk}
                    content_upload.update(data)

                    offset += len(chunk)
                    chunk = contentfile.read(content_chunk_size)

            size = 0
            checksum = hashlib.sha256()
            with open(filepath, 'rb') as contentfile:
                contents = contentfile.read()
                size = len(contents)
                checksum.update(contents)

            uploads = [{'id': content_upload.upload_id, 'name': filename,
                        'size': size, 'checksum': checksum.hexdigest()}]
            # pylint:disable=no-member
            json = self.repository.import_uploads(uploads)
        finally:
            content_upload.delete()

        return json


class ContentViewVersion(
        Entity,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin):
    """A representation of a Content View Version non-entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'content_view': entity_fields.OneToOneField(ContentView),
            'description': entity_fields.StringField(),
            'environment': entity_fields.OneToManyField(LifecycleEnvironment),
            'file_count': entity_fields.IntegerField(),
            'major': entity_fields.IntegerField(),
            'minor': entity_fields.IntegerField(),
            'package_count': entity_fields.IntegerField(),
            "module_stream_count": entity_fields.IntegerField(),
            'puppet_module': entity_fields.OneToManyField(PuppetModule),
            'repository': entity_fields.OneToManyField(Repository),
            'version': entity_fields.StringField(),
        }
        self._meta = {
            'api_path': 'katello/api/v2/content_view_versions',
            'server_modes': ('sat'),
        }
        super(ContentViewVersion, self).__init__(
            server_config,
            **kwargs
        )

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        incremental_update
            /content_view_versions/incremental_update
        promote
            /content_view_versions/<id>/promote

        ``super`` is called otherwise.

        """
        if which in ('incremental_update', 'promote'):
            prefix = 'base' if which == 'incremental_update' else 'self'
            return '{0}/{1}'.format(
                super(ContentViewVersion, self).path(prefix),
                which
            )
        return super(ContentViewVersion, self).path(which)

    def incremental_update(self, synchronous=True, **kwargs):
        """Helper for incrementally updating a content view version.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('incremental_update'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def promote(self, synchronous=True, **kwargs):
        """Helper for promoting an existing published content view.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('promote'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class ContentViewFilterRule(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Content View Filter Rule entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('content_view_filter', kwargs)
        self._fields = {
            'content_view_filter': entity_fields.OneToOneField(
                AbstractContentViewFilter,
                required=True
            ),
            'date_type': entity_fields.StringField(
                choices=('issued', 'updated'),
            ),
            'end_date': entity_fields.DateField(),
            'errata': entity_fields.OneToOneField(Errata),
            'max_version': entity_fields.StringField(),
            'min_version': entity_fields.StringField(),
            'name': entity_fields.StringField(
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'start_date': entity_fields.DateField(),
            'types': entity_fields.ListField(),
            'version': entity_fields.StringField(),
            'uuid': entity_fields.StringField(),
            'architecture': entity_fields.StringField(),
        }
        super(ContentViewFilterRule, self).__init__(server_config, **kwargs)
        self._meta = {
            'server_modes': ('sat'),
            'api_path': '{0}/rules'.format(
                # pylint:disable=no-member
                self.content_view_filter.path('self')
            )
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Do not read certain fields.

        Do not expect the server to return the ``content_view_filter``
        attribute. This has no practical impact, as the attribute must be
        provided when a :class:`nailgun.entities.ContentViewFilterRule` is
        instantiated.

        Also, ignore any field that is not returned by the server. For more
        information, see `Bugzilla #1238408
        <https://bugzilla.redhat.com/show_bug.cgi?id=1238408>`_.

        """
        if entity is None:
            entity = type(self)(
                self._server_config,
                # pylint:disable=no-member
                content_view_filter=self.content_view_filter,
            )
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()
        ignore.add('content_view_filter')
        ignore.update([
            field_name
            for field_name in entity.get_fields().keys()
            if field_name not in attrs
        ])
        return super(ContentViewFilterRule, self).read(
            entity, attrs, ignore, params)

    def create_payload(self):
        """Reset ``errata_id`` from DB ID to ``errata_id``."""
        payload = super(ContentViewFilterRule, self).create_payload()
        if 'errata_id' in payload:
            if not hasattr(self.errata, 'errata_id'):
                self.errata = self.errata.read()
            payload['errata_id'] = self.errata.errata_id
        return payload

    def update_payload(self, fields=None):
        """Reset ``errata_id`` from DB ID to ``errata_id``."""
        payload = super(ContentViewFilterRule, self).update_payload(fields)
        if 'errata_id' in payload:
            if not hasattr(self.errata, 'errata_id'):
                self.errata = self.errata.read()
            payload['errata_id'] = self.errata.errata_id
        return payload

    def search_payload(self, fields=None, query=None):
        """Reset ``errata_id`` from DB ID to ``errata_id``."""
        payload = super(ContentViewFilterRule, self).search_payload(
            fields, query)
        if 'errata_id' in payload:
            if not hasattr(self.errata, 'errata_id'):
                self.errata = self.errata.read()
            payload['errata_id'] = self.errata.errata_id
        return payload


class AbstractContentViewFilter(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Content View Filter entity."""

    def __init__(self, server_config=None, **kwargs):
        # The `fields={…}; fields.update(…)` idiom lets subclasses add fields.
        fields = {
            'content_view': entity_fields.OneToOneField(
                ContentView,
                required=True
            ),
            'description': entity_fields.StringField(),
            'type': entity_fields.StringField(
                choices=('erratum', 'package_group', 'rpm'),
                required=True,
            ),
            'inclusion': entity_fields.BooleanField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'repository': entity_fields.OneToManyField(Repository),
        }
        fields.update(getattr(self, '_fields', {}))
        self._fields = fields
        self._meta = {
            'api_path': 'katello/api/v2/content_view_filters',
            'server_modes': ('sat'),
        }
        super(AbstractContentViewFilter, self).__init__(
            server_config,
            **kwargs
        )


class ErratumContentViewFilter(AbstractContentViewFilter):
    """A representation of a Content View Filter of type "erratum"."""

    def __init__(self, server_config=None, **kwargs):
        super(ErratumContentViewFilter, self).__init__(server_config, **kwargs)
        self._fields['type'].default = 'erratum'


class PackageGroupContentViewFilter(AbstractContentViewFilter):
    """A representation of a Content View Filter of type "package_group"."""

    def __init__(self, server_config=None, **kwargs):
        super(PackageGroupContentViewFilter, self).__init__(
            server_config,
            **kwargs
        )
        self._fields['type'].default = 'package_group'


class RPMContentViewFilter(AbstractContentViewFilter):
    """A representation of a Content View Filter of type "rpm"."""

    def __init__(self, server_config=None, **kwargs):
        # Add the `original_packages` field to what's provided by parent class.
        self._fields = {'original_packages': entity_fields.BooleanField()}
        super(RPMContentViewFilter, self).__init__(server_config, **kwargs)
        self._fields['type'].default = 'rpm'


class ContentViewPuppetModule(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Content View Puppet Module entity.

    ``content_view`` must be passed in when this entity is instantiated.

    :raises: ``TypeError`` if ``content_view`` is not passed in.

    """

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('content_view', kwargs)
        self._fields = {
            'author': entity_fields.StringField(),
            'content_view': entity_fields.OneToOneField(
                ContentView,
                required=True,
            ),
            'name': entity_fields.StringField(
                str_type='alpha',
                length=(6, 12),
                unique=True

            ),
        }
        super(ContentViewPuppetModule, self).__init__(server_config, **kwargs)
        self._meta = {
            'server_modes': ('sat'),
            'api_path': '{0}/content_view_puppet_modules'.format(
                self.content_view.path('self')  # pylint:disable=no-member
            )
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`ContentViewPuppetModule` requires that an
        ``content_view`` be provided, so this technique will not work. Do
        this instead::

            entity = type(self)(content_view=self.content_view.id)

        """
        # read() should not change the state of the object it's called on, but
        # super() alters the attributes of any entity passed in. Creating a new
        # object and passing it to super() lets this one avoid changing state.
        if entity is None:
            entity = type(self)(
                self._server_config,
                content_view=self.content_view,  # pylint:disable=no-member
            )
        if ignore is None:
            ignore = set()
        ignore.add('content_view')
        return super(ContentViewPuppetModule, self).read(
            entity, attrs, ignore, params)


class ContentView(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Content View entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'auto_publish': entity_fields.BooleanField(),
            'component': entity_fields.OneToManyField(ContentViewVersion),
            'composite': entity_fields.BooleanField(),
            'content_host_count': entity_fields.IntegerField(),
            'content_view_component': entity_fields.OneToManyField(ContentViewComponent),
            'description': entity_fields.StringField(),
            'environment': entity_fields.OneToManyField(LifecycleEnvironment),
            'label': entity_fields.StringField(unique=True),
            'last_published': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'next_version': entity_fields.IntegerField(),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'puppet_module': entity_fields.OneToManyField(PuppetModule),
            'repository': entity_fields.OneToManyField(Repository),
            'version': entity_fields.OneToManyField(ContentViewVersion),
        }
        self._meta = {
            'api_path': 'katello/api/v2/content_views',
            'server_modes': ('sat'),
        }
        super(ContentView, self).__init__(server_config, **kwargs)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Fetch an attribute missing from the server's response.

        For more information, see `Bugzilla #1237257
        <https://bugzilla.redhat.com/show_bug.cgi?id=1237257>`_.

        Add content_view_component to the response if needed, as
        :meth:`nailgun.entity_mixins.EntityReadMixin.read` can't initialize
        content_view_component.
        """
        if attrs is None:
            attrs = self.read_json()
        if _get_version(self._server_config) < Version('6.1'):
            org = _get_org(self._server_config, attrs['organization']['label'])
            attrs['organization'] = org.get_values()

        if ignore is None:
            ignore = set()
        ignore.add('content_view_component')
        result = super(ContentView, self).read(entity, attrs, ignore, params)
        if 'content_view_components' in attrs and attrs['content_view_components']:
            result.content_view_component = [
                ContentViewComponent(
                    self._server_config,
                    composite_content_view=result.id,
                    id=content_view_component['id'],
                )
                for content_view_component in attrs['content_view_components']
            ]
        return result

    def search(self, fields=None, query=None, filters=None):
        """Search for entities.

        :param fields: A set naming which fields should be used when generating
            a search query. If ``None``, all values on the entity are used. If
            an empty set, no values are used.
        :param query: A dict containing a raw search query. This is melded in
            to the generated search query like so:  ``{generated:
            query}.update({manual: query})``.
        :param filters: A dict. Used to filter search results locally.
        :return: A list of entities, all of type ``type(self)``.
        """
        results = self.search_json(fields, query)['results']
        results = self.search_normalize(results)
        entities = []
        for result in results:
            content_view_components = result.get('content_view_component')
            if content_view_components is not None:
                del result['content_view_component']
            entity = type(self)(self._server_config, **result)
            if content_view_components:
                entity.content_view_component = [
                    ContentViewComponent(
                        self._server_config,
                        composite_content_view=result['id'],
                        id=cvc_id,
                    )
                    for cvc_id in content_view_components
                ]
            entities.append(entity)
        if filters is not None:
            entities = self.search_filter(entities, filters)
        return entities

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        content_view_puppet_modules
            /content_views/<id>/content_view_puppet_modules
        content_view_versions
            /content_views/<id>/content_view_versions
        publish
            /content_views/<id>/publish
        available_puppet_module_names
            /content_views/<id>/available_puppet_module_names

        ``super`` is called otherwise.

        """
        if which in (
                'available_puppet_module_names',
                'available_puppet_modules',
                'content_view_puppet_modules',
                'content_view_versions',
                'copy',
                'publish'):
            return '{0}/{1}'.format(
                super(ContentView, self).path(which='self'),
                which
            )
        return super(ContentView, self).path(which)

    def publish(self, synchronous=True, **kwargs):
        """Helper for publishing an existing content view.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        if 'data' in kwargs and 'id' not in kwargs['data']:
            kwargs['data']['id'] = self.id  # pylint:disable=no-member
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('publish'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def available_puppet_modules(self, synchronous=True, **kwargs):
        """Get puppet modules available to be added to the content view.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('available_puppet_modules'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def copy(self, synchronous=True, **kwargs):
        """Clone provided content view.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        if 'data' in kwargs and 'id' not in kwargs['data']:
            kwargs['data']['id'] = self.id  # pylint:disable=no-member
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('copy'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def delete_from_environment(self, environment, synchronous=True):
        """Delete this content view version from an environment.

        This method acts much like
        :meth:`nailgun.entity_mixins.EntityDeleteMixin.delete`.  The
        documentation on that method describes how the deletion procedure works
        in general. This method differs only in accepting an ``environment``
        parameter.

        :param environment: A :class:`nailgun.entities.Environment` object. The
            environment's ``id`` parameter *must* be specified. As a
            convenience, an environment ID may be passed in instead of an
            ``Environment`` object.

        """
        if isinstance(environment, Environment):
            environment_id = environment.id
        else:
            environment_id = environment
        response = client.delete(
            '{0}/environments/{1}'.format(self.path(), environment_id),
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config, synchronous)


class ContentViewComponent(
        Entity,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Content View Components entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('composite_content_view', kwargs)
        self._fields = {
            'composite_content_view': entity_fields.OneToOneField(ContentView),
            'content_view': entity_fields.OneToOneField(ContentView),
            'content_view_version': entity_fields.OneToOneField(ContentViewVersion),
            'latest': entity_fields.BooleanField(),
        }
        super(ContentViewComponent, self).__init__(server_config, **kwargs)
        self._meta = {
            'api_path': '{0}/content_view_components'.format(self.composite_content_view.path()),
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """
        Add composite_content_view to the response if needed, as
        :meth:`nailgun.entity_mixins.EntityReadMixin.read` can't initialize
        composite_content_view.
        """
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()
        if entity is None:
            entity = type(self)(
                self._server_config,
                composite_content_view=self.composite_content_view,
            )

        ignore.add('composite_content_view')
        return super(ContentViewComponent, self).read(entity, attrs, ignore, params)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.
        The format of the returned path depends on the value of ``which``:

        add
            /content_view_components/add
        remove
            /content_view_components/remove

        Otherwise, call ``super``.

        """
        if which in (
                'add',
                'remove'):
            return '{0}/{1}'.format(
                super(ContentViewComponent, self).path(which='base'),
                which
            )

        return super(ContentViewComponent, self).path(which)

    def add(self, synchronous=True, **kwargs):
        """Add provided Content View Component.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        if 'data' not in kwargs:
            # data is required
            kwargs['data'] = dict()
        if 'component_ids' not in kwargs['data']:
            kwargs['data']['components'] = [_payload(self.get_fields(), self.get_values())]
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('add'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def remove(self, synchronous=True, **kwargs):
        """remove provided Content View Component.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        if 'data' not in kwargs:
            # data is required
            kwargs['data'] = dict()
        if 'data' in kwargs and 'component_ids' not in kwargs['data']:
            kwargs['data']['component_ids'] = [self.id]
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('remove'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class Domain(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Domain entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'dns': entity_fields.OneToOneField(SmartProxy),
            'domain_parameters_attributes': entity_fields.ListField(),
            'fullname': entity_fields.StringField(),
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
        }
        self._meta = {'api_path': 'api/v2/domains', 'server_modes': ('sat')}
        super(Domain, self).__init__(server_config, **kwargs)

    def create_missing(self):
        """Customize the process of auto-generating instance attributes.

        By default, :meth:`nailgun.entity_fields.StringField.gen_value` can
        produce strings in both lower and upper cases, but domain name should
        be always in lower case due logical reason.

        """
        if not hasattr(self, 'name'):
            self.name = gen_alphanumeric().lower()
        super(Domain, self).create_missing()

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'domain': super(Domain, self).create_payload()}

    def create(self, create_missing=None):
        """Manually fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1219654
        <https://bugzilla.redhat.com/show_bug.cgi?id=1219654>`_.

        """
        return Domain(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Deal with weirdly named data returned from the server.

        For more information, see `Bugzilla #1233245
        <https://bugzilla.redhat.com/show_bug.cgi?id=1233245>`_.

        """
        if attrs is None:
            attrs = self.read_json()
        attrs['domain_parameters_attributes'] = attrs.pop('parameters')
        return super(Domain, self).read(entity, attrs, ignore, params)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1234999
        <https://bugzilla.redhat.com/show_bug.cgi?id=1234999>`_.

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'domain': super(Domain, self).update_payload(fields)}


class Environment(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Environment entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True,
                str_type='alphanumeric',  # cannot contain whitespace
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
        }
        self._meta = {
            'api_path': 'api/v2/environments',
            'server_modes': ('sat'),
        }
        super(Environment, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'environment': super(Environment, self).create_payload()}

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1262029
        <https://bugzilla.redhat.com/show_bug.cgi?id=1262029>`_.

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {
            u'environment': super(
                Environment,
                self
            ).update_payload(fields)
        }

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.
        The format of the returned path depends on the value of ``which``:

        smart_class_parameters
            /api/environments/:environment_id/smart_class_parameters

        Otherwise, call ``super``.

        """
        if which in ('smart_class_parameters',):
            return '{0}/{1}'.format(
                super(Environment, self).path(which='self'),
                which
            )
        return super(Environment, self).path(which)

    def list_scparams(self, synchronous=True, **kwargs):
        """List all smart class parameters

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('smart_class_parameters'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class Errata(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of an Errata entity."""
    # You cannot create an errata. Errata are a read-only entity.

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'content_view_version': entity_fields.OneToOneField(
                ContentViewVersion
            ),
            'errata_id': entity_fields.StringField(),
            'cves': entity_fields.DictField(),
            'description': entity_fields.StringField(),
            'environment': entity_fields.OneToOneField(LifecycleEnvironment),
            'hosts_applicable_count': entity_fields.IntegerField(),
            'hosts_available_count': entity_fields.IntegerField(),
            'issued': entity_fields.DateField(),
            'packages': entity_fields.DictField(),
            'module_streams': entity_fields.ListField(),
            'reboot_suggested': entity_fields.BooleanField(),
            'repository': entity_fields.OneToOneField(Repository),
            'severity': entity_fields.StringField(),
            'solution': entity_fields.StringField(),
            'summary': entity_fields.StringField(),
            'type': entity_fields.StringField(
                choices=('bugfix', 'enhancement', 'security'),
            ),
            'updated': entity_fields.DateField(),
        }
        self._meta = {
            'api_path': '/katello/api/v2/errata',
            'server_modes': ('sat')
        }
        super(Errata, self).__init__(server_config, **kwargs)

    def compare(self, synchronous=True, **kwargs):
        """Compare errata from different content view versions

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('compare'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        compare
            /katello/api/errata/compare

        Otherwise, call ``super``.

        """
        if which in ('compare',):
            return '{0}/{1}'.format(super(Errata, self).path('base'), which)
        return super(Errata, self).path(which)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Following fields are only accessible for filtering search results
        and are never returned by the server: ``content_view_version_id``,
        ``environment_id``, ``repository_id``.
        """
        if ignore is None:
            ignore = set()
        ignore.add('content_view_version')
        ignore.add('environment')
        ignore.add('repository')
        return super(Errata, self).read(entity, attrs, ignore, params)


class File(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Package entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(unique=True),
            'path': entity_fields.StringField(),
            'uuid': entity_fields.StringField(),
            'checksum': entity_fields.StringField(),
            'repository': entity_fields.OneToOneField(Repository),
        }
        self._meta = {'api_path': 'katello/api/v2/files'}
        super(File, self).__init__(server_config, **kwargs)


class Filter(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Filter entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location),
            'organization': entity_fields.OneToManyField(Organization),
            'permission': entity_fields.OneToManyField(Permission),
            'role': entity_fields.OneToOneField(Role, required=True),
            'search': entity_fields.StringField(),
            'override': entity_fields.BooleanField(),
            'unlimited': entity_fields.BooleanField(),
        }
        self._meta = {'api_path': 'api/v2/filters', 'server_modes': ('sat')}
        super(Filter, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'filter': super(Filter, self).create_payload()}

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Deal with different named data returned from the server
        """
        if attrs is None:
            attrs = self.read_json()
        attrs['override'] = attrs.pop('override?')
        attrs['unlimited'] = attrs.pop('unlimited?')
        return super(Filter, self).read(entity, attrs, ignore, params)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'filter': super(Filter, self).update_payload(fields)}


class ForemanStatus(Entity, EntityReadMixin):
    """A representation of the Foreman Status entity."""
    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'result': entity_fields.StringField(),
            'status': entity_fields.IntegerField(),
            'version': entity_fields.StringField(),
            'api_version': entity_fields.IntegerField(),
        }
        self._meta = {
            'api_path': 'api/v2/status',
            'server_modes': ('sat'),
            'read_type': 'base',
        }
        super(ForemanStatus, self).__init__(server_config, **kwargs)


class ForemanTask(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Foreman task."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'cli_example': entity_fields.StringField(),
            'ended_at': entity_fields.DateTimeField(),
            'humanized': entity_fields.DictField(),
            'input': entity_fields.DictField(),
            'label': entity_fields.StringField(),
            'output': entity_fields.DictField(),
            'pending': entity_fields.BooleanField(),
            'progress': entity_fields.FloatField(),
            'result': entity_fields.StringField(),
            'started_at': entity_fields.DateTimeField(),
            'state': entity_fields.StringField(),
            'username': entity_fields.StringField(),
        }
        self._meta = {
            'api_path': 'foreman_tasks/api/tasks',
            'server_modes': ('sat'),
        }
        super(ForemanTask, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        bulk_resume
            /foreman_tasks/api/tasks/bulk_resume
        bulk_search
            /foreman_tasks/api/tasks/bulk_search
        summary
            /foreman_tasks/api/tasks/summary

        Otherwise, call ``super``.

        """
        if which in ('bulk_resume', 'bulk_search', 'summary'):
            return '{0}/{1}'.format(
                super(ForemanTask, self).path('base'),
                which
            )
        return super(ForemanTask, self).path(which)

    def poll(self, poll_rate=None, timeout=None):
        """Return the status of a task or timeout.

        There are several API calls that trigger asynchronous tasks, such as
        synchronizing a repository, or publishing or promoting a content view.
        It is possible to check on the status of a task if you know its UUID.
        This method polls a task once every ``poll_rate`` seconds and, upon
        task completion, returns information about that task.

        :param poll_rate: Delay between the end of one task check-up and
            the start of the next check-up. Defaults to
            ``nailgun.entity_mixins.TASK_POLL_RATE``.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :returns: Information about the asynchronous task.
        :raises: ``nailgun.entity_mixins.TaskTimedOutError`` if the task
            completes with any result other than "success".
        :raises: ``nailgun.entity_mixins.TaskFailedError`` if the task finishes
            with any result other than "success".
        :raises: ``requests.exceptions.HTTPError`` If the API returns a message
            with an HTTP 4XX or 5XX status code.

        """
        # See nailgun.entity_mixins._poll_task for an explanation of why a
        # private method is called.
        return _poll_task(
            self.id,  # pylint:disable=no-member
            self._server_config,
            poll_rate,
            timeout
        )

    def summary(self, synchronous=True, **kwargs):
        """Helper to view a summary of tasks.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('summary'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class GPGKey(ContentCredential):
    """A representation of a GPG Key entity."""

    def __init__(self, server_config=None, **kwargs):
        super(GPGKey, self).__init__(server_config, **kwargs)


class HostCollectionErrata(Entity):
    """A representation of a Host Collection Errata entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'errata': entity_fields.OneToManyField(Errata, required=True),
        }
        self._meta = {
            'api_path': (
                'katello/api/v2/organizations/:organization_id/'
                'host_collections/:host_collection_id/errata'
            ),
            'server_modes': ('sat'),
        }
        super(HostCollectionErrata, self).__init__(server_config, **kwargs)


class HostCollectionPackage(Entity):
    """A representation of a Host Collection Package entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'groups': entity_fields.ListField(),
            'packages': entity_fields.ListField(),
        }
        self._meta = {
            'api_path': (
                'katello/api/v2/organizations/:organization_id/'
                'host_collections/:host_collection_id/packages'
            ),
            'server_modes': ('sat'),
        }
        super(HostCollectionPackage, self).__init__(server_config, **kwargs)


class HostCollection(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Host Collection entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'description': entity_fields.StringField(),
            'host': entity_fields.OneToManyField(Host),
            'max_hosts': entity_fields.IntegerField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'unlimited_hosts': entity_fields.BooleanField(),
        }
        # The following attributes have been renamed with Satellite
        # 6.2, so we revert them to their old values if we have an
        # older version of Satellite
        if _get_version(server_config) < Version('6.2'):
            self._fields['max_content_hosts'] = self._fields.pop('max_hosts')
            self._fields['unlimited_content_hosts'] = self._fields.pop(
                'unlimited_hosts')
            self._fields['system'] = entity_fields.OneToManyField(System)
            self._fields.pop('host')

        self._meta = {
            'api_path': 'katello/api/v2/host_collections',
            'server_modes': ('sat', 'sam'),
        }
        super(HostCollection, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Rename ``system_ids`` to ``system_uuids``."""
        payload = super(HostCollection, self).create_payload()
        if 'system_ids' in payload:
            payload['system_uuids'] = payload.pop('system_ids')
        return payload

    def create(self, create_missing=None):
        """Manually fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1654383
        <https://bugzilla.redhat.com/show_bug.cgi?id=1654383>`_.

        """
        return HostCollection(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def update_payload(self, fields=None):
        """Rename ``system_ids`` to ``system_uuids``."""
        payload = super(HostCollection, self).update_payload(fields)
        if 'system_ids' in payload:
            payload['system_uuids'] = payload.pop('system_ids')
        return payload


class HostGroup(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Host Group entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'architecture': entity_fields.OneToOneField(Architecture),
            'domain': entity_fields.OneToOneField(Domain),
            'puppet_proxy': entity_fields.OneToOneField(SmartProxy),
            'puppet_ca_proxy': entity_fields.OneToOneField(SmartProxy),
            'content_source': entity_fields.OneToOneField(SmartProxy),
            'compute_resource': entity_fields.OneToOneField(AbstractComputeResource),
            'environment': entity_fields.OneToOneField(Environment),
            'kickstart_repository': entity_fields.OneToOneField(Repository),
            'lifecycle_environment': entity_fields.OneToOneField(
                LifecycleEnvironment),
            'location': entity_fields.OneToManyField(Location),
            'medium': entity_fields.OneToOneField(Media),
            'root_pass': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'operatingsystem': entity_fields.OneToOneField(OperatingSystem),
            'organization': entity_fields.OneToManyField(Organization),
            'parent': entity_fields.OneToOneField(HostGroup),
            'ptable': entity_fields.OneToOneField(PartitionTable),
            'realm': entity_fields.OneToOneField(Realm),
            'subnet': entity_fields.OneToOneField(Subnet),
        }
        if _get_version(server_config) >= Version('6.1'):
            self._fields.update({
                'content_view': entity_fields.OneToOneField(ContentView),
                'lifecycle_environment': entity_fields.OneToOneField(
                    LifecycleEnvironment),
            })
        self._meta = {'api_path': 'api/v2/hostgroups', 'server_modes': ('sat')}
        super(HostGroup, self).__init__(server_config, **kwargs)

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1235377
        <https://bugzilla.redhat.com/show_bug.cgi?id=1235377>`_.

        """
        return HostGroup(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'hostgroup': super(HostGroup, self).create_payload()}

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Deal with several bugs.

        For more information, see:

        * `Bugzilla #1235377
          <https://bugzilla.redhat.com/show_bug.cgi?id=1235377>`_
        * `Bugzilla #1235379
          <https://bugzilla.redhat.com/show_bug.cgi?id=1235379>`_
        * `Bugzilla #1450379
          <https://bugzilla.redhat.com/show_bug.cgi?id=1450379>`_

        """
        if ignore is None:
            ignore = set()
        ignore.add('root_pass')
        ignore.add('kickstart_repository')
        ignore.add('compute_resource')

        if attrs is None:
            attrs = self.read_json()
        attrs['parent_id'] = attrs.pop('ancestry')  # either an ID or None
        version = _get_version(self._server_config)
        if version >= Version('6.1') and version < Version('6.2'):
            # We cannot call `self.update_json([])`, as an ID might not be
            # present on self. However, `attrs` is guaranteed to have an ID.
            attrs2 = HostGroup(
                self._server_config,
                id=attrs['id']
            ).update_json([])
            for attr in ('content_source_id',
                         'content_view_id',
                         'lifecycle_environment_id'):
                attrs[attr] = attrs2.get(attr)
        return super(HostGroup, self).read(entity, attrs, ignore, params)

    def update(self, fields=None):
        """Deal with several bugs.

        For more information, see:

        * `Bugzilla #1235378
          <https://bugzilla.redhat.com/show_bug.cgi?id=1235378>`_
        * `Bugzilla #1235380
          <https://bugzilla.redhat.com/show_bug.cgi?id=1235380>`_

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'hostgroup': super(HostGroup, self).update_payload(fields)}

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.
        The format of the returned path depends on the value of ``which``:

        clone
            /api/hostgroups/:hostgroup_id/clone
        puppetclass_ids
            /api/hostgroups/:hostgroup_id/puppetclass_ids
        rebuild_config
            /api/hostgroups/:hostgroup_id/rebuild_config
        smart_class_parameters
            /api/hostgroups/:hostgroup_id/smart_class_parameters
        smart_class_variables
            /api/hostgroups/:hostgroup_id/smart_variables

        Otherwise, call ``super``.

        """
        if which in (
                'clone',
                'puppetclass_ids',
                'rebuild_config',
                'smart_class_parameters',
                'smart_variables'
        ):
            return '{0}/{1}'.format(
                super(HostGroup, self).path(which='self'),
                which
            )
        return super(HostGroup, self).path(which)

    def add_puppetclass(self, synchronous=True, **kwargs):
        """Add a Puppet class to host group

        Here is an example of how to use this method::
            hostgroup.add_puppetclass(data={'puppetclass_id': puppet.id})

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('puppetclass_ids'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def delete_puppetclass(self, synchronous=True, **kwargs):
        """Remove a Puppet class from host group

        Here is an example of how to use this method::
            hostgroup.delete_puppetclass(data={'puppetclass_id': puppet.id})

        Constructs path:
            /api/hostgroups/:hostgroup_id/puppetclass_ids/:id

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        path = "{0}/{1}".format(
            self.path('puppetclass_ids'),
            kwargs['data'].pop('puppetclass_id')
        )
        return _handle_response(
            client.delete(path, **kwargs), self._server_config, synchronous)

    def list_scparams(self, synchronous=True, **kwargs):
        """List all smart class parameters

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('smart_class_parameters'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def list_smart_variables(self, synchronous=True, **kwargs):
        """List all smart variables

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('smart_variables'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def clone(self, synchronous=True, **kwargs):
        """Helper to clone an existing host group

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('clone'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def rebuild_config(self, synchronous=True, **kwargs):
        """Helper to 'Rebuild orchestration config' of an existing host group

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('rebuild_config'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class HostPackage(Entity):
    """A representation of a Host Package entity."""

    def __init__(self, server_config=None, **kwargs):
        if _get_version(server_config) < Version('6.2'):
            raise NotImplementedError(
                'Your current version of Satellite does not support '
                'HostPackage entity. Please, use SystemPackage entity instead.'
            )
        _check_for_value('host', kwargs)
        self._fields = {
            'groups': entity_fields.ListField(),
            'host': entity_fields.OneToOneField(Host, required=True),
            'packages': entity_fields.ListField(),
        }
        super(HostPackage, self).__init__(server_config, **kwargs)
        self._meta = {
            # pylint:disable=no-member
            'api_path': '{0}/packages'.format(self.host.path()),
            'server_modes': ('sat'),
        }


class HostSubscription(Entity):
    """A representation of a Host Subscription entity."""

    def __init__(self, server_config=None, **kwargs):
        if _get_version(server_config) < Version('6.2'):
            raise NotImplementedError(
                'Your current version of Satellite does not support'
                'HostSubscription entity. Please, use System entity instead.'
            )
        _check_for_value('host', kwargs)
        self._fields = {
            'content_label': entity_fields.StringField(),
            'host': entity_fields.OneToOneField(Host, required=True),
            'subscriptions': entity_fields.DictField(),
            'value': entity_fields.StringField(),
        }
        super(HostSubscription, self).__init__(server_config, **kwargs)
        self._meta = {
            # pylint:disable=no-member
            'api_path': '{0}/subscriptions'.format(self.host.path()),
            'server_modes': ('sat'),
        }

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        add_subscriptions
            /hosts/<id>/add_subscriptions
        remove_subscriptions
            /hosts/<id>/remove_subscriptions

        ``super`` is called otherwise.

        """
        if which in (
                'add_subscriptions',
                'remove_subscriptions'):
            return '{0}/{1}'.format(
                super(HostSubscription, self).path(which='base'),
                which
            )
        return super(HostSubscription, self).path(which)

    def add_subscriptions(self, synchronous=True, **kwargs):
        """Helper for adding subscriptions to host

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('add_subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def remove_subscriptions(self, synchronous=True, **kwargs):
        """Helper for removing subscriptions from host

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('remove_subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class Host(  # pylint:disable=too-many-instance-attributes,R0904
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin,
        EntitySearchMixin):
    """A representation of a Host entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'all_parameters': entity_fields.ListField(),
            'architecture': entity_fields.OneToOneField(Architecture),
            'build': entity_fields.BooleanField(),
            'build_status_label': entity_fields.StringField(),
            'capabilities': entity_fields.StringField(),
            'comment': entity_fields.StringField(),
            'compute_attributes': entity_fields.DictField(),
            'compute_profile': entity_fields.OneToOneField(ComputeProfile),
            'compute_resource': entity_fields.OneToOneField(
                AbstractComputeResource),
            'content_facet_attributes': entity_fields.DictField(),
            'domain': entity_fields.OneToOneField(Domain),
            'enabled': entity_fields.BooleanField(),
            'environment': entity_fields.OneToOneField(Environment),
            'hostgroup': entity_fields.OneToOneField(HostGroup),
            'host_parameters_attributes': entity_fields.ListField(),
            'image': entity_fields.OneToOneField(Image),
            'interface': entity_fields.OneToManyField(Interface),
            'interfaces_attributes': entity_fields.ListField(),
            'ip': entity_fields.StringField(),
            'location': entity_fields.OneToOneField(Location, required=True),
            'mac': entity_fields.MACAddressField(),
            'managed': entity_fields.BooleanField(),
            'medium': entity_fields.OneToOneField(Media),
            'model': entity_fields.OneToOneField(Model),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'operatingsystem': entity_fields.OneToOneField(OperatingSystem),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'owner': entity_fields.OneToOneField(User),
            'owner_type': entity_fields.StringField(
                choices=('User', 'Usergroup'),
            ),
            'provision_method': entity_fields.StringField(),
            'ptable': entity_fields.OneToOneField(PartitionTable),
            'puppet_ca_proxy': entity_fields.OneToOneField(SmartProxy),
            'puppetclass': entity_fields.OneToManyField(PuppetClass),
            'puppet_proxy': entity_fields.OneToOneField(SmartProxy),
            'realm': entity_fields.OneToOneField(Realm),
            'root_pass': entity_fields.StringField(
                length=(8, 30), str_type='alpha'),
            'subnet': entity_fields.OneToOneField(Subnet),
            'uuid': entity_fields.StringField(),
        }
        self._owner_type = None  # actual ``owner_type`` value
        self._meta = {'api_path': 'api/v2/hosts', 'server_modes': ('sat')}
        super(Host, self).__init__(server_config, **kwargs)

        # See https://github.com/SatelliteQE/nailgun/issues/258
        if (hasattr(self, 'owner') and hasattr(self.owner, 'id') and
                isinstance(self.owner.id, Entity)):  # pylint:disable=no-member
            self.owner = self.owner.id  # pylint:disable=no-member

    @property
    def owner_type(self):
        """Return ``_owner_type``."""
        return self._owner_type

    @owner_type.setter
    def owner_type(self, value):
        """Set ``owner_type`` to the given value.

        In addition:

        * Update the internal type of the ``owner`` field.
        * Update the value of the ``owner`` field if a value is already set.
        """
        self._owner_type = value
        if value == 'User':
            self._fields['owner'] = entity_fields.OneToOneField(User)
            if hasattr(self, 'owner'):
                # pylint:disable=no-member
                self.owner = User(
                    self._server_config,
                    id=self.owner.id if isinstance(self.owner, Entity)
                    else self.owner
                )
        elif value == 'Usergroup':
            self._fields['owner'] = entity_fields.OneToOneField(UserGroup)
            if hasattr(self, 'owner'):
                # pylint:disable=no-member
                self.owner = UserGroup(
                    self._server_config,
                    id=self.owner.id if isinstance(self.owner, Entity)
                    else self.owner
                )

    def get_values(self):
        """Correctly set the ``owner_type`` attribute."""
        attrs = super(Host, self).get_values()
        if '_owner_type' in attrs and attrs['_owner_type'] is not None:
            attrs['owner_type'] = attrs.pop('_owner_type')
        else:
            attrs.pop('_owner_type')
        return attrs

    def create_missing(self):
        """Create a bogus managed host.

        The exact set of attributes that are required varies depending on
        whether the host is managed or inherits values from a host group and
        other factors. Unfortunately, the rules for determining which
        attributes should be filled in are mildly complex, and it is hard to
        know which scenario a user is aiming for.

        Populate the values necessary to create a bogus managed host. The
        resultant dependency graph will look, in part, like this::

                 .-> medium --------.
                 |-> architecture <-V-.
            host --> operatingsystem -|
                 |-> ptable <---------'
                 |-> domain
                 '-> environment

        If nested entities were passed by `id` (i.e. entity was only
        initialized and not read, and therefore contains only `id` field)
        perform additional read request.
        """
        # pylint:disable=no-member,too-many-branches,too-many-statements
        super(Host, self).create_missing()
        # See: https://bugzilla.redhat.com/show_bug.cgi?id=1227854
        self.name = self.name.lower()
        if not hasattr(self, 'mac'):
            self.mac = self._fields['mac'].gen_value()
        if not hasattr(self, 'root_pass'):
            self.root_pass = self._fields['root_pass'].gen_value()

        # Flesh out the dependency graph shown in the docstring.
        if not hasattr(self, 'domain'):
            self.domain = Domain(
                self._server_config,
                location=[self.location],
                organization=[self.organization],
            ).create(True)
        else:
            if not hasattr(self.domain, 'organization'):
                self.domain = self.domain.read()
            if self.location.id not in [
                    loc.id for loc in self.domain.location]:
                self.domain.location.append(self.location)
                self.domain.update(['location'])
            if self.organization.id not in [
                    org.id for org in self.domain.organization]:
                self.domain.organization.append(self.organization)
                self.domain.update(['organization'])
        if not hasattr(self, 'environment'):
            self.environment = Environment(
                self._server_config,
                location=[self.location],
                organization=[self.organization],
            ).create(True)
        else:
            if not hasattr(self.environment, 'organization'):
                self.environment = self.environment.read()
            if self.location.id not in [
                    loc.id for loc in self.environment.location]:
                self.environment.location.append(self.location)
                self.environment.update(['location'])
            if self.organization.id not in [
                    org.id for org in self.environment.organization]:
                self.environment.organization.append(self.organization)
                self.environment.update(['organization'])
        if not hasattr(self, 'architecture'):
            self.architecture = Architecture(self._server_config).create(True)
        if not hasattr(self, 'ptable'):
            if _get_version(self._server_config) >= Version('6.2'):
                self.ptable = PartitionTable(
                    self._server_config,
                    location=[self.location],
                    organization=[self.organization],
                ).create(True)
            else:
                self.ptable = PartitionTable(self._server_config).create(True)
        if not hasattr(self, 'operatingsystem'):
            self.operatingsystem = OperatingSystem(
                self._server_config,
                architecture=[self.architecture],
                ptable=[self.ptable],
            ).create(True)
        else:
            if not hasattr(self.operatingsystem, 'architecture'):
                self.operatingsystem = self.operatingsystem.read()
            if self.architecture.id not in [
                    arch.id for arch in self.operatingsystem.architecture]:
                self.operatingsystem.architecture.append(self.architecture)
                self.operatingsystem.update(['architecture'])
            if self.ptable.id not in [
                    ptable.id for ptable in self.operatingsystem.ptable]:
                self.operatingsystem.ptable.append(self.ptable)
                self.operatingsystem.update(['ptable'])
        if not hasattr(self, 'medium'):
            self.medium = Media(
                self._server_config,
                operatingsystem=[self.operatingsystem],
                location=[self.location],
                organization=[self.organization],
            ).create(True)
        else:
            if not hasattr(self.medium, 'organization'):
                self.medium = self.medium.read()
            if self.operatingsystem.id not in [
                    operatingsystem.id for operatingsystem in
                    self.medium.operatingsystem]:
                self.medium.operatingsystem.append(self.operatingsystem)
                self.medium.update(['operatingsystem'])
            if self.location.id not in [
                    loc.id for loc in self.medium.location]:
                self.medium.location.append(self.location)
                self.medium.update(['location'])
            if self.organization.id not in [
                    org.id for org in self.medium.organization]:
                self.medium.organization.append(self.organization)
                self.medium.update(['organization'])

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'host': super(Host, self).create_payload()}

    def create(self, create_missing=None):
        """Manually fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1449749
        <https://bugzilla.redhat.com/show_bug.cgi?id=1449749>`_.
        """
        return Host(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def enc(self, synchronous=True, **kwargs):
        """Return external node classifier (ENC) information

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('enc'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def errata(self, synchronous=True, **kwargs):
        """List errata available for the host

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('errata'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def packages(self, synchronous=True, **kwargs):
        """List packages installed on the host

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('packages'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def module_streams(self, synchronous=True, **kwargs):
        """List module_streams available for the host

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('module_streams'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def errata_applicability(self, synchronous=True, **kwargs):
        """Force regenerate errata applicability

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('errata/applicability'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def errata_apply(self, synchronous=True, **kwargs):
        """Schedule errata for installation

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('errata/apply'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def install_content(self, synchronous=True, **kwargs):
        """Install content on one or more hosts

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('bulk/install_content'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def get_facts(self, synchronous=True, **kwargs):
        """List all fact values of a given host

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('facts'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def upload_facts(self, synchronous=True, **kwargs):
        """Upload facts for a host, creating the host if required

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('upload_facts'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Deal with oddly named and structured data returned by the server.

        For more information, see `Bugzilla #1235019
        <https://bugzilla.redhat.com/show_bug.cgi?id=1235019>`_
        and `Bugzilla #1449749
        <https://bugzilla.redhat.com/show_bug.cgi?id=1449749>`_.

        `content_facet_attributes` are returned only in case any of facet
        attributes were actually set.

        Also add image to the response if needed, as
        :meth:`nailgun.entity_mixins.EntityReadMixin.read` can't initialize
        image.
        """
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()
        if 'parameters' in attrs:
            attrs['host_parameters_attributes'] = attrs.pop('parameters')
        else:
            ignore.add('host_parameters_attributes')
        if 'content_facet_attributes' not in attrs:
            ignore.add('content_facet_attributes')
        ignore.add('compute_attributes')
        ignore.add('interfaces_attributes')
        ignore.add('root_pass')
        # Image entity requires compute_resource_id to initialize as it is
        # part of its path. The thing is that entity_mixins.read() initializes
        # entities by id only.
        # Workaround is to add image to ignore, call entity_mixins.read()
        # and then add 'manually' initialized image to the result.
        # If image_id is None set image to None as it is done by default.
        ignore.add('image')
        # host id is required for interface initialization
        ignore.add('interface')
        ignore.add('build_status_label')
        result = super(Host, self).read(entity, attrs, ignore, params)
        if attrs.get('image_id'):
            result.image = Image(
                server_config=self._server_config,
                id=attrs.get('image_id'),
                compute_resource=attrs.get('compute_resource_id'),
            )
        else:
            result.image = None
        if 'interfaces' in attrs and attrs['interfaces']:
            result.interface = [
                Interface(
                    self._server_config,
                    host=result.id,
                    id=interface['id'],
                )
                for interface in attrs['interfaces']
            ]
        if 'build_status_label' in attrs:
            result.build_status_label = attrs['build_status_label']
        return result

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1235049
        <https://bugzilla.redhat.com/show_bug.cgi?id=1235049>`_.

        .. WARNING:: Several attributes cannot be updated. See `Bugzilla
            #1235041 <https://bugzilla.redhat.com/show_bug.cgi?id=1235041>`_.

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'host': super(Host, self).update_payload(fields)}

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.
        The format of the returned path depends on the value of ``which``:

        bulk/install_content
            /api/hosts/:host_id/bulk/install_content
        errata
            /api/hosts/:host_id/errata
        power
            /api/hosts/:host_id/power
        errata/apply
            /api/hosts/:host_id/errata/apply
        puppetclass_ids
            /api/hosts/:host_id/puppetclass_ids
        smart_class_parameters
            /api/hosts/:host_id/smart_class_parameters
        smart_variables
            /api/hosts/:host_id/smart_class_variables
        module_streams
            /api/hosts/:host_id/module_streams

        Otherwise, call ``super``.

        """
        if which in (
                'enc',
                'errata',
                'errata/apply',
                'errata/applicability',
                'facts',
                'packages',
                'power',
                'puppetclass_ids',
                'smart_class_parameters',
                'smart_variables',
                'module_streams',
        ):
            return '{0}/{1}'.format(
                super(Host, self).path(which='self'),
                which
            )
        elif which in ('bulk/install_content',):
            return '{0}/{1}'.format(
                super(Host, self).path(which='base'),
                which
            )
        elif which in ('upload_facts',):
            return '{0}/{1}'.format(
                super(Host, self).path(which='base'),
                'facts'
            )
        return super(Host, self).path(which)

    def add_puppetclass(self, synchronous=True, **kwargs):
        """Add a Puppet class to host

        Here is an example of how to use this method::
            host.add_puppetclass(data={'puppetclass_id': puppet.id})

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('puppetclass_ids'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def delete_puppetclass(self, synchronous=True, **kwargs):
        """Remove a Puppet class from host

        Here is an example of how to use this method::
            host.delete_puppetclass(data={'puppetclass_id': puppet.id})

        Constructs path:
           /api/hosts/:hostgroup_id/puppetclass_ids/:id

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        path = "{0}/{1}".format(
            self.path('puppetclass_ids'),
            kwargs['data'].pop('puppetclass_id')
        )
        return _handle_response(
            client.delete(path, **kwargs), self._server_config, synchronous)

    def list_scparams(self, synchronous=True, **kwargs):
        """List all smart class parameters

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('smart_class_parameters'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def list_smart_variables(self, synchronous=True, **kwargs):
        """List all smart variables

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('smart_variables'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def power(self, synchronous=True, **kwargs):
        """Power the host off or on

        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('power'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def search(self, fields=None, query=None, filters=None):
        """Search for entities.

        :param fields: A set naming which fields should be used when generating
            a search query. If ``None``, all values on the entity are used. If
            an empty set, no values are used.
        :param query: A dict containing a raw search query. This is melded in
            to the generated search query like so:  ``{generated:
            query}.update({manual: query})``.
        :param filters: A dict. Used to filter search results locally.
        :return: A list of entities, all of type ``type(self)``.
        """
        results = self.search_json(fields, query)['results']
        results = self.search_normalize(results)
        entities = []
        for result in results:
            image = result.get('image')
            if image is not None:
                del result['image']
            entity = type(self)(self._server_config, **result)
            if image:
                entity.image = Image(
                    server_config=self._server_config,
                    id=image,
                    compute_resource=AbstractComputeResource(
                        server_config=self._server_config,
                        id=result.get('compute_resource')
                    ),
                )
            entities.append(entity)
        if filters is not None:
            entities = self.search_filter(entities, filters)
        return entities


class Image(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Image entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('compute_resource', kwargs)
        self._fields = {
            'architecture': entity_fields.OneToOneField(
                Architecture,
                required=True
            ),
            'compute_resource': entity_fields.OneToOneField(
                AbstractComputeResource,
                required=True
            ),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'operatingsystem': entity_fields.OneToOneField(
                OperatingSystem,
                required=True
            ),
            'username': entity_fields.StringField(required=True),
            'uuid': entity_fields.StringField(required=True),
        }
        super(Image, self).__init__(server_config, **kwargs)
        self._meta = {
            'api_path': '{0}/images'.format(
                # pylint:disable=no-member
                self.compute_resource.path('self')),
            'server_modes': ('sat'),
        }

    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {u'image': super(Image, self).create_payload()}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'image': super(Image, self).update_payload(fields)}

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read`` provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`Image` requires that an
        ``compute_resource`` be provided, so this technique will not work. Do
        this instead::

            entity = type(self)(compute_resource=self.compute_resource.id)

        """
        # read() should not change the state of the object it's called on, but
        # super() alters the attributes of any entity passed in. Creating a new
        # object and passing it to super() lets this one avoid changing state.
        if entity is None:
            entity = type(self)(
                self._server_config,
                compute_resource=self.compute_resource,  # pylint:disable=E1101
            )
        if ignore is None:
            ignore = set()
        ignore.add('compute_resource')
        return super(Image, self).read(entity, attrs, ignore, params)


class Interface(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Interface entity.

    ``host`` must be passed in when this entity is instantiated.

    :raises: ``TypeError`` if ``host`` is not passed in.
    """

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('host', kwargs)
        self._fields = {
            'attached_devices': entity_fields.DictField(),  # for 'bond' or ...
            # ... 'bridge' type
            'attached_to': entity_fields.StringField(),  # for 'virtual' type
            'bond_options': entity_fields.StringField(),  # for 'bond' type
            'domain': entity_fields.OneToOneField(Domain),
            'host': entity_fields.OneToOneField(Host, required=True),
            'identifier': entity_fields.StringField(),
            'ip': entity_fields.IPAddressField(required=True),
            'mac': entity_fields.MACAddressField(required=True),
            'managed': entity_fields.BooleanField(),
            'mode': entity_fields.StringField(  # for 'bond' type
                choices=('802.3ad', 'active-backup', 'balance-alb',
                         'balance-rr', 'balance-tlb', 'balance-xor',
                         'broadcast')
            ),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
            'password': entity_fields.StringField(),  # for 'bmc' type
            'primary': entity_fields.BooleanField(),
            'provider': entity_fields.StringField(),  # for 'bmc' type
            'provision': entity_fields.BooleanField(),
            'subnet': entity_fields.OneToOneField(Subnet),
            'tag': entity_fields.StringField(),  # for 'virtual' type
            'type': entity_fields.StringField(
                choices=('interface', 'bmc', 'bond', 'bridge'),
                default='interface',
                required=True),

            'virtual': entity_fields.BooleanField(),
            'username': entity_fields.StringField(),  # for 'bmc' type
        }
        super(Interface, self).__init__(server_config, **kwargs)
        self._meta = {
            # pylint:disable=no-member
            'api_path': '{}/interfaces'.format(self.host.path()),
            'server_modes': ('sat'),
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read`` provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`Interface` requires that a ``host`` must be provided,
        so this technique will not work. Do this instead::

            entity = type(self)(host=self.host)

        In addition, some of interface fields are specific to its ``type`` and
        are never returned for different ``type`` so ignoring all the redundant
        fields.

        """
        # read() should not change the state of the object it's called on, but
        # super() alters the attributes of any entity passed in. Creating a new
        # object and passing it to super() lets this one avoid changing state.
        if entity is None:
            entity = type(self)(
                self._server_config,
                host=self.host,  # pylint:disable=no-member
            )
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()
        ignore.add('host')
        # type-specific fields
        if attrs['type'] != 'bmc':
            ignore.add('password')
            ignore.add('provider')
            ignore.add('username')
        if attrs['type'] != 'bond':
            ignore.add('mode')
            ignore.add('bond_options')
        if attrs['type'] != 'virtual':
            ignore.add('attached_to')
            ignore.add('tag')
        if attrs['type'] != 'bridge' and attrs['type'] != 'bond':
            ignore.add('attached_devices')
        return super(Interface, self).read(entity, attrs, ignore, params)

    def search_normalize(self, results):
        """Append host id to search results to be able to initialize found
        :class:`Interface` successfully
        """
        for interface in results:
            interface[u'host_id'] = self.host.id  # pylint:disable=no-member
        return super(Interface, self).search_normalize(results)


class LifecycleEnvironment(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Lifecycle Environment entity."""

    def __init__(self, server_config=None, **kwargs):
        # NOTE: The "prior" field is unusual. See `create_missing`'s docstring.
        self._fields = {
            'description': entity_fields.StringField(),
            'label': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'prior': entity_fields.OneToOneField(LifecycleEnvironment),
            'registry_name_pattern': entity_fields.StringField(),
            'registry_unauthenticated_pull': entity_fields.BooleanField(),
        }
        self._meta = {
            'api_path': 'katello/api/v2/environments',
            'server_modes': ('sat'),
        }
        super(LifecycleEnvironment, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Rename the payload key "prior_id" to "prior".

        For more information, see `Bugzilla #1238757
        <https://bugzilla.redhat.com/show_bug.cgi?id=1238757>`_.

        """
        payload = super(LifecycleEnvironment, self).create_payload()
        if (_get_version(self._server_config) < Version('6.1') and
                'prior_id' in payload):
            payload['prior'] = payload.pop('prior_id')
        return payload

    def create_missing(self):
        """Automatically populate additional instance attributes.

        When a new lifecycle environment is created, it must either:

        * Reference a parent lifecycle environment in the tree of lifecycle
          environments via the ``prior`` field, or
        * have a name of "Library".

        Within a given organization, there can only be a single lifecycle
        environment with a name of 'Library'. This lifecycle environment is at
        the root of a tree of lifecycle environments, so its ``prior`` field is
        blank.

        This method finds the 'Library' lifecycle environment within the
        current organization and points to it via the ``prior`` field. This is
        not done if the current lifecycle environment has a name of 'Library'.

        """
        # We call `super` first b/c it populates `self.organization`, and we
        # need that field to perform a search a little later.
        super(LifecycleEnvironment, self).create_missing()
        if (self.name != 'Library' and  # pylint:disable=no-member
                not hasattr(self, 'prior')):
            results = self.search({'organization'}, {u'name': u'Library'})
            if len(results) != 1:
                raise APIResponseError(
                    u'Could not find the "Library" lifecycle environment for '
                    u'organization {0}. Search results: {1}'
                    .format(self.organization, results)  # pylint:disable=E1101
                )
            self.prior = results[0]


class Location(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Location entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'compute_resource': entity_fields.OneToManyField(
                AbstractComputeResource),
            'config_template': entity_fields.OneToManyField(ConfigTemplate),
            'description': entity_fields.StringField(),
            'domain': entity_fields.OneToManyField(Domain),
            'environment': entity_fields.OneToManyField(Environment),
            'hostgroup': entity_fields.OneToManyField(HostGroup),
            'medium': entity_fields.OneToManyField(Media),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'parent': entity_fields.OneToOneField(Location),
            'provisioning_template': entity_fields.OneToManyField(
                ProvisioningTemplate),
            'realm': entity_fields.OneToManyField(Realm),
            'smart_proxy': entity_fields.OneToManyField(SmartProxy),
            'subnet': entity_fields.OneToManyField(Subnet),
            'user': entity_fields.OneToManyField(User),
        }
        self._meta = {'api_path': 'api/v2/locations', 'server_modes': ('sat')}
        super(Location, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {
            u'location': super(Location, self).create_payload()
        }

    def create(self, create_missing=None):
        """Manually fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1216236
        <https://bugzilla.redhat.com/show_bug.cgi?id=1216236>`_.

        """
        attrs = self.create_json(create_missing)
        return Location(self._server_config, id=attrs['id']).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Work around a bug in the server's response.

        Do not read the ``realm`` attribute. See `Bugzilla #1216234
        <https://bugzilla.redhat.com/show_bug.cgi?id=1216234>`_.

        """
        if ignore is None:
            ignore = set()
        ignore.add('realm')
        return super(Location, self).read(entity, attrs, ignore, params)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        Beware of `Bugzilla #1236008
        <https://bugzilla.redhat.com/show_bug.cgi?id=1236008>`_:
        "Cannot use HTTP PUT to associate location with media"

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {
            u'location': super(Location, self).update_payload(fields)
        }


class Media(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Media entity.

    .. NOTE:: The ``path_`` field is named as such due to a naming conflict
        with :meth:`nailgun.entity_mixins.Entity.path`.

    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'path_': entity_fields.URLField(required=True),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'operatingsystem': entity_fields.OneToManyField(OperatingSystem),
            'organization': entity_fields.OneToManyField(Organization),
            'location': entity_fields.OneToManyField(Location),
            'os_family': entity_fields.StringField(choices=_OPERATING_SYSTEMS),
        }
        self._meta = {'api_path': 'api/v2/media', 'server_modes': ('sat')}
        super(Media, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict and rename ``path_``.

        For more information on wrapping submitted data, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        payload = super(Media, self).create_payload()
        if 'path_' in payload:
            payload['path'] = payload.pop('path_')
        return {u'medium': payload}

    def create(self, create_missing=None):
        """Manually fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1219653
        <https://bugzilla.redhat.com/show_bug.cgi?id=1219653>`_.

        """
        return Media(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Rename ``path`` to ``path_``."""
        if attrs is None:
            attrs = self.read_json()
        attrs['path_'] = attrs.pop('path')
        return super(Media, self).read(entity, attrs, ignore, params)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        Beware of `Bugzilla #1261047
        <https://bugzilla.redhat.com/show_bug.cgi?id=1261047>`_:
        "PUT /api/v2/medium/:id doesn't return all attributes"

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super(Media, self).update_payload(fields)
        if 'path_' in payload:
            payload['path'] = payload.pop('path_')
        return {u'medium': payload}


class Model(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Model entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'hardware_model': entity_fields.StringField(),
            'info': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'vendor_class': entity_fields.StringField(),
        }
        self._meta = {'api_path': 'api/v2/models', 'server_modes': ('sat')}
        super(Model, self).__init__(server_config, **kwargs)


class OperatingSystem(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Operating System entity.

    ``major`` is listed as a string field in the API docs, but only numeric
    values are accepted, and they may be no longer than 5 digits long. Also see
    `Bugzilla #1122261 <https://bugzilla.redhat.com/show_bug.cgi?id=1122261>`_.

    ``title`` field is valid despite not being listed in the API docs. This may
    be changed in future as both ``title`` and ``description`` fields share
    similar purpose. See `Bugzilla #1290359
    <https://bugzilla.redhat.com/show_bug.cgi?id=1290359>`_ for more details.
    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'architecture': entity_fields.OneToManyField(Architecture),
            'description': entity_fields.StringField(),
            'family': entity_fields.StringField(choices=_OPERATING_SYSTEMS),
            'major': entity_fields.StringField(
                length=(1, 5),
                required=True,
                str_type='numeric',
            ),
            'medium': entity_fields.OneToManyField(Media),
            'minor': entity_fields.StringField(
                length=(1, 16),
                str_type='numeric',
            ),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'ptable': entity_fields.OneToManyField(PartitionTable),
            'config_template': entity_fields.OneToManyField(ConfigTemplate),
            'provisioning_template': entity_fields.OneToManyField(
                ProvisioningTemplate),
            'release_name': entity_fields.StringField(),
            'password_hash': entity_fields.StringField(
                choices=('MD5', 'SHA256', 'SHA512'),
                default='MD5',
            ),
            'title': entity_fields.StringField(),
        }
        self._meta = {
            'api_path': 'api/v2/operatingsystems',
            'server_modes': ('sat'),
        }
        super(OperatingSystem, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {
            u'operatingsystem': super(OperatingSystem, self).create_payload()
        }

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {
            u'operatingsystem': super(
                OperatingSystem,
                self
            ).update_payload(fields)
        }


class OperatingSystemParameter(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a parameter for an operating system.

    ``organization`` must be passed in when this entity is instantiated.

    :raises: ``TypeError`` if ``operatingsystem`` is not passed in.

    """

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('operatingsystem', kwargs)
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'operatingsystem': entity_fields.OneToOneField(
                OperatingSystem,
                required=True,
            ),
            'value': entity_fields.StringField(required=True),
        }
        super(OperatingSystemParameter, self).__init__(server_config, **kwargs)
        self._meta = {
            'api_path': '{0}/parameters'.format(
                self.operatingsystem.path('self')  # pylint:disable=no-member
            ),
            'server_modes': ('sat'),
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read`` provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`OperatingSystemParameter` requires that an
        ``operatingsystem`` be provided, so this technique will not work. Do
        this instead::

            entity = type(self)(operatingsystem=self.operatingsystem.id)

        """
        # read() should not change the state of the object it's called on, but
        # super() alters the attributes of any entity passed in. Creating a new
        # object and passing it to super() lets this one avoid changing state.
        if entity is None:
            entity = type(self)(
                self._server_config,
                operatingsystem=self.operatingsystem,  # pylint:disable=E1101
            )
        if ignore is None:
            ignore = set()
        ignore.add('operatingsystem')
        return super(OperatingSystemParameter, self).read(
            entity,
            attrs,
            ignore,
            params
        )


class Organization(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of an Organization entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'compute_resource': entity_fields.OneToManyField(
                AbstractComputeResource
            ),
            'config_template': entity_fields.OneToManyField(ConfigTemplate),
            'description': entity_fields.StringField(),
            'domain': entity_fields.OneToManyField(Domain),
            'environment': entity_fields.OneToManyField(Environment),
            'hostgroup': entity_fields.OneToManyField(HostGroup),
            'label': entity_fields.StringField(str_type='alpha'),
            'medium': entity_fields.OneToManyField(Media),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'provisioning_template': entity_fields.OneToManyField(
                ProvisioningTemplate),
            'realm': entity_fields.OneToManyField(Realm),
            'redhat_repository_url': entity_fields.URLField(),
            'smart_proxy': entity_fields.OneToManyField(SmartProxy),
            'subnet': entity_fields.OneToManyField(Subnet),
            'title': entity_fields.StringField(),
            'user': entity_fields.OneToManyField(User),
        }
        if _get_version(server_config) >= Version('6.1.1'):  # default: True
            self._fields.update({
                'default_content_view': entity_fields.OneToOneField(
                    ContentView
                ),
                'library': entity_fields.OneToOneField(LifecycleEnvironment),
            })
        self._meta = {
            'api_path': 'katello/api/v2/organizations',
            'server_modes': ('sat', 'sam'),
        }
        super(Organization, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        download_debug_certificate
            /organizations/<id>/download_debug_certificate
        subscriptions
            /organizations/<id>/subscriptions
        subscriptions/upload
            /organizations/<id>/subscriptions/upload
        subscriptions/delete_manifest
            /organizations/<id>/subscriptions/delete_manifest
        subscriptions/refresh_manifest
            /organizations/<id>/subscriptions/refresh_manifest
        sync_plans
            /organizations/<id>/sync_plans

        Otherwise, call ``super``.

        """
        if which in (
                'download_debug_certificate',
                'subscriptions',
                'subscriptions/delete_manifest',
                'subscriptions/manifest_history',
                'subscriptions/refresh_manifest',
                'subscriptions/upload',
                'sync_plans',
        ):
            return '{0}/{1}'.format(
                super(Organization, self).path(which='self'),
                which
            )
        return super(Organization, self).path(which)

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1230873
        <https://bugzilla.redhat.com/show_bug.cgi?id=1230873>`_.

        """
        return Organization(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Fetch as many attributes as possible for this entity.

        Do not read the ``realm`` attribute. For more information, see
        `Bugzilla #1230873
        <https://bugzilla.redhat.com/show_bug.cgi?id=1230873>`_.

        """
        if ignore is None:
            ignore = set()
        ignore.add('realm')
        return super(Organization, self).read(entity, attrs, ignore, params)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1232871
        <https://bugzilla.redhat.com/show_bug.cgi?id=1232871>`_.

        .. WARNING:: Several attributes cannot be updated. See `Bugzilla
            #1230865 <https://bugzilla.redhat.com/show_bug.cgi?id=1230865>`_.

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        org_payload = super(Organization, self).update_payload(fields)
        payload = {u'organization': org_payload}
        if 'redhat_repository_url' in org_payload:
            rh_repo_url = org_payload.pop('redhat_repository_url')
            payload['redhat_repository_url'] = rh_repo_url
        return payload

    def download_debug_certificate(self, synchronous=True, **kwargs):
        """Get debug certificate for particular organization.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(
            self.path('download_debug_certificate'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class OSDefaultTemplate(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a OS Default Template entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('operatingsystem', kwargs)
        self._fields = {
            'config_template': entity_fields.OneToOneField(ConfigTemplate),
            'operatingsystem': entity_fields.OneToOneField(
                OperatingSystem,
                required=True,
            ),
            'provisioning_template': entity_fields.OneToOneField(
                ProvisioningTemplate),
            'template_kind': entity_fields.OneToOneField(TemplateKind),
        }
        super(OSDefaultTemplate, self).__init__(server_config, **kwargs)
        self._meta = {
            'api_path': '{0}/os_default_templates'.format(
                self.operatingsystem.path('self')  # pylint:disable=no-member
            ),
            'server_modes': ('sat'),
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Fetch as many attributes as possible for this entity.
        Since operatingsystem is needed to instanciate, prepare the entity
        accordingly.
        """
        if entity is None:
            entity = type(self)(
                self._server_config,
                # pylint:disable=no-member
                operatingsystem=self.operatingsystem,
                # pylint:enable=no-member
            )
        if ignore is None:
            ignore = set()
        ignore.add('operatingsystem')
        return super(OSDefaultTemplate, self).read(
            entity, attrs, ignore, params)

    def update_payload(self, fields=None):
        """Wrap payload in ``os_default_template``
        relates to `Redmine #21169`_.

        .. _Redmine #21169: http://projects.theforeman.org/issues/21169
        """
        payload = super(OSDefaultTemplate, self).update_payload(fields)
        return {'os_default_template': payload}


class OverrideValue(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Override Value entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'match': entity_fields.StringField(required=True),
            'value': entity_fields.StringField(required=True),
            'smart_class_parameter': entity_fields.OneToOneField(
                SmartClassParameters),
            'smart_variable': entity_fields.OneToOneField(SmartVariable),
            'use_puppet_default': entity_fields.BooleanField(),
            'omit': entity_fields.BooleanField(),
        }
        super(OverrideValue, self).__init__(server_config, **kwargs)
        # Create an override value for a specific smart class parameter
        if hasattr(self, 'smart_class_parameter'):
            # pylint:disable=no-member
            partial_path = self.smart_class_parameter.path('self')
        # Create an override value for a specific smart_variable
        elif hasattr(self, 'smart_variable'):
            # pylint:disable=no-member
            partial_path = self.smart_variable.path('self')
        else:
            raise TypeError(
                'A value must be provided for one of the following fields: '
                '"smart_class_parameter", "smart_variable"'
            )
        self._meta = {
            'api_path': '{0}/override_values'.format(partial_path),
            'server_modes': ('sat'),
        }

    def create_payload(self):
        """Remove ``smart_class_parameter_id`` or ``smart_variable_id``"""
        payload = super(OverrideValue, self).create_payload()
        if hasattr(self, 'smart_class_parameter'):
            del payload['smart_class_parameter_id']
        if hasattr(self, 'smart_variable'):
            del payload['smart_variable_id']
        return payload

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`OverrideValue` requires that an
        ``smart_class_parameter`` or ``smart_varaiable`` be provided, so this
        technique will not work. Do this instead::

            entity = type(self)(
                smart_class_parameter=self.smart_class_parameter)
            entity = type(self)(smart_variable=self.smart_variable)

        """
        # read() should not change the state of the object it's called on, but
        # super() alters the attributes of any entity passed in. Creating a new
        # object and passing it to super() lets this one avoid changing state.
        if entity is None:
            if hasattr(self, 'smart_class_parameter'):
                entity = type(self)(
                    self._server_config,
                    # pylint:disable=no-member
                    smart_class_parameter=self.smart_class_parameter,
                )
            elif hasattr(self, 'smart_variable'):
                entity = type(self)(
                    self._server_config,
                    # pylint:disable=no-member
                    smart_variable=self.smart_variable,
                )
        if ignore is None:
            ignore = set()
        ignore.update(['smart_class_parameter', 'smart_variable'])
        return super(OverrideValue, self).read(entity, attrs, ignore, params)


class Parameter(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Parameter entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
            'priority': entity_fields.IntegerField(),
            'value': entity_fields.StringField(required=True),
        }
        self._path_fields = {
            'domain': entity_fields.OneToOneField(Domain),
            'host': entity_fields.OneToOneField(Host),
            'hostgroup': entity_fields.OneToOneField(HostGroup),
            'location': entity_fields.OneToOneField(Location),
            'operatingsystem': entity_fields.OneToOneField(OperatingSystem),
            'organization': entity_fields.OneToOneField(Organization),
            'subnet': entity_fields.OneToOneField(Subnet),
        }
        self._fields.update(self._path_fields)
        super(Parameter, self).__init__(server_config, **kwargs)
        if not any(
                getattr(self, attr, None) for attr in self._path_fields):
            raise TypeError(
                'A value must be provided for any of "{0}" fields.'.format(
                    self._path_fields.keys())
            )
        self._parent_type = next(
            attr for attr in self._path_fields if getattr(self, attr, None))
        self._parent_id = getattr(self, self._parent_type).id
        self._meta = {
            'api_path': 'api/v2/{}s/{}/parameters'.format(
                self._parent_type, self._parent_id),
            'server_modes': ('sat'),
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Ignore path related fields as they're never returned by the server
        and are only added to entity to be able to use proper path.
        """
        if entity is None:
            entity = type(self)(
                self._server_config,
                **{self._parent_type: self._parent_id}
            )
        if ignore is None:
            ignore = set()
        for field_name in self._path_fields:
            ignore.add(field_name)
        return super(Parameter, self).read(entity, attrs, ignore, params)


class Permission(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Permission entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'resource_type': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': 'api/v2/permissions',
            'server_modes': ('sat', 'sam'),
        }
        super(Permission, self).__init__(server_config, **kwargs)


class Ping(Entity, EntitySearchMixin):
    """A representation of a Ping entity."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {
            'api_path': 'katello/api/v2/ping',
            'server_modes': ('sat', 'sam'),
        }
        super(Ping, self).__init__(server_config, **kwargs)


class Product(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Product entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'description': entity_fields.StringField(),
            'gpg_key': entity_fields.OneToOneField(ContentCredential),
            'label': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True
            ),
            'repository': entity_fields.OneToManyField(Repository),
            'sync_plan': entity_fields.OneToOneField(SyncPlan),
        }
        self._meta = {
            'api_path': 'katello/api/v2/products',
            'server_modes': ('sat', 'sam'),
        }
        super(Product, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        sync
            /products/<product_id>/sync

        ``super`` is called otherwise.

        """
        if which == 'sync':
            return '{0}/{1}'.format(
                super(Product, self).path(which='self'),
                which,
            )
        return super(Product, self).path(which)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Fetch an attribute missing from the server's response.

        Also add sync plan to the responce if needed, as
        :meth:`nailgun.entity_mixins.EntityReadMixin.read` can't initialize
        sync plan.

        For more information, see `Bugzilla #1237283
        <https://bugzilla.redhat.com/show_bug.cgi?id=1237283>`_ and
        `nailgun#261 <https://github.com/SatelliteQE/nailgun/issues/261>`_.

        """
        if attrs is None:
            attrs = self.read_json()
        if _get_version(self._server_config) < Version('6.1'):
            org = _get_org(self._server_config, attrs['organization']['label'])
            attrs['organization'] = org.get_values()
        if ignore is None:
            ignore = set()
        ignore.add('sync_plan')
        result = super(Product, self).read(entity, attrs, ignore, params)
        if 'sync_plan' in attrs:
            sync_plan_id = attrs.get('sync_plan_id')
            if sync_plan_id is None:
                result.sync_plan = None
            else:
                result.sync_plan = SyncPlan(
                    server_config=self._server_config,
                    id=sync_plan_id,
                    organization=result.organization,
                )
        return result

    def search(self, fields=None, query=None, filters=None):
        """Search for entities with missing attribute

        :param fields: A set naming which fields should be used when generating
            a search query. If ``None``, all values on the entity are used. If
            an empty set, no values are used.
        :param query: A dict containing a raw search query. This is melded in
            to the generated search query like so:  ``{generated:
            query}.update({manual: query})``.
        :param filters: A dict. Used to filter search results locally.
        :return: A list of entities, all of type ``type(self)``.

        For more information, see `Bugzilla #1237283
        <https://bugzilla.redhat.com/show_bug.cgi?id=1237283>`_ and
        `nailgun#261 <https://github.com/SatelliteQE/nailgun/issues/261>`_.
        """
        results = self.search_json(fields, query)['results']
        results = self.search_normalize(results)
        entities = []
        for result in results:
            sync_plan = result.get('sync_plan')
            if sync_plan is not None:
                del result['sync_plan']
            entity = type(self)(self._server_config, **result)
            if sync_plan:
                entity.sync_plan = SyncPlan(
                    server_config=self._server_config,
                    id=sync_plan,
                    organization=Organization(
                        server_config=self._server_config,
                        id=result.get('organization')
                    ),
                )
            entities.append(entity)
        if filters is not None:
            entities = self.search_filter(entities, filters)
        return entities

    def sync(self, synchronous=True, **kwargs):
        """Synchronize :class:`repositories <Repository>` in this product.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class PartitionTable(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Partition Table entity.

    Currently a Partition Table with one character in name cannot be created.
    For more information, see `Bugzilla #1229384
    <https://bugzilla.redhat.com/show_bug.cgi?id=1229384>`_.

    Note: Having a name length of 2 had failures again.  Updating the length to
    4.

    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'layout': entity_fields.StringField(required=True),
            'location': entity_fields.OneToManyField(Location),
            'locked': entity_fields.BooleanField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(4, 30),
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'os_family': entity_fields.StringField(choices=_OPERATING_SYSTEMS),
        }
        self._meta = {'api_path': 'api/v2/ptables', 'server_modes': ('sat')}
        super(PartitionTable, self).__init__(server_config, **kwargs)
        # The following fields were added in Satellite 6.2, removing them if we
        # have previous version of Satellite
        if _get_version(self._server_config) < Version('6.2'):
            # pragma: no cover
            self._fields.pop('location')
            self._fields.pop('organization')


class PuppetClass(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin):
    """A representation of a Puppet Class entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'hostgroup': entity_fields.OneToManyField(HostGroup),
        }
        self._meta = {
            'api_path': 'api/v2/puppetclasses',
            'server_modes': ('sat'),
        }
        super(PuppetClass, self).__init__(server_config, **kwargs)

    def search_normalize(self, results):
        """Flattens results.
        :meth:`nailgun.entity_mixins.EntitySearchMixin.search_normalize`
        expects structure like
        list(dict_1(name: class_1), dict_2(name: class_2)),
        while Puppet Class entity returns dictionary with lists of subclasses
        split by main puppet class.
        """
        flattened_results = []
        for key in results.keys():
            for item in results[key]:
                flattened_results.append(item)
        return super(PuppetClass, self).search_normalize(flattened_results)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.
        The format of the returned path depends on the value of ``which``:

        smart_class_parameters
            /api/puppetclasses/:puppetclass_id/smart_class_parameters

        Otherwise, call ``super``.

        """
        if which in ('smart_class_parameters', 'smart_variables'):
            return '{0}/{1}'.format(
                super(PuppetClass, self).path(which='self'),
                which
            )
        return super(PuppetClass, self).path(which)

    def list_scparams(self, synchronous=True, **kwargs):
        """List of smart class parameters for a specific Puppet class

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('smart_class_parameters'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def list_smart_variables(self, synchronous=True, **kwargs):
        """List all smart variables

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('smart_variables'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class PackageGroup(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Package Group entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(unique=True),
            'description': entity_fields.StringField(),
            'repository': entity_fields.OneToOneField(Repository),
            'uuid': entity_fields.StringField(),
        }
        self._meta = {'api_path': 'katello/api/v2/package_groups'}
        super(PackageGroup, self).__init__(server_config, **kwargs)


class Package(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Package entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'arch': entity_fields.StringField(),
            'checksum': entity_fields.StringField(),
            'description': entity_fields.StringField(),
            'epoch': entity_fields.StringField(),
            'filename': entity_fields.StringField(),
            'name': entity_fields.StringField(unique=True),
            'nvrea': entity_fields.StringField(),
            'nvra': entity_fields.StringField(),
            'release': entity_fields.StringField(),
            'repository': entity_fields.OneToOneField(Repository),
            'sourcerpm': entity_fields.StringField(),
            'summary': entity_fields.StringField(),
            'version': entity_fields.StringField(),
        }
        self._meta = {'api_path': 'katello/api/v2/packages'}
        super(Package, self).__init__(server_config, **kwargs)


class ModuleStream(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Module Stream entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'uuid': entity_fields.StringField(),
            'name': entity_fields.StringField(),
            'description': entity_fields.StringField(),
            'context': entity_fields.StringField(),
            'arch': entity_fields.StringField(),
            'stream': entity_fields.StringField(),
            'summary': entity_fields.StringField(),
            'version': entity_fields.StringField(),
            'module_spec': entity_fields.StringField(),
        }
        self._meta = {'api_path': 'katello/api/v2/module_stream'}
        super(ModuleStream, self).__init__(server_config, **kwargs)


class PuppetModule(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Puppet Module entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'author': entity_fields.StringField(),
            'checksums': entity_fields.ListField(),
            'dependencies': entity_fields.ListField(),
            'description': entity_fields.StringField(),
            'license': entity_fields.StringField(),
            'name': entity_fields.StringField(
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'project_page': entity_fields.URLField(),
            'repository': entity_fields.OneToManyField(Repository),
            'source': entity_fields.URLField(),
            'summary': entity_fields.StringField(),
            'version': entity_fields.StringField(),
        }
        self._meta = {'api_path': 'katello/api/v2/puppet_modules'}
        super(PuppetModule, self).__init__(server_config, **kwargs)


class CompliancePolicies(Entity, EntityReadMixin):
    """A representation of a Policy entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(4, 30),
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'hosts': entity_fields.OneToManyField(Host)
        }
        self._meta = {
            'api_path': 'api/v2/compliance/policies',
            'server_modes': ('sat')
        }
        super(CompliancePolicies, self).__init__(server_config, **kwargs)


class Realm(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Realm entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'realm_proxy': entity_fields.OneToOneField(
                SmartProxy,
                required=True,
            ),
            'realm_type': entity_fields.StringField(
                choices=('Red Hat Identity Management', 'Active Directory'),
                required=True,
            ),
        }
        self._meta = {'api_path': 'api/v2/realms', 'server_modes': ('sat')}
        super(Realm, self).__init__(server_config, **kwargs)

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1232855
        <https://bugzilla.redhat.com/show_bug.cgi?id=1232855>`_.

        """
        return Realm(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()


class RecurringLogic(Entity, EntityReadMixin):
    """A representation of a Recurring logic entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'cron_line': entity_fields.StringField(),
            'end_time': entity_fields.DateTimeField(),
            'iteration': entity_fields.IntegerField(),
            'state': entity_fields.StringField(),
            'task': entity_fields.OneToManyField(ForemanTask),
            'task_group_id': entity_fields.IntegerField(),

        }
        self._meta = {
            'api_path': 'foreman_tasks/api/recurring_logics',
            'server_modes': ('sat')}
        super(RecurringLogic, self).__init__(server_config, **kwargs)

    def cancel(self, synchronous=True, **kwargs):
        """Helper for canceling a recurring logic

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('cancel'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.RecurringLogic.path``.
        The format of the returned path depends on the value of ``which``:

        cancel
            /foreman_tasks/api/recurring_logics/:id/cancel

        Otherwise, call ``super``.

        """
        if which in ('cancel',):
            return '{0}/{1}'.format(
                super(RecurringLogic, self).path(which='self'),
                which
            )
        return super(RecurringLogic, self).path(which)


class Registry(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Registry entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'description': entity_fields.StringField(),
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'password': entity_fields.StringField(),
            'url': entity_fields.URLField(required=True),
            'username': entity_fields.StringField(),
        }
        self._meta = {
            'api_path': 'docker/api/v2/registries',
            'server_modes': ('sat'),
        }
        super(Registry, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {
            u'registry': super(Registry, self).create_payload()
        }

    def create(self, create_missing=None):
        """Manually fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1479391
        <https://bugzilla.redhat.com/show_bug.cgi?id=1479391>`_.
        """
        return Registry(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Do not read the ``password`` argument."""
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()
        ignore.add('password')
        return super(Registry, self).read(entity, attrs, ignore, params)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'registry': super(Registry, self).update_payload(fields)}

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1479391
        <https://bugzilla.redhat.com/show_bug.cgi?id=1479391>`_.
        """
        self.update_json(fields)
        return self.read()


class Report(Entity):
    """A representation of a Report entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'host': entity_fields.StringField(required=True),
            'logs': entity_fields.ListField(),
            'reported_at': entity_fields.DateTimeField(required=True),
        }
        self._meta = {'api_path': 'api/v2/reports', 'server_modes': ('sat')}
        super(Report, self).__init__(server_config, **kwargs)


class Repository(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Repository entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'backend_identifier': entity_fields.StringField(),
            'checksum_type': entity_fields.StringField(
                choices=('sha1', 'sha256'),
            ),
            'content_counts': entity_fields.DictField(),
            'content_type': entity_fields.StringField(
                choices=('puppet', 'yum', 'file', 'docker', 'ostree'),
                default='yum',
                required=True,
            ),
            'container_repository_name': entity_fields.StringField(),
            # Just setting `str_type='alpha'` will fail with this error:
            # {"docker_upstream_name":["must be a valid docker name"]}}
            'docker_upstream_name': entity_fields.StringField(
                default='busybox'
            ),
            'docker_tags_whitelist': entity_fields.ListField(),
            'download_policy': entity_fields.StringField(
                choices=('background', 'immediate', 'on_demand'),
                default='immediate',
            ),
            'full_path': entity_fields.StringField(),
            'gpg_key': entity_fields.OneToOneField(ContentCredential),
            'label': entity_fields.StringField(),
            'last_sync': entity_fields.OneToOneField(ForemanTask),
            'mirror_on_sync': entity_fields.BooleanField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToOneField(Organization),
            'product': entity_fields.OneToOneField(Product, required=True),
            'unprotected': entity_fields.BooleanField(),
            'url': entity_fields.URLField(
                default=_FAKE_YUM_REPO,
                required=True,
            ),
            'upstream_username': entity_fields.StringField(),
            'upstream_password': entity_fields.StringField(),
            'verify_ssl_on_sync': entity_fields.BooleanField(),
        }
        if _get_version(server_config) < Version('6.1'):
            # Adjust for Satellite 6.0
            del self._fields['docker_upstream_name']
            del self._fields['upstream_username']
            del self._fields['upstream_password']
            self._fields['content_type'].choices = (tuple(
                set(self._fields['content_type'].choices) - set(['docker'])
            ))
            del self._fields['checksum_type']
        if self._fields['content_type'].choices == 'yum':
            self._fields['download_policy'].required = True
        self._meta = {
            'api_path': 'katello/api/v2/repositories',
            'server_modes': ('sat'),
        }
        super(Repository, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        errata
            /repositories/<id>/errata
        files
            /repositories/<id>/files
        packages
            /repositories/<id>/packages
        module_streams
            /repositories/<id>/module_streams
        puppet_modules
            /repositories/<id>/puppet_modules
        remove_content
            /repositories/<id>/remove_content
        sync
            /repositories/<id>/sync
        upload_content
            /repositories/<id>/upload_content
        import_uploads
            /repositories/<id>/import_uploads

        ``super`` is called otherwise.

        """
        if which in (
                'errata',
                'files',
                'packages',
                'module_streams',
                'puppet_modules',
                'remove_content',
                'sync',
                'import_uploads',
                'upload_content'):
            return '{0}/{1}'.format(
                super(Repository, self).path(which='self'),
                which
            )
        return super(Repository, self).path(which)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Ignore ``organization`` field as it's never returned by the server
        and is only added to entity to be able to use organization path
        dependent helpers and also upstream_password as it is not returned
        for security reasons.
        """
        if ignore is None:
            ignore = set()
        ignore.add('organization')
        ignore.add('upstream_password')
        return super(Repository, self).read(entity, attrs, ignore, params)

    def create_missing(self):
        """Conditionally mark ``docker_upstream_name`` as required.

        Mark ``docker_upstream_name`` as required if ``content_type`` is
        "docker".

        """
        if getattr(self, 'content_type', '') == 'docker':
            self._fields['docker_upstream_name'].required = True
        super(Repository, self).create_missing()

    def errata(self, synchronous=True, **kwargs):
        """List errata inside repository.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('errata'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def sync(self, synchronous=True, **kwargs):
        """Helper for syncing an existing repository.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def upload_content(self, synchronous=True, **kwargs):
        """Upload a file or files to the current repository.

        Here is an example of how to upload content::

            with open('my_content.rpm') as content:
                repo.upload_content(files={'content': content})

        This method accepts the same keyword arguments as Requests. As a
        result, the following examples can be adapted for use here:

        * `POST a Multipart-Encoded File`_
        * `POST Multiple Multipart-Encoded Files`_

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        :raises nailgun.entities.APIResponseError: If the response has a status
            other than "success".

        .. _POST a Multipart-Encoded File:
            http://docs.python-requests.org/en/latest/user/quickstart/#post-a-multipart-encoded-file
        .. _POST Multiple Multipart-Encoded Files:
            http://docs.python-requests.org/en/latest/user/advanced/#post-multiple-multipart-encoded-files

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('upload_content'), **kwargs)
        json = _handle_response(response, self._server_config, synchronous)
        if json['status'] != 'success':
            raise APIResponseError(
                # pylint:disable=no-member
                'Received error when uploading file {0} to repository {1}: {2}'
                .format(kwargs.get('files'), self.id, json)
            )
        return json

    def import_uploads(self, uploads=None, upload_ids=None, synchronous=True,
                       **kwargs):
        """Import uploads into a repository

        It expects either a list of uploads or upload_ids (but not both).

        :param uploads: Array of uploads to be imported
        :param upload_ids: Array of upload ids to be imported
        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        if uploads:
            data = {'uploads': uploads}
        elif upload_ids:
            data = {'upload_ids': upload_ids}
        response = client.put(self.path('import_uploads'), data, **kwargs)
        json = _handle_response(response, self._server_config, synchronous)
        return json

    def remove_content(self, synchronous=True, **kwargs):
        """Remove content from a repository

        It expects packages/puppet modules/docker manifests ids sent as data.
        Here is an example of how to use this method::

            repository.remove_content(data={'ids': [package.id]})

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('remove_content'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def puppet_modules(self, synchronous=True, **kwargs):
        """"List puppet modules associated with repository

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('puppet_modules'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def packages(self, synchronous=True, **kwargs):
        """List packages associated with repository

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('packages'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def module_streams(self, synchronous=True, **kwargs):
        """List module_streams associated with repository

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('module_streams'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def files(self, synchronous=True, **kwargs):
        """List files associated with repository

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('files'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class RepositorySet(
        Entity,
        EntityReadMixin,
        EntitySearchMixin):
    """ A representation of a Repository Set entity"""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'contentUrl': entity_fields.URLField(required=True),
            'gpgUrl': entity_fields.URLField(required=True),
            'label': entity_fields.StringField(required=True),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'product': entity_fields.OneToOneField(Product, required=True),
            'repositories': entity_fields.OneToManyField(Repository),
            'type': entity_fields.StringField(
                choices=('kickstart', 'yum', 'file'),
                default='yum',
                required=True,
            ),
            'vendor': entity_fields.StringField(required=True),
        }
        super(RepositorySet, self).__init__(server_config, **kwargs)
        self._meta = {
            'api_path': 'katello/api/v2/repository_sets',
        }

    def available_repositories(self, **kwargs):
        """Lists available repositories for the repository set

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        if 'data' not in kwargs:
            kwargs['data'] = dict()
            kwargs['data']['product_id'] = self.product.id
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('available_repositories'), **kwargs)
        return _handle_response(response, self._server_config)

    def enable(self, synchronous=True, **kwargs):
        """Enables the RedHat Repository

        RedHat Repos needs to be enabled first, so that we can sync it.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        if 'data' not in kwargs:
            kwargs['data'] = dict()
            kwargs['data']['product_id'] = self.product.id
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('enable'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def disable(self, synchronous=True, **kwargs):
        """Disables the RedHat Repository

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        if 'data' not in kwargs:
            kwargs['data'] = dict()
            kwargs['data']['product_id'] = self.product.id
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('disable'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        available_repositories
            /repository_sets/<id>/available_repositories
        enable
            /repository_sets/<id>/enable
        disable
            /repository_sets/<id>/disable

        ``super`` is called otherwise.

        """
        if which in (
                'available_repositories',
                'enable',
                'disable',
        ):
            return '{0}/{1}'.format(
                super(RepositorySet, self).path(which='self'),
                which
            )
        return super(RepositorySet, self).path(which)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read`` provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`RepositorySet` requires that a ``product`` be
        provided, so this technique will not work. Do this instead::

            entity = type(self)(product=self.product.id)

        """
        # read() should not change the state of the object it's called on, but
        # super() alters the attributes of any entity passed in. Creating a new
        # object and passing it to super() lets this one avoid changing state.
        if entity is None:
            entity = type(self)(
                self._server_config,
                product=self.product,  # pylint:disable=no-member
            )
        if ignore is None:
            ignore = set()
        return super(RepositorySet, self).read(entity, attrs, ignore, params)


class RHCIDeployment(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a RHCI deployment entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'deploy_rhev': entity_fields.BooleanField(required=True),
            'lifecycle_environment': entity_fields.OneToOneField(
                LifecycleEnvironment,
                required=True
            ),
            'name': entity_fields.StringField(required=True, unique=True),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'rhev_engine_admin_password': entity_fields.StringField(),
            'rhev_engine_host': entity_fields.OneToOneField(
                Host,
                required=True,
            ),
            'rhev_storage_type': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': 'fusor/api/v21/deployments',
            'server_modes': ('sat'),
        }
        super(RHCIDeployment, self).__init__(server_config, **kwargs)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Normalize the data returned by the server.

        The server's JSON response is in this form::

            {
                "organizations": […],
                "lifecycle_environments": […],
                "discovered_hosts": […],
                "deployment": {…},
            }

        The inner "deployment" dict contains information about this entity. The
        response does not contain a value for the ``rhev_engine_host``
        argument.

        """
        if attrs is None:
            attrs = self.read_json()
        attrs = attrs['deployment']
        if ignore is None:
            ignore = set()
        ignore.add('rhev_engine_host')
        return super(RHCIDeployment, self).read(entity, attrs, ignore, params)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        deploy
            /deployments/<id>/deploy

        ``super`` is called otherwise.

        """
        if which == 'deploy':
            return '{0}/{1}'.format(
                super(RHCIDeployment, self).path(which='self'),
                which
            )
        return super(RHCIDeployment, self).path(which)

    def deploy(self, synchronous=True, **kwargs):
        """Kickoff the RHCI deployment.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('deploy'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class RoleLDAPGroups(Entity):
    """A representation of a Role LDAP Groups entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
        }
        self._meta = {
            'api_path': 'katello/api/v2/roles/:role_id/ldap_groups',
            'server_modes': ('sat', 'sam'),
        }
        super(RoleLDAPGroups, self).__init__(server_config, **kwargs)


class Role(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Role entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'filters': entity_fields.OneToManyField(Filter),
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True,
                str_type='alphanumeric',
                length=(2, 30),  # min length is 2 and max length is arbitrary
                unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
        }
        self._meta = {
            'api_path': 'api/v2/roles',
            'server_modes': ('sat', 'sam'),
        }
        super(Role, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'role': super(Role, self).create_payload()}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'role': super(Role, self).update_payload(fields)}

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.
        The format of the returned path depends on the value of ``which``:

        clone
            /api/roles/:role_id/clone

        Otherwise, call ``super``.

        """
        if which == 'clone':
            return '{0}/{1}'.format(
                super(Role, self).path(which='self'),
                which
            )
        return super(Role, self).path(which)

    def clone(self, synchronous=True, **kwargs):
        """Helper to clone an existing Role

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('clone'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class Setting(Entity, EntityReadMixin, EntitySearchMixin, EntityUpdateMixin):
    """A representation of a Setting entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'created_at': entity_fields.DateTimeField(),
            'default': entity_fields.StringField(),
            'description': entity_fields.StringField(),
            'name': entity_fields.StringField(unique=True),
            'settings_type': entity_fields.StringField(),
            'updated_at': entity_fields.DateTimeField(),
            'value': entity_fields.StringField(),
        }
        self._meta = {
            'api_path': 'api/v2/settings',
            'server_modes': ('sat'),
        }
        super(Setting, self).__init__(server_config, **kwargs)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'setting': super(Setting, self).update_payload(fields)}


class SmartProxy(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Smart Proxy entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'download_policy': entity_fields.StringField(
                choices=('background', 'immediate', 'on_demand'),
                default='on_demand',
            ),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'url': entity_fields.URLField(required=True),
            'location': entity_fields.OneToManyField(Location),
            'organization': entity_fields.OneToManyField(Organization),
        }
        self._meta = {
            'api_path': 'api/v2/smart_proxies',
            'server_modes': ('sat'),
        }
        super(SmartProxy, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.
        The format of the returned path depends on the value of ``which``:

        refresh
            /api/smart_proxies/:id/refresh

        Otherwise, call ``super``.

        """
        if which in ('refresh',):
            return '{0}/{1}'.format(
                super(SmartProxy, self).path(which='self'),
                which
            )
        return super(SmartProxy, self).path(which)

    def refresh(self, synchronous=True, **kwargs):
        """Refresh Capsule features

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('refresh'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def import_puppetclasses(self, synchronous=True, **kwargs):
        """Import puppet classes from puppet Capsule.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        # Check if environment_id was sent and substitute it to the path
        # but do not pass it to requests
        if 'environment' in kwargs:
            if isinstance(kwargs['environment'], Environment):
                environment_id = kwargs.pop('environment').id
            else:
                environment_id = kwargs.pop('environment')
            path = '{0}/environments/{1}/import_puppetclasses'.format(
                self.path(), environment_id)
        else:
            path = '{0}/import_puppetclasses'.format(self.path())
        return _handle_response(
            client.post(path, **kwargs), self._server_config, synchronous)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Ignore ``download_policy`` field as it's never returned by the
        server.

        For more information, see `Bugzilla #1486609
        <https://bugzilla.redhat.com/show_bug.cgi?id=1486609>`_.
        """
        if ignore is None:
            ignore = set()
        ignore.add('download_policy')
        return super(SmartProxy, self).read(entity, attrs, ignore, params)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1262037
        <https://bugzilla.redhat.com/show_bug.cgi?id=1262037>`_.

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {
            u'smart_proxy': super(SmartProxy, self).update_payload(fields)
        }


class SmartClassParameters(
        Entity,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Smart Class Parameters."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'puppetclass': entity_fields.OneToOneField(PuppetClass),
            'override': entity_fields.BooleanField(),
            'description': entity_fields.StringField(),
            'default_value': entity_fields.StringField(),
            'hidden_value': entity_fields.BooleanField(),
            'hidden_value?': entity_fields.BooleanField(),
            'use_puppet_default': entity_fields.BooleanField(),
            'validator_type': entity_fields.StringField(
                choices=('regexp', 'list')
            ),
            'validator_rule': entity_fields.StringField(),
            'parameter': entity_fields.StringField(),
            'parameter_type': entity_fields.StringField(
                choices=('string', 'boolean', 'integer', 'real',
                         'array', 'hash', 'yaml', 'json')
            ),
            'required': entity_fields.BooleanField(),
            'merge_overrides': entity_fields.BooleanField(),
            'merge_default': entity_fields.BooleanField(),
            'avoid_duplicates': entity_fields.BooleanField(),
            'override_value_order': entity_fields.StringField(),
            'override_values': entity_fields.DictField()
        }
        self._meta = {
            'api_path': 'api/v2/smart_class_parameters',
            'server_modes': ('sat'),
        }
        super(SmartClassParameters, self).__init__(server_config, **kwargs)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Do not read the ``hidden_value`` attribute."""
        if ignore is None:
            ignore = set()
        ignore.add('hidden_value')
        return super(SmartClassParameters, self).read(
            entity, attrs, ignore, params)


class SmartVariable(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Smart Variable entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'default_value': entity_fields.StringField(),
            'description': entity_fields.StringField(),
            'puppetclass': entity_fields.OneToOneField(PuppetClass),
            'validator_rule': entity_fields.StringField(),
            'validator_type': entity_fields.StringField(),
            'variable': entity_fields.StringField(required=True),
            'variable_type': entity_fields.StringField(),
            'hidden_value': entity_fields.BooleanField(),
            'hidden_value?': entity_fields.BooleanField(),
            'merge_overrides': entity_fields.BooleanField(),
            'merge_default': entity_fields.BooleanField(),
            'avoid_duplicates': entity_fields.BooleanField(),
            'override_value_order': entity_fields.StringField(),
            'override_values': entity_fields.DictField(),
        }
        self._meta = {
            'api_path': 'api/v2/smart_variables',
            'server_modes': ('sat'),
        }
        super(SmartVariable, self).__init__(server_config, **kwargs)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Do not read the ``hidden_value`` attribute."""
        if ignore is None:
            ignore = set()
        ignore.add('hidden_value')
        return super(SmartVariable, self).read(entity, attrs, ignore, params)

    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {u'smart_variable': super(SmartVariable, self).create_payload()}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {
            u'smart_variable':
                super(SmartVariable, self).update_payload(fields)
        }


class Snapshot(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Snapshot entity.
       Foreman_snapshot as mentioned in the plugin:
       https://github.com/ATIX-AG/foreman_snapshot_management
       # Read Snapshot
       Snapshot(host=<host_id>, id=<snapshot_id>).read()
       # Search Snapshots
       Snapshot(host=<host_id>).search()
       # Create Snapshot
       Snapshot(host=<host_id>, name=<snapshot_name>).create()
       # Update Snapshot
       Snapshot(host=<host_id>, id=<snapshot_id>, description=<snapshot_description>).update()
       # Revert Snapshot
       Snapshot(host=<host_id>, id=<snapshot_id>).revert()
       # Delete Snapshot
       Snapshot(host=<host_id>, id=<snapshot_id>).delete()
    """

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('host', kwargs)
        self._fields = {
            'name': entity_fields.StringField(required=True),
            'description': entity_fields.StringField(required=False),
            'host': entity_fields.OneToOneField(
                Host,
                required=True,
            ),
        }
        super(Snapshot, self).__init__(server_config, **kwargs)
        self._meta = {
            'api_path': '{0}/snapshots'.format(
                self.host.path('self')),
            'server_modes': ('sat'),
        }

    def path(self, which=None):
        """Extend nailgun.entity_mixins.Entity.path.
        revert
        /api/v2/hosts/<host-id>/snapshots/<snapshot-id>/revert
        """
        if which == 'revert':
            return '{0}/{1}'.format(super(Snapshot, self).path(which='self'), which)
        return super(Snapshot, self).path(which)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read`` provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`Snapshot` requires that an
        ``host`` be provided, so this technique will not work. Do
        this instead::

            entity = type(self)(host=self.host)

        """
        # read() should not change the state of the object it's called on, but
        # super() alters the attributes of any entity passed in. Creating a new
        # object and passing it to super() lets this one avoid changing state.
        if entity is None:
            entity = type(self)(
                self._server_config,
                host=self.host,  # pylint:disable=E1101
            )
        if ignore is None:
            ignore = set()
        ignore.add('host')
        return super(Snapshot, self).read(entity, attrs, ignore, params)

    def search_normalize(self, results):
        """Append host id to search results to be able to initialize found
        :class:`Snapshot` successfully
        """

        for snapshot in results:
            snapshot[u'host_id'] = self.host.id  # pylint:disable=no-member
        return super(Snapshot, self).search_normalize(results)

    def revert(self, **kwargs):
        """ Rollbacks the Snapshot

        Makes HTTP PUT call to revert the snapshot.
        """

        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('revert'), **kwargs)
        return _handle_response(response, self._server_config)


class SSHKey(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin):
    """A representation of a SSH Key entity.

    ``user`` must be passed in when this entity is instantiated.

    :raises: ``TypeError`` if ``user`` is not passed in.

    """

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('user', kwargs)
        self._fields = {
            'user': entity_fields.OneToOneField(
                User,
                required=True,
            ),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'key': entity_fields.StringField(
                required=True,
                str_type='alphanumeric',
                unique=True
            )
        }
        super(SSHKey, self).__init__(server_config, **kwargs)
        self._meta = {
            # pylint:disable=no-member
            'api_path': '{0}/ssh_keys'.format(self.user.path()),
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read`` provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`SSHKey` requires that an ``user`` be
        provided, so this technique will not work. Do this instead::

            entity = type(self)(user=self.user.id)

        """
        # read() should not change the state of the object it's called on, but
        # super() alters the attributes of any entity passed in. Creating a new
        # object and passing it to super() lets this one avoid changing state.
        if entity is None:
            entity = type(self)(
                self._server_config,
                user=self.user,  # pylint:disable=no-member
            )
        if ignore is None:
            ignore = set()
        ignore.add('user')
        return super(SSHKey, self).read(entity, attrs, ignore, params)

    def search_normalize(self, results):
        """Append user id to search results to be able to initialize found
        :class:`User` successfully
        """
        for sshkey in results:
            sshkey[u'user_id'] = self.user.id  # pylint:disable=no-member
        return super(SSHKey, self).search_normalize(results)


class Status(Entity):
    """A representation of a Status entity."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {
            'api_path': 'katello/api/v2/status',
            'server_modes': ('sat'),
        }
        super(Status, self).__init__(server_config, **kwargs)


class Subnet(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Subnet entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'boot_mode': entity_fields.StringField(
                choices=('Static', 'DHCP',),
                default=u'DHCP',
            ),
            'cidr': entity_fields.IntegerField(),
            'dhcp': entity_fields.OneToOneField(SmartProxy),
            # When reading a subnet, no discovery information is
            # returned by the server. See Bugzilla #1217146.
            'discovery': entity_fields.OneToOneField(SmartProxy),
            'dns': entity_fields.OneToOneField(SmartProxy),
            'dns_primary': entity_fields.IPAddressField(),
            'dns_secondary': entity_fields.IPAddressField(),
            'domain': entity_fields.OneToManyField(Domain),
            'from_': entity_fields.IPAddressField(),
            'gateway': entity_fields.StringField(),
            'ipam': entity_fields.StringField(
                choices=(u'DHCP', u'Internal DB'),
                default=u'DHCP',
            ),
            'location': entity_fields.OneToManyField(Location),
            'mask': entity_fields.NetmaskField(required=True),
            'mtu': entity_fields.IntegerField(min_val=68, max_val=4294967295),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'network': entity_fields.IPAddressField(required=True),
            'network_type': entity_fields.StringField(
                choices=('IPv4', 'IPv6'),
                default='IPv4',
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'remote_execution_proxy':
                entity_fields.OneToManyField(SmartProxy),
            'subnet_parameters_attributes': entity_fields.ListField(),
            'template': entity_fields.OneToOneField(SmartProxy),
            'to': entity_fields.IPAddressField(),
            'tftp': entity_fields.OneToOneField(SmartProxy),
            'vlanid': entity_fields.StringField(),
        }
        self._meta = {'api_path': 'api/v2/subnets', 'server_modes': ('sat')}
        super(Subnet, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        In addition, rename the ``from_`` field to ``from``.

        """
        payload = super(Subnet, self).create_payload()
        if 'from_' in payload:
            payload['from'] = payload.pop('from_')
        return {u'subnet': payload}

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Fetch as many attributes as possible for this entity.

        Do not read the ``discovery`` attribute. For more information, see
        `Bugzilla #1217146
        <https://bugzilla.redhat.com/show_bug.cgi?id=1217146>`_.

        In addition, rename the ``from_`` field to ``from``.

        """
        if attrs is None:
            attrs = self.read_json()
        attrs['from_'] = attrs.pop('from')

        if ignore is None:
            ignore = set()
        if attrs is not None and 'parameters' in attrs:
            attrs['subnet_parameters_attributes'] = attrs.pop('parameters')
        else:
            ignore.add('subnet_parameters_attributes')
        ignore.add('discovery')
        ignore.add('remote_execution_proxy')
        return super(Subnet, self).read(entity, attrs, ignore, params)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super(Subnet, self).update_payload(fields)
        if 'from_' in payload:
            payload['from'] = payload.pop('from_')
        return {u'subnet': payload}


class Subscription(
        Entity,
        EntityReadMixin,
        EntitySearchMixin):
    """A representation of a Subscription entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'activation_key': entity_fields.OneToManyField(ActivationKey),
            'cp_id': entity_fields.StringField(unique=True),
            'name': entity_fields.StringField(),
            'organization': entity_fields.OneToOneField(Organization),
            'provided_product': entity_fields.OneToManyField(Product),
            'quantity': entity_fields.IntegerField(),
            'subscription': entity_fields.OneToOneField(Subscription),
        }
        self._meta = {
            'api_path': 'katello/api/v2/subscriptions',
            'server_modes': ('sat', 'sam'),
        }
        super(Subscription, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        delete_manifest
            /katello/api/v2/organizations/:organization_id/subscriptions/delete_manifest
        manifest_history
            /katello/api/v2/organizations/:organization_id/subscriptions/manifest_history
        refresh_manifest
            /katello/api/v2/organizations/:organization_id/subscriptions/refresh_manifest
        upload
            /katello/api/v2/organizations/:organization_id/subscriptions/upload

        """
        if which in (
                'delete_manifest',
                'manifest_history',
                'refresh_manifest',
                'upload'):
            _check_for_value('organization', self.get_values())
            # pylint:disable=no-member
            return self.organization.path('subscriptions/{0}'.format(which))
        return super(Subscription, self).path(which)

    def _org_path(self, which, payload):
        """A helper method for generating paths with organization IDs in them.

        :param which: A path such as "manifest_history" that has an
            organization ID in it.
        :param payload: A dict with an "organization_id" key in it.
        :returns: A string. The requested path.

        """
        return Subscription(
            self._server_config,
            organization=payload['organization_id'],
        ).path(which)

    def delete_manifest(self, synchronous=True, **kwargs):
        """Delete manifest from Red Hat provider.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(
            self._org_path('delete_manifest', kwargs['data']),
            **kwargs
        )
        return _handle_response(
            response,
            self._server_config,
            synchronous,
            timeout=1500,
        )

    def manifest_history(self, synchronous=True, **kwargs):
        """Obtain manifest history for subscriptions.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(
            self._org_path('manifest_history', kwargs['data']),
            **kwargs
        )
        return _handle_response(response, self._server_config, synchronous)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Ignore ``organization`` field as it's never returned by the server
        and is only added to entity to be able to use organization path
        dependent helpers.
        """
        if ignore is None:
            ignore = set()
        ignore.add('organization')
        return super(Subscription, self).read(entity, attrs, ignore, params)

    def refresh_manifest(self, synchronous=True, **kwargs):
        """Refresh previously imported manifest for Red Hat provider.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(
            self._org_path('refresh_manifest', kwargs['data']),
            **kwargs
        )
        return _handle_response(
            response,
            self._server_config,
            synchronous,
            timeout=1500,
        )

    def upload(self, synchronous=True, **kwargs):
        """Upload a subscription manifest.

        Here is an example of how to use this method::

            with open('my_manifest.zip') as manifest:
                sub.upload({'organization_id': org.id}, manifest)

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(
            self._org_path('upload', kwargs['data']),
            **kwargs
        )
        # Setting custom timeout as manifest upload can take enormously huge
        # amount of time. See BZ#1339696 for more details
        return _handle_response(
            response,
            self._server_config,
            synchronous,
            timeout=1500,
        )


class SyncPlan(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Sync Plan entity.

    ``organization`` must be passed in when this entity is instantiated.

    :raises: ``TypeError`` if ``organization`` is not passed in.

    """

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('organization', kwargs)
        self._fields = {
            'description': entity_fields.StringField(),
            'enabled': entity_fields.BooleanField(required=True),
            'interval': entity_fields.StringField(
                choices=('hourly', 'daily', 'weekly', 'custom cron'),
                default=gen_choice(('hourly', 'daily', 'weekly')),
                required=True,
            ),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'cron_expression': entity_fields.StringField(
                str_type='alpha'
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'product': entity_fields.OneToManyField(Product),
            'sync_date': entity_fields.DateTimeField(required=True),
            'foreman_tasks_recurring_logic': entity_fields.OneToOneField(RecurringLogic)
        }
        super(SyncPlan, self).__init__(server_config, **kwargs)
        self._meta = {
            # pylint:disable=no-member
            'api_path': '{0}/sync_plans'.format(self.organization.path()),
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read`` provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`SyncPlan` requires that an ``organization`` be
        provided, so this technique will not work. Do this instead::

            entity = type(self)(organization=self.organization.id)

        """
        # read() should not change the state of the object it's called on, but
        # super() alters the attributes of any entity passed in. Creating a new
        # object and passing it to super() lets this one avoid changing state.
        if entity is None:
            entity = type(self)(
                self._server_config,
                organization=self.organization,  # pylint:disable=no-member
            )
        if ignore is None:
            ignore = set()
        ignore.add('organization')
        return super(SyncPlan, self).read(entity, attrs, ignore, params)

    def create_payload(self):
        """Convert ``sync_date`` to a string.

        The ``sync_date`` instance attribute on the current object is not
        affected. However, the ``'sync_date'`` key in the dict returned by
        ``create_payload`` is a string.

        """
        data = super(SyncPlan, self).create_payload()
        if isinstance(data.get('sync_date'), datetime):
            data['sync_date'] = data['sync_date'].strftime('%Y-%m-%d %H:%M:%S')
        return data

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        add_products
            /katello/api/v2/organizations/:organization_id/sync_plans/:sync_plan_id/add_products
        remove_products
            /katello/api/v2/organizations/:organization_id/sync_plans/:sync_plan_id/remove_products

        """
        if which in ('add_products', 'remove_products'):
            return '{0}/{1}'.format(
                super(SyncPlan, self).path(which='self'),
                which
            )
        return super(SyncPlan, self).path(which)

    def add_products(self, synchronous=True, **kwargs):
        """Add products to this sync plan.

        .. NOTE:: The ``synchronous`` argument has no effect in certain
            versions of Satellite. See `Bugzilla #1199150
            <https://bugzilla.redhat.com/show_bug.cgi?id=1199150>`_.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('add_products'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def remove_products(self, synchronous=True, **kwargs):
        """Remove products from this sync plan.

        .. NOTE:: The ``synchronous`` argument has no effect in certain
            versions of Satellite. See `Bugzilla #1199150
            <https://bugzilla.redhat.com/show_bug.cgi?id=1199150>`_.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('remove_products'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def update_payload(self, fields=None):
        """Convert ``sync_date`` to a string if datetime object provided."""
        data = super(SyncPlan, self).update_payload(fields)
        if isinstance(data.get('sync_date'), datetime):
            data['sync_date'] = data['sync_date'].strftime('%Y-%m-%d %H:%M:%S')
        return data


class SystemPackage(Entity):
    """A representation of a System Package entity."""

    def __init__(self, server_config=None, **kwargs):
        if _get_version(server_config) >= Version('6.2'):
            raise DeprecationWarning(
                'SystemPackage entity was removed in Satellite 6.2. Please, '
                'use HostPackage entity instead.'
            )
        self._fields = {
            'groups': entity_fields.ListField(),
            'packages': entity_fields.ListField(),
            'system': entity_fields.OneToOneField(System, required=True),
        }
        self._meta = {
            'api_path': 'katello/api/v2/systems/:system_id/packages',
            'server_modes': ('sat'),
        }
        super(SystemPackage, self).__init__(server_config, **kwargs)


class System(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin):
    """A representation of a System entity."""

    def __init__(self, server_config=None, **kwargs):
        if _get_version(server_config) >= Version('6.2'):
            raise DeprecationWarning(
                'System entity was removed in Satellite 6.2. Please, use Host '
                'entity instead.'
            )
        self._fields = {
            'content_view': entity_fields.OneToOneField(ContentView),
            'description': entity_fields.StringField(),
            'environment': entity_fields.OneToOneField(LifecycleEnvironment),
            'facts': entity_fields.DictField(
                default={u'uname.machine': u'unknown'},
                required=True,
            ),
            'host_collection': entity_fields.OneToManyField(HostCollection),
            'installed_products': entity_fields.ListField(),
            'last_checkin': entity_fields.DateTimeField(),
            'location': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'release_ver': entity_fields.StringField(),
            'service_level': entity_fields.StringField(),
            'uuid': entity_fields.StringField(),

            # The type() builtin is still available within instance methods,
            # class methods, static methods, inner classes, and so on. However,
            # type() is *not* available at the current level of lexical scoping
            # after this point.
            'type': entity_fields.StringField(default='system', required=True),
        }
        self._meta = {
            'api_path': 'katello/api/v2/systems',
            'server_modes': ('sat', 'sam'),
        }
        super(System, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        This method contains a workaround for `Bugzilla #1202917`_.

        Most entities are uniquely identified by an ID. ``System`` is a bit
        different: it has both an ID and a UUID, and the UUID is used to
        uniquely identify a ``System``.

        Return a path in the format ``katello/api/v2/systems/<uuid>`` if a UUID
        is available and:

        * ``which is None``, or
        * ``which == 'this'``.

        .. _Bugzilla #1202917:
            https://bugzilla.redhat.com/show_bug.cgi?id=1202917

        Finally, return a path in the form
        ``katello/api/v2/systems/<uuid>/subscriptions`` if ``'subscriptions'``
        is passed in.

        """
        if which == 'subscriptions':
            return '{0}/{1}/{2}'.format(
                super(System, self).path('base'),
                self.uuid,  # pylint:disable=no-member
                which,
            )
        if hasattr(self, 'uuid') and (which is None or which == 'self'):
            return '{0}/{1}'.format(
                super(System, self).path('base'),
                self.uuid  # pylint:disable=no-member
            )
        return super(System, self).path(which)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Fetch as many attributes as possible for this entity.

        Do not read the ``facts``, ``organization`` or ``type`` attributes.
        For more information, see `Bugzilla #1202917
        <https://bugzilla.redhat.com/show_bug.cgi?id=1202917>`_.

        """
        if attrs is None:
            attrs = self.read_json()
        attrs['last_checkin'] = attrs.pop('checkin_time')
        attrs['host_collections'] = attrs.pop('hostCollections')
        attrs['installed_products'] = attrs.pop('installedProducts')
        if ignore is None:
            ignore = set()
        ignore.update(['facts', 'organization', 'type'])
        return super(System, self).read(entity, attrs, ignore, params)


class Template(Entity):
    """A representation of a Template entity."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {
            'api_path': 'api/v2/templates',
            'server_modes': ('sat'),
        }
        super(Template, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        import
            /templates/import
        export
            /templates/export

        """
        if which:
            return '{0}/{1}'.format(
                super(Template, self).path(which='base'), which)
        return super(Template, self).path(which)

    def imports(self, synchronous=True, **kwargs):
        """Helper to import templates

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('import'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def exports(self, synchronous=True, **kwargs):
        """Helper to export templates

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('export'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)


class TemplateCombination(Entity, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Template Combination entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'config_template': entity_fields.OneToOneField(ConfigTemplate),
            'environment': entity_fields.OneToOneField(Environment),
            'hostgroup': entity_fields.OneToOneField(HostGroup),
            'provisioning_template': entity_fields.OneToOneField(
                ProvisioningTemplate,
                required=True,
            ),
        }
        self._meta = {
            'api_path': 'api/v2/template_combinations',
            'server_modes': 'sat',
        }
        super(TemplateCombination, self).__init__(server_config, **kwargs)


class TemplateKind(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Template Kind entity.

    Unusually, the ``/api/v2/template_kinds/:id`` path is totally unsupported.

    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(unique=True),
        }
        self._meta = {
            'api_path': 'api/v2/template_kinds',
            'num_created_by_default': 8,
            'server_modes': ('sat'),
        }
        super(TemplateKind, self).__init__(server_config, **kwargs)


class UserGroup(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a User Group entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'admin': entity_fields.BooleanField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
                unique=True
            ),
            'role': entity_fields.OneToManyField(Role),
            'user': entity_fields.OneToManyField(User),
            'usergroup': entity_fields.OneToManyField(UserGroup),
        }
        self._meta = {'api_path': 'api/v2/usergroups', 'server_modes': ('sat')}
        super(UserGroup, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'usergroup': super(UserGroup, self).create_payload()}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'usergroup': super(UserGroup, self).update_payload(fields)}

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1301658
        <https://bugzilla.redhat.com/show_bug.cgi?id=1301658>`_.

        """
        return UserGroup(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Work around `Redmine #9594`_.

        An HTTP GET request to ``path('self')`` does not return the ``admin``
        attribute, even though it should. Also see `Bugzilla #1197871`_.

        .. _Redmine #9594: http://projects.theforeman.org/issues/9594
        .. _Bugzilla #1197871:
            https://bugzilla.redhat.com/show_bug.cgi?id=1197871

        """
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()
        if 'admin' not in attrs and 'admin' not in ignore:
            response = client.put(
                self.path('self'),
                {},
                **self._server_config.get_client_kwargs()
            )
            response.raise_for_status()
            attrs['admin'] = response.json()['admin']
        return super(UserGroup, self).read(entity, attrs, ignore, params)


class User(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a User entity.

    The LDAP authentication source with an ID of 1 is internal. It is nearly
    guaranteed to exist and be functioning. Thus, ``auth_source`` is set to "1"
    by default for a practical reason: it is much easier to use internal
    authentication than to spawn LDAP authentication servers for each new user.

    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'admin': entity_fields.BooleanField(),
            'auth_source': entity_fields.OneToOneField(
                AuthSourceLDAP,
                default=AuthSourceLDAP(server_config, id=1),
                required=True,
            ),
            'default_location': entity_fields.OneToOneField(Location),
            'default_organization': entity_fields.OneToOneField(Organization),
            'description': entity_fields.StringField(),
            'firstname': entity_fields.StringField(length=(1, 50)),
            'lastname': entity_fields.StringField(length=(1, 50)),
            'location': entity_fields.OneToManyField(Location),
            'login': entity_fields.StringField(
                length=(6, 12),
                required=True,
                str_type='alpha',
            ),
            'mail': entity_fields.EmailField(required=True),
            'organization': entity_fields.OneToManyField(Organization),
            'password': entity_fields.StringField(required=True),
            'role': entity_fields.OneToManyField(Role),
        }
        self._meta = {
            'api_path': 'api/v2/users',
            'server_modes': ('sat', 'sam'),
        }
        super(User, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'user': super(User, self).create_payload()}

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Do not read the ``password`` argument."""
        if ignore is None:
            ignore = set()
        ignore.add('password')
        return super(User, self).read(entity, attrs, ignore, params)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'user': super(User, self).update_payload(fields)}

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1235012
        <https://bugzilla.redhat.com/show_bug.cgi?id=1235012>`_.

        """
        self.update_json(fields)
        return self.read()


class VirtWhoConfig(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a VirtWho Config entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'blacklist': entity_fields.StringField(),
            'debug': entity_fields.BooleanField(),
            'filtering_mode': entity_fields.IntegerField(
                choices=[0, 1, 2], default=0, required=True),
            'hypervisor_id': entity_fields.StringField(
                choices=['hostname', 'uuid', 'hwuuid'],
                default='hostname', required=True),
            'hypervisor_password': entity_fields.StringField(),
            'hypervisor_server': entity_fields.StringField(required=True),
            'hypervisor_type': entity_fields.StringField(
                choices=['esx', 'rhevm', 'hyperv', 'xen', 'libvirt', 'kubevirt'],
                default='libvirt', required=True),
            'hypervisor_username': entity_fields.StringField(required=True),
            'interval': entity_fields.IntegerField(
                choices=[60, 120, 240, 480, 720, 1440, 2880, 4320], default=120, required=True),
            'name': entity_fields.StringField(required=True),
            'no_proxy': entity_fields.StringField(),
            'proxy': entity_fields.StringField(),
            'satellite_url': entity_fields.StringField(required=True),
            'whitelist': entity_fields.StringField(),
            'organization_id': entity_fields.IntegerField(),
            'status': entity_fields.StringField()
        }
        self._meta = {
            'api_path': 'foreman_virt_who_configure/api/v2/configs',
            'server_modes': ('sat', 'sam'),
        }
        super(VirtWhoConfig, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        deploy_script
            /foreman_virt_who_configure/api/v2/configs/:id/deploy_script

        configs
            /foreman_virt_who_configure/api/v2/organizations/:organization_id/configs

        ``super`` is called otherwise.

        """
        if which and which in ('deploy_script'):
            return '{0}/{1}'.format(
                super(VirtWhoConfig, self).path(which='self'), which)
        if which and which in ('configs'):
            return '{0}/{1}/{2}/{3}'.format(
                self._server_config.url,
                'foreman_virt_who_configure/api/v2/organizations',
                self.read().organization_id,
                which
            )
        return super(VirtWhoConfig, self).path(which)

    def create_payload(self):
        """
        Wraps config in extra dict
        """
        return {u'foreman_virt_who_configure_config': super(VirtWhoConfig, self).create_payload()}

    def update_payload(self, fields=None):
        """
        Wraps config in extra dict
        """
        return {
            u'foreman_virt_who_configure_config': super(VirtWhoConfig, self).update_payload(fields)
        }

    def deploy_script(self, synchronous=True, **kwargs):
        """Helper for Config's deploy_script method.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('deploy_script'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """
        Override :meth:`nailgun.entity_mixins.EntityReadMixin.read` to ignore
        the ``hypervisor_password``
        """
        if not ignore:
            ignore = set()
        ignore.add('hypervisor_password')
        return super(VirtWhoConfig, self).read(entity, attrs, ignore, params)

    def get_organization_configs(self, synchronous=True, **kwargs):
        """
        Unusually, the ``/foreman_virt_who_configure/api/v2/organizations/
        :organization_id/configs`` path is totally unsupported.
        Support to List of virt-who configurations per organization.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('configs'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)
