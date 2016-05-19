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
from fauxfactory import gen_alphanumeric
from nailgun import client, entity_fields, signals
from nailgun.entity_mixins import (
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
    MissingValueError,
    _poll_task,
)
from packaging.version import Version
import random

from sys import version_info
if version_info.major == 2:  # pragma: no cover
    from httplib import ACCEPTED, NO_CONTENT  # pylint:disable=import-error
else:  # pragma: no cover
    from http.client import ACCEPTED, NO_CONTENT  # pylint:disable=import-error

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


def _handle_response(response, server_config, synchronous=False):
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

    """
    response.raise_for_status()
    if synchronous is True and response.status_code == ACCEPTED:
        return ForemanTask(server_config, id=response.json()['id']).poll()
    if response.status_code == NO_CONTENT:
        return
    if 'application/json' in response.headers.get('content-type', '').lower():
        return response.json()
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
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
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
        content_override
            /activation_keys/<id>/content_override
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
                'releases',
                'remove_subscriptions',
                'subscriptions'):
            return '{0}/{1}'.format(
                super(ActivationKey, self).path(which='self'),
                which
            )
        return super(ActivationKey, self).path(which)

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


class AuthSourceLDAP(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
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

    def read(self, entity=None, attrs=None, ignore=None):
        """Do not read the ``account_password`` attribute. Work around a bug.

        For more information, see `Bugzilla #1243036
        <https://bugzilla.redhat.com/show_bug.cgi?id=1243036>`_.

        """
        if attrs is None:
            attrs = self.update_json([])
        if ignore is None:
            ignore = set()
        ignore.add('account_password')
        return super(AuthSourceLDAP, self).read(entity, attrs, ignore)


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
            ),
            'public': entity_fields.BooleanField(),
            'query': entity_fields.StringField(required=True),
        }
        self._meta = {'api_path': 'api/v2/bookmarks', 'server_modes': ('sat')}
        super(Bookmark, self).__init__(server_config, **kwargs)


class CommonParameter(Entity):
    """A representation of a Common Parameter entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(required=True),
            'value': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': 'api/v2/common_parameters',
            'server_modes': ('sat'),
        }
        super(CommonParameter, self).__init__(server_config, **kwargs)


class ComputeAttribute(Entity, EntityCreateMixin, EntityReadMixin):
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
        EntityUpdateMixin):
    """A representation of a Compute Profile entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
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
                str_type=('alphanumeric', 'cjk'),  # cannot contain whitespace
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
            'max_count': entity_fields.IntegerField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
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

    def read(self, entity=None, attrs=None, ignore=None):
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
        return super(DiscoveryRule, self).read(entity, attrs, ignore)

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

    def read(self, entity=None, attrs=None, ignore=None):
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
        return super(DockerComputeResource, self).read(entity, attrs, ignore)


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
            # A server is pre-populated with "num_created_by_default" template
            # kinds. We use one of those instead of creating a new one.
            self.template_kind = TemplateKind(self._server_config)
            self.template_kind.id = random.randint(  # pylint:disable=C0103
                # pylint:disable=protected-access
                1, self.template_kind._meta['num_created_by_default']
            )

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {
            u'config_template': super(ConfigTemplate, self).create_payload()
        }

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1234973
        <https://bugzilla.redhat.com/show_bug.cgi?id=1234973>`_.

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {
            u'config_template': super(
                ConfigTemplate,
                self
            ).update_payload(fields)
        }

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        revision
            /config_templates/revision
        build_pxe_default
            /config_templates/build_pxe_default

        ``super`` is called otherwise.

        """
        if which in ('revision', 'build_pxe_default'):
            return '{0}/{1}'.format(
                super(ConfigTemplate, self).path(which='base'),
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
        response = client.get(self.path('build_pxe_default'), **kwargs)
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
            'command': entity_fields.StringField(
                required=True,
                str_type='latin1',
            ),
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


class ContentUpload(Entity):
    """A representation of a Content Upload entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'repository': entity_fields.OneToOneField(
                Repository,
                required=True,
            )
        }
        self._meta = {
            'api_path': (
                'katello/api/v2/repositories/:repository_id/content_uploads'
            ),
            'server_modes': ('sat'),
        }
        super(ContentUpload, self).__init__(server_config, **kwargs)


class ContentViewVersion(Entity, EntityReadMixin, EntityDeleteMixin):
    """A representation of a Content View Version non-entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'content_view': entity_fields.OneToOneField(ContentView),
            'environment': entity_fields.OneToManyField(Environment),
            'puppet_module': entity_fields.OneToManyField(PuppetModule),
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
        EntitySearchMixin):
    """A representation of a Content View Filter Rule entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('content_view_filter', kwargs)
        self._fields = {
            'content_view_filter': entity_fields.OneToOneField(
                AbstractContentViewFilter,
                required=True
            ),
            'end_date': entity_fields.DateField(),
            'errata': entity_fields.OneToOneField(Errata),
            'max_version': entity_fields.StringField(),
            'min_version': entity_fields.StringField(),
            'name': entity_fields.StringField(
                str_type='alpha',
                length=(6, 12)
            ),
            'start_date': entity_fields.DateField(),
            'types': entity_fields.ListField(),
            'version': entity_fields.StringField(),
        }
        super(ContentViewFilterRule, self).__init__(server_config, **kwargs)
        self._meta = {
            'server_modes': ('sat'),
            'api_path': '{0}/rules'.format(
                # pylint:disable=no-member
                self.content_view_filter.path('self')
            )
        }

    def read(self, entity=None, attrs=None, ignore=None):
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
        if 'errata_id' in attrs:
            ignore.discard('errata')  # pylint:disable=no-member
        return super(ContentViewFilterRule, self).read(entity, attrs, ignore)


class AbstractContentViewFilter(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
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
                length=(6, 12)
            ),
            'puppet_module': entity_fields.OneToOneField(PuppetModule),
        }
        super(ContentViewPuppetModule, self).__init__(server_config, **kwargs)
        self._meta = {
            'server_modes': ('sat'),
            'api_path': '{0}/content_view_puppet_modules'.format(
                self.content_view.path('self')  # pylint:disable=no-member
            )
        }

    def read(self, entity=None, attrs=None, ignore=None):
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

        if attrs is None:
            attrs = self.read_json()
        # The puppet_module_id is returned as uuid
        attrs['puppet_module_id'] = attrs.pop('uuid')

        if ignore is None:
            ignore = set()
        ignore.add('content_view')
        return super(ContentViewPuppetModule, self).read(entity, attrs, ignore)

    def create_payload(self):
        """Rename the ``puppet_module_id`` field to ``uuid``.

        For more information, see `Bugzilla #1238731
        <https://bugzilla.redhat.com/show_bug.cgi?id=1238731>`_.

        """
        payload = super(ContentViewPuppetModule, self).create_payload()
        if 'puppet_module_id' in payload:
            payload['uuid'] = payload.pop('puppet_module_id')
        return payload


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
            'component': entity_fields.OneToManyField(ContentViewVersion),
            'composite': entity_fields.BooleanField(),
            'description': entity_fields.StringField(),
            'label': entity_fields.StringField(),
            'last_published': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
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

    def read(self, entity=None, attrs=None, ignore=None):
        """Fetch an attribute missing from the server's response.

        For more information, see `Bugzilla #1237257
        <https://bugzilla.redhat.com/show_bug.cgi?id=1237257>`_.

        """
        if _get_version(self._server_config) < Version('6.1'):
            if attrs is None:
                attrs = self.read_json()
            org = _get_org(self._server_config, attrs['organization']['label'])
            attrs['organization'] = org.get_values()
        return super(ContentView, self).read(entity, attrs, ignore)

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

    def read(self, entity=None, attrs=None, ignore=None):
        """Deal with weirdly named data returned from the server.

        For more information, see `Bugzilla #1233245
        <https://bugzilla.redhat.com/show_bug.cgi?id=1233245>`_.

        """
        if attrs is None:
            attrs = self.read_json()
        attrs['domain_parameters_attributes'] = attrs.pop('parameters')
        return super(Domain, self).read(entity, attrs, ignore)

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


class Errata(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of an Errata entity."""
    # You cannot create an errata. Errata are a read-only entity.

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'content_view_version': entity_fields.OneToOneField(
                ContentViewVersion
            ),
            'repository': entity_fields.OneToOneField(Repository),
            'search': entity_fields.StringField(),
        }
        self._meta = {
            'api_path': '/katello/api/v2/errata',
            'server_modes': ('sat')
        }
        super(Errata, self).__init__(server_config, **kwargs)


class Filter(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Filter entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location),
            'organization': entity_fields.OneToManyField(Organization),
            'permission': entity_fields.OneToManyField(Permission),
            'role': entity_fields.OneToOneField(Role, required=True),
            'search': entity_fields.StringField(),
        }
        self._meta = {'api_path': 'api/v2/filters', 'server_modes': ('sat')}
        super(Filter, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'filter': super(Filter, self).create_payload()}


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


class GPGKey(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a GPG Key entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'content': entity_fields.StringField(required=True),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
        }
        self._meta = {
            'api_path': 'katello/api/v2/gpg_keys',
            'server_modes': ('sat'),
        }
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

    def read(self, entity=None, attrs=None, ignore=None):
        """Ignore 'host' field as it is not returned by the server.

        For more information, see `Bugzilla #1325989
        <https://bugzilla.redhat.com/show_bug.cgi?id=1325989>`_.

        """
        if ignore is None:
            ignore = set()
        ignore.add('host')
        return super(HostCollection, self).read(entity, attrs, ignore)

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
            'environment': entity_fields.OneToOneField(Environment),
            'location': entity_fields.OneToManyField(Location),
            'medium': entity_fields.OneToOneField(Media),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
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

    def read(self, entity=None, attrs=None, ignore=None):
        """Deal with several bugs.

        For more information, see:

        * `Bugzilla #1235377
          <https://bugzilla.redhat.com/show_bug.cgi?id=1235377>`_
        * `Bugzilla #1235379
          <https://bugzilla.redhat.com/show_bug.cgi?id=1235379>`_

        """
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
                attrs[attr] = attrs2[attr]
        return super(HostGroup, self).read(entity, attrs, ignore)

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


class Host(  # pylint:disable=too-many-instance-attributes
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Host entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'architecture': entity_fields.OneToOneField(Architecture),
            'build': entity_fields.BooleanField(),
            'capabilities': entity_fields.StringField(),
            'comment': entity_fields.StringField(),
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
            'puppet_class': entity_fields.OneToManyField(PuppetClass),
            'puppet_proxy': entity_fields.OneToOneField(SmartProxy),
            'realm': entity_fields.OneToOneField(Realm),
            'root_pass': entity_fields.StringField(length=(8, 30)),
            'subnet': entity_fields.OneToOneField(Subnet),
        }
        self._owner_type = None  # actual ``owner_type`` value
        self._meta = {'api_path': 'api/v2/hosts', 'server_modes': ('sat')}
        super(Host, self).__init__(server_config, **kwargs)

        # See https://github.com/SatelliteQE/nailgun/issues/258
        if (
                hasattr(self, 'owner') and
                hasattr(self.owner, 'id') and
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
            if self.operatingsystem.id not in [
                    os.id for os in self.medium.operatingsystem]:
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

    def read(self, entity=None, attrs=None, ignore=None):
        """Deal with oddly named and structured data returned by the server.

        For more information, see `Bugzilla #1235019
        <https://bugzilla.redhat.com/show_bug.cgi?id=1235019>`_.

        `content_facet_attributes` are returned as `content`, and only in case
        any of facet attributes were actually set.
        """
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()
        if attrs.get('content'):
            attrs['content_facet_attributes'] = attrs.pop('content')
        else:
            ignore.add('content_facet_attributes')
        ignore.add('root_pass')
        attrs['host_parameters_attributes'] = attrs.pop('parameters')
        attrs['puppet_class'] = attrs.pop('puppetclasses')
        return super(Host, self).read(entity, attrs, ignore)

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


class Image(Entity):
    """A representation of a Image entity."""

    def __init__(self, server_config=None, **kwargs):
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
            ),
            'operatingsystem': entity_fields.OneToOneField(
                OperatingSystem,
                required=True
            ),
            'username': entity_fields.StringField(required=True),
            'uuid': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': 'api/v2/compute_resources/:compute_resource_id/images',
            'server_modes': ('sat'),
        }
        super(Image, self).__init__(server_config, **kwargs)


class Interface(Entity):
    """A representation of a Interface entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'domain': entity_fields.OneToOneField(Domain),
            'host': entity_fields.OneToOneField(Host, required=True),
            'type': entity_fields.StringField(required=True),
            'ip': entity_fields.IPAddressField(required=True),
            'mac': entity_fields.MACAddressField(required=True),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
            'password': entity_fields.StringField(),
            'provider': entity_fields.StringField(),
            'subnet': entity_fields.OneToOneField(Subnet),
            'username': entity_fields.StringField(),
        }
        self._meta = {
            'api_path': 'api/v2/hosts/:host_id/interfaces',
            'server_modes': ('sat'),
        }
        super(Interface, self).__init__(server_config, **kwargs)


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
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'prior': entity_fields.OneToOneField(LifecycleEnvironment),
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
            'media': entity_fields.OneToManyField(Media),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
            'organization': entity_fields.OneToManyField(Organization),
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

    def read(self, entity=None, attrs=None, ignore=None):
        """Work around a bug in the server's response.

        Do not read the ``realm`` attribute. See `Bugzilla #1216234
        <https://bugzilla.redhat.com/show_bug.cgi?id=1216234>`_.

        """
        if ignore is None:
            ignore = set()
        ignore.add('realm')
        return super(Location, self).read(entity, attrs, ignore)

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

    def read(self, entity=None, attrs=None, ignore=None):
        """Rename ``path`` to ``path_``."""
        if attrs is None:
            attrs = self.read_json()
        attrs['path_'] = attrs.pop('path')
        return super(Media, self).read(entity, attrs, ignore)

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
            ),
            'ptable': entity_fields.OneToManyField(PartitionTable),
            'config_template': entity_fields.OneToManyField(ConfigTemplate),
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

    def read(self, entity=None, attrs=None, ignore=None):
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
            ignore
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
            'media': entity_fields.OneToManyField(Media),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
            'realm': entity_fields.OneToManyField(Realm),
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
        signals.pre_create.send(self, create_missing=create_missing)
        entity = Organization(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()
        signals.post_create.send(self, entity=entity)
        return entity

    def read(self, entity=None, attrs=None, ignore=None):
        """Fetch as many attributes as possible for this entity.

        Do not read the ``realm`` attribute. For more information, see
        `Bugzilla #1230873
        <https://bugzilla.redhat.com/show_bug.cgi?id=1230873>`_.

        """
        if ignore is None:
            ignore = set()
        ignore.add('realm')
        return super(Organization, self).read(entity, attrs, ignore)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1232871
        <https://bugzilla.redhat.com/show_bug.cgi?id=1232871>`_.

        .. WARNING:: Several attributes cannot be updated. See `Bugzilla
            #1230865 <https://bugzilla.redhat.com/show_bug.cgi?id=1230865>`_.

        """
        signals.pre_update.send(self, fields=fields)
        self.update_json(fields)
        entity = self.read()
        signals.post_update.send(self, entity=entity, fields=fields)
        return entity

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {
            u'organization': super(Organization, self).update_payload(fields)
        }

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


class OSDefaultTemplate(Entity):
    """A representation of a OS Default Template entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'config_template': entity_fields.OneToOneField(ConfigTemplate),
            'operatingsystem': entity_fields.OneToOneField(
                OperatingSystem
            ),
            'template_kind': entity_fields.OneToOneField(TemplateKind),
        }
        self._meta = {
            'api_path': (
                'api/v2/operatingsystems/:operatingsystem_id/'
                'os_default_templates'
            ),
            'server_modes': ('sat'),
        }
        super(OSDefaultTemplate, self).__init__(server_config, **kwargs)


class OverrideValue(Entity):
    """A representation of a Override Value entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'match': entity_fields.StringField(),
            'smart_variable': entity_fields.OneToOneField(SmartVariable),
            'value': entity_fields.StringField(),
        }
        self._meta = {
            'api_path': (
                # Create an override value for a specific smart_variable
                '/api/v2/smart_variables/:smart_variable_id/override_values',
                # Create an override value for a specific smart class parameter
                '/api/v2/smart_class_parameters/:smart_class_parameter_id/'
                'override_values',
            ),
            'server_modes': ('sat'),
        }
        super(OverrideValue, self).__init__(server_config, **kwargs)


class Permission(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Permission entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
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
            'gpg_key': entity_fields.OneToOneField(GPGKey),
            'label': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
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

    def read(self, entity=None, attrs=None, ignore=None):
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
        result = super(Product, self).read(entity, attrs, ignore)
        if 'sync_plan' in attrs:
            result.sync_plan = SyncPlan(
                server_config=self._server_config,
                id=attrs.get('sync_plan_id'),
                organization=result.organization,
            )
        return result

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
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(4, 30),
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'os_family': entity_fields.StringField(choices=_OPERATING_SYSTEMS),
        }
        self._meta = {'api_path': 'api/v2/ptables', 'server_modes': ('sat')}
        super(PartitionTable, self).__init__(server_config, **kwargs)
        # The following fields were added in Satellite 6.2, removing them if we
        # have previous version of Satellite
        if _get_version(self._server_config) < Version('6.2'):
            self._fields.pop('location')
            self._fields.pop('organization')


class PuppetClass(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Puppet Class entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
        }
        self._meta = {
            'api_path': 'api/v2/puppetclasses',
            'server_modes': ('sat'),
        }
        super(PuppetClass, self).__init__(server_config, **kwargs)


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
                length=(6, 12)
            ),
            'project_page': entity_fields.URLField(),
            'repository': entity_fields.OneToManyField(Repository),
            'source': entity_fields.URLField(),
            'summary': entity_fields.StringField(),
            'version': entity_fields.StringField(),
        }
        self._meta = {'api_path': 'katello/api/v2/puppet_modules'}
        super(PuppetModule, self).__init__(server_config, **kwargs)


class Realm(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Realm entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
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
        signals.pre_create.send(self, create_missing=create_missing)
        entity = Realm(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()
        signals.post_create.send(self, entity=entity)
        return entity


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
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
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

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'registry': super(Registry, self).update_payload(fields)}


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
            'checksum_type': entity_fields.StringField(
                choices=('sha1', 'sha256'),
            ),
            'content_counts': entity_fields.DictField(),
            'content_type': entity_fields.StringField(
                choices=('puppet', 'yum', 'file', 'docker'),
                default='yum',
                required=True,
            ),
            'container_repository_name': entity_fields.StringField(),
            # Just setting `str_type='alpha'` will fail with this error:
            # {"docker_upstream_name":["must be a valid docker name"]}}
            'docker_upstream_name': entity_fields.StringField(
                default='busybox'
            ),
            'gpg_key': entity_fields.OneToOneField(GPGKey),
            'label': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
            'product': entity_fields.OneToOneField(Product, required=True),
            'unprotected': entity_fields.BooleanField(),
            'url': entity_fields.URLField(
                default=_FAKE_YUM_REPO,
                required=True,
            ),
        }
        if _get_version(server_config) < Version('6.1'):
            # Adjust for Satellite 6.0
            del self._fields['docker_upstream_name']
            self._fields['content_type'].choices = (tuple(
                set(self._fields['content_type'].choices) - set(['docker'])
            ))
            del self._fields['checksum_type']
        self._meta = {
            'api_path': 'katello/api/v2/repositories',
            'server_modes': ('sat'),
        }
        super(Repository, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        sync
            /repositories/<id>/sync
        upload_content
            /repositories/<id>/upload_content

        ``super`` is called otherwise.

        """
        if which in ('sync', 'upload_content'):
            return '{0}/{1}'.format(
                super(Repository, self).path(which='self'),
                which
            )
        return super(Repository, self).path(which)

    def create_missing(self):
        """Conditionally mark ``docker_upstream_name`` as required.

        Mark ``docker_upstream_name`` as required if ``content_type`` is
        "docker".

        """
        if getattr(self, 'content_type', '') == 'docker':
            self._fields['docker_upstream_name'].required = True
        super(Repository, self).create_missing()

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


class RepositorySet(
        Entity,
        EntityReadMixin,
        EntitySearchMixin):
    """ A representation of a Repository Set entity"""
    def __init__(self, server_config=None, **kwargs):
        _check_for_value('product', kwargs)
        self._fields = {
            'contentUrl': entity_fields.URLField(required=True),
            'gpgUrl': entity_fields.URLField(required=True),
            'label': entity_fields.StringField(required=True),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
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
            # pylint:disable=no-member
            'api_path': '{0}/repository_sets'.format(self.product.path()),
        }

    def available_repositories(self, synchronous=True, **kwargs):
        """Lists available repositories for the repository set

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
        response = client.get(self.path('available_repositories'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

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
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('disable'), **kwargs)
        return _handle_response(response, self._server_config, synchronous)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        available_repositories
            /products/<product_id>/repository_sets/<id>/available_repositories
        enable
            /products/<product_id>/repository_sets/<id>/enable
        disable
            /products/<product_id>/repository_sets/<id>/disable

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

    def read(self, entity=None, attrs=None, ignore=None):
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
        ignore.add('product')
        return super(RepositorySet, self).read(entity, attrs, ignore)

    def search_normalize(self, results):
        """Provide a value for `product` field.

        Method ``search`` will create entities from search results. Search
        results do not contain `product` field, which is required for
        ``RepositorySet`` entity initialization.

        """
        for result in results:
            result['product_id'] = self.product.id  # pylint:disable=no-member
        return super(RepositorySet, self).search_normalize(results)


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
            'name': entity_fields.StringField(required=True),
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

    def read(self, entity=None, attrs=None, ignore=None):
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
        return super(RHCIDeployment, self).read(entity, attrs, ignore)

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
            'name': entity_fields.StringField(
                required=True,
                str_type='alphanumeric',
                length=(2, 30),  # min length is 2 and max length is arbitrary
            )
        }
        self._meta = {
            'api_path': 'api/v2/roles',
            'server_modes': ('sat', 'sam'),
        }
        super(Role, self).__init__(server_config, **kwargs)


class Setting(Entity, EntityReadMixin, EntitySearchMixin, EntityUpdateMixin):
    """A representation of a Setting entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'created_at': entity_fields.DateTimeField(),
            'default': entity_fields.StringField(),
            'description': entity_fields.StringField(),
            'name': entity_fields.StringField(),
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
        EntityReadMixin,
        EntitySearchMixin,
        EntityUpdateMixin):
    """A representation of a Smart Proxy entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
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
            /katello/api/v2/smart_proxies/:id/refresh

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

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1262037
        <https://bugzilla.redhat.com/show_bug.cgi?id=1262037>`_.

        """
        signals.pre_update.send(self, fields=fields)
        self.update_json(fields)
        entity = self.read()
        signals.post_update.send(self, entity=entity, fields=fields)
        return entity

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {
            u'smart_proxy': super(SmartProxy, self).update_payload(fields)
        }


class SmartVariable(Entity):
    """A representation of a Smart Variable entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'default_value': entity_fields.StringField(),
            'description': entity_fields.StringField(),
            'override_value_order': entity_fields.StringField(),
            'puppetclass': entity_fields.OneToOneField(PuppetClass),
            'validator_rule': entity_fields.StringField(),
            'validator_type': entity_fields.StringField(),
            'variable': entity_fields.StringField(required=True),
            'variable_type': entity_fields.StringField(),
        }
        self._meta = {
            'api_path': 'api/v2/smart_variables',
            'server_modes': ('sat'),
        }
        super(SmartVariable, self).__init__(server_config, **kwargs)


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
            'dns_primary': entity_fields.IPAddressField(),
            'dns_secondary': entity_fields.IPAddressField(),
            'domain': entity_fields.OneToManyField(Domain),
            'from': entity_fields.IPAddressField(),
            'gateway': entity_fields.StringField(),
            'mask': entity_fields.NetmaskField(required=True),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
            'network': entity_fields.IPAddressField(required=True),
            'to': entity_fields.IPAddressField(),
            'vlanid': entity_fields.StringField(),
        }
        if _get_version(server_config) >= Version('6.1'):
            self._fields.update({
                'boot_mode': entity_fields.StringField(
                    choices=('Static', 'DHCP',),
                    default=u'DHCP',
                ),
                'dhcp': entity_fields.OneToOneField(SmartProxy),
                # When reading a subnet, no discovery information is
                # returned by the server. See Bugzilla #1217146.
                'discovery': entity_fields.OneToOneField(SmartProxy),
                'dns': entity_fields.OneToOneField(SmartProxy),
                'ipam': entity_fields.StringField(
                    choices=(u'DHCP', u'Internal DB'),
                    default=u'DHCP',
                ),
                'location': entity_fields.OneToManyField(Location),
                'organization': entity_fields.OneToManyField(Organization),
                'tftp': entity_fields.OneToOneField(SmartProxy),
            })
        self._meta = {'api_path': 'api/v2/subnets', 'server_modes': ('sat')}
        super(Subnet, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'subnet': super(Subnet, self).create_payload()}

    def read(self, entity=None, attrs=None, ignore=None):
        """Fetch as many attributes as possible for this entity.

        Do not read the ``discovery`` attribute. For more information, see
        `Bugzilla #1217146
        <https://bugzilla.redhat.com/show_bug.cgi?id=1217146>`_.

        """

        if ignore is None:
            ignore = set()
        ignore.add('discovery')
        return super(Subnet, self).read(entity, attrs, ignore)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'subnet': super(Subnet, self).update_payload(fields)}


class Subscription(
        Entity,
        EntityReadMixin,
        EntitySearchMixin):
    """A representation of a Subscription entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'activation_key': entity_fields.OneToOneField(ActivationKey),
            'host': entity_fields.OneToOneField(Host),
            'organization': entity_fields.OneToOneField(Organization),
            'quantity': entity_fields.IntegerField(),
            'subscriptions': entity_fields.OneToManyField(Subscription),
        }
        # Before Satellite 6.2 System entity was used instead of Host
        if _get_version(server_config) < Version('6.2'):
            self._fields['system'] = entity_fields.OneToOneField(System)
            self._fields.pop('host')
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

    def search_raw(self, fields=None, query=None):
        """Completely override the inherited ``search_raw`` method for older
        Satellite versions.

        The ``GET /katello/api/v2/subscriptions`` API call is not available.
        Instead, one of the following must be used:

        * ``GET /katello/api/v2/activation_keys/<id>/subscriptions``
        * ``GET /katello/api/v2/organizations/<id>/subscriptions``
        * ``GET /katello/api/v2/systems/<id>/subscriptions``

        Use the activation key path if ``self.activation_key`` is set, use the
        organization path if ``self.organization`` is set, use the system path
        if ``self.system`` is set, or raise an exception otherwise.

        """
        if _get_version(self._server_config) >= Version('6.2'):
            return super(Subscription, self).search_raw(fields, query)
        path = None
        attrs = ('activation_key', 'organization', 'system')
        for attr in attrs:
            if hasattr(self, attr):
                path = getattr(self, attr).path('subscriptions')
                break
        if path is None:
            raise MissingValueError(
                'A value must be provided for one of the following fields: '
                '{0}. This is because the "GET /katello/api/v2/subscriptions" '
                'API call is not available. See the documentation for method '
                '`nailgun.entities.Subscription.search_raw` for details.'
                .format(attrs)
            )
        return client.get(
            path,
            data=self.search_payload(fields, query),
            **self._server_config.get_client_kwargs()
        )

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
        return _handle_response(response, self._server_config, synchronous)

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
        return _handle_response(response, self._server_config, synchronous)

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
        return _handle_response(response, self._server_config, synchronous)


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
                choices=('hourly', 'daily', 'weekly'),
                required=True,
            ),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'product': entity_fields.OneToManyField(Product),
            'sync_date': entity_fields.DateTimeField(required=True),
        }
        super(SyncPlan, self).__init__(server_config, **kwargs)
        self._meta = {
            # pylint:disable=no-member
            'api_path': '{0}/sync_plans'.format(self.organization.path()),
        }

    def read(self, entity=None, attrs=None, ignore=None):
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
        return super(SyncPlan, self).read(entity, attrs, ignore)

    def create_payload(self):
        """Convert ``sync_date`` to a string.

        The ``sync_date`` instance attribute on the current object is not
        affected. However, the ``'sync_date'`` key in the dict returned by
        ``create_payload`` is a string.

        """
        data = super(SyncPlan, self).create_payload()
        if 'sync_date' in data:
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

    def read(self, entity=None, attrs=None, ignore=None):
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
        return super(System, self).read(entity, attrs, ignore)


class TemplateCombination(Entity):
    """A representation of a Template Combination entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'config_template': entity_fields.OneToOneField(
                ConfigTemplate,
                required=True,
            ),
            'environment': entity_fields.OneToOneField(Environment),
            'hostgroup': entity_fields.OneToOneField(HostGroup),
        }
        self._meta = {
            'api_path': (
                'api/v2/config_templates/:config_template_id/'
                'template_combinations'
            ),
            'server_modes': ('sat'),
        }
        super(TemplateCombination, self).__init__(server_config, **kwargs)


class TemplateKind(Entity, EntityReadMixin):
    """A representation of a Template Kind entity.

    Unusually, the ``/api/v2/template_kinds/:id`` path is totally unsupported.

    """
    def __init__(self, server_config=None, **kwargs):
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
        EntityUpdateMixin):
    """A representation of a User Group entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'admin': entity_fields.BooleanField(),
            'name': entity_fields.StringField(
                required=True,
                str_type='alpha',
                length=(6, 12),
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
        signals.pre_create.send(self, create_missing=create_missing)
        entity = UserGroup(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()
        signals.post_create.send(self, entity=entity)
        return entity

    def read(self, entity=None, attrs=None, ignore=None):
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
        return super(UserGroup, self).read(entity, attrs, ignore)


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
            'firstname': entity_fields.StringField(length=(1, 50)),
            'lastname': entity_fields.StringField(length=(1, 50)),
            'location': entity_fields.OneToManyField(Location),
            'login': entity_fields.StringField(
                length=(1, 100),
                required=True,
                str_type=('alpha', 'alphanumeric', 'cjk', 'latin1'),
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

    def read(self, entity=None, attrs=None, ignore=None):
        """Do not read the ``password`` argument."""
        if ignore is None:
            ignore = set()
        ignore.add('password')
        return super(User, self).read(entity, attrs, ignore)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'user': super(User, self).update_payload(fields)}

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1235012
        <https://bugzilla.redhat.com/show_bug.cgi?id=1235012>`_.

        """
        signals.pre_update.send(self, fields=fields)
        self.update_json(fields)
        entity = self.read()
        signals.post_update.send(self, entity=entity, fields=fields)
        return entity
