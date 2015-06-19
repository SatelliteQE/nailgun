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
from fauxfactory import gen_alpha, gen_alphanumeric, gen_url
from nailgun import client, entity_fields
from nailgun.entity_mixins import (
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntityUpdateMixin,
    _poll_task,
)
from pkg_resources import parse_version
from time import sleep
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
# obfuscate the design of the entities.

# pylint:disable=attribute-defined-outside-init
# NailGun aims to be like a traditional database ORM and allow uses of the dot
# operator such as these:
#
#     product = Product(server_config, id=5).read()
#     product.name
#     product.organization.id
#
# Unfortunately, these fields cannot simply be initialized with `None`, as the
# server considers "nil" to be different from the absence of a value. This
# inevitably means that instance attributes will be defined outside __init__.


_FAKE_YUM_REPO = 'http://inecas.fedorapeople.org/fakerepos/zoo3/'
_OPERATING_SYSTEMS = (
    'AIX',
    'Archlinux',
    'Debian',
    'Freebsd',
    'Gentoo',
    'Redhat',
    'Solaris',
    'Suse',
    'Windows',
)


class APIResponseError(Exception):
    """Indicates an error if response returns unexpected result."""


class HostCreateMissingError(Exception):
    """Indicates that ``Host.create_missing`` was unable to execute."""


def _handle_response(response, server_config, synchronous=False):
    """Handle a server's response in a typical fashion.

    Do the following:

    1. Check the server's response for an HTTP status code indicating an error.
    2. Poll the server for a foreman task to complete if an HTTP 202 (accepted)
       status code is returned and ``synchronous is True``.
    3. Immediately return if an HTTP "NO CONTENT" response is received.
    4. Return the server's response, with all JSON decoded.

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
    return response.json()


def _check_for_value(field_name, field_values):
    """Check to see if ``field_name`` is present in ``field_values``.

    An entity may use this function in its ``__init__`` method to ensure that a
    parameter required for object instantiation has been passed in. For
    example, in :class:`nailgun.entities.ContentViewPuppetModule`:

    >>> def __init__(self, server_config=None, **kwargs):
    >>>     _check_for_param('content_view', kwargs)
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


class ActivationKey(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Activtion Key entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'auto_attach': entity_fields.BooleanField(),
            'content_view': entity_fields.OneToOneField(ContentView),
            'description': entity_fields.StringField(),
            'environment': entity_fields.OneToOneField(Environment),
            'host_collection': entity_fields.OneToManyField(HostCollection),
            'max_content_hosts': entity_fields.IntegerField(),
            'name': entity_fields.StringField(required=True),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'unlimited_content_hosts': entity_fields.BooleanField(),
        }
        self._meta = {
            'api_path': 'katello/api/v2/activation_keys',
            'server_modes': ('sat', 'sam'),
        }
        super(ActivationKey, self).__init__(server_config, **kwargs)

    def read_raw(self):
        """Work around `Redmine #4638`_.

        Poll the server several times upon receiving a 404, just to be *really*
        sure that the requested activation key is non-existent. Do this because
        elasticsearch can be slow about indexing newly created activation keys,
        especially when the server is under load.

        .. _Redmine #4638: http://projects.theforeman.org/issues/4638

        """
        super_read_raw = super(ActivationKey, self).read_raw
        response = super_read_raw()
        for _ in range(5):
            if response.status_code == 404:
                sleep(5)
                response = super_read_raw()
        return response

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

        ``super`` is called otherwise.

        """
        if which in (
                'add_subscriptions',
                'content_override',
                'releases',
                'remove_subscriptions'):
            return '{0}/{1}'.format(
                super(ActivationKey, self).path(which='self'),
                which
            )
        return super(ActivationKey, self).path(which)

    def add_subscriptions(self, params):
        """Helper for adding subscriptions to activation key.

        :param params: Parameters that are encoded to JSON and passed in
            with the request. See the API documentation page for a list of
            parameters and their descriptions.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        response = client.put(
            self.path('add_subscriptions'),
            params,
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)

    def content_override(self, content_label, value):
        """Override the content of an activation key.

        :param content_label: Label for the new content.
        :param value: The new content for this activation key.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        response = client.put(
            self.path('content_override'),
            {'content_override': {
                'content_label': content_label,
                'value': value,
            }},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)


class Architecture(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Architecture entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(required=True),
            'operatingsystem': entity_fields.OneToManyField(
                OperatingSystem,
                null=True,
            ),
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

        FIXME: File a bug at https://bugzilla.redhat.com/ and link to it.

        """
        self.update_json(fields)
        return self.read()


class AuthSourceLDAP(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a AuthSourceLDAP entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'account': entity_fields.StringField(null=True),
            'attr_photo': entity_fields.StringField(null=True),
            'base_dn': entity_fields.StringField(null=True),
            'host': entity_fields.StringField(required=True, length=(1, 60)),
            'name': entity_fields.StringField(required=True, length=(1, 60)),
            'onthefly_register': entity_fields.BooleanField(null=True),
            'port': entity_fields.IntegerField(null=True),
            'tls': entity_fields.BooleanField(null=True),

            # required if onthefly_register is true,
            'account_password': entity_fields.StringField(null=True),
            'attr_firstname': entity_fields.StringField(null=True),
            'attr_lastname': entity_fields.StringField(null=True),
            'attr_login': entity_fields.StringField(null=True),
            'attr_mail': entity_fields.EmailField(null=True),
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
            self.account_password = (
                self._fields['account_password'].gen_value()
            )
            self.attr_firstname = self._fields['attr_firstname'].gen_value()
            self.attr_lastname = self._fields['attr_lastname'].gen_value()
            self.attr_login = self._fields['attr_login'].gen_value()
            self.attr_mail = self._fields['attr_mail'].gen_value()

    def read(self, entity=None, attrs=None, ignore=('account_password',)):
        """Do not read the ``account_password`` attribute from the server."""
        return super(AuthSourceLDAP, self).read(entity, attrs, ignore)


class Bookmark(Entity):
    """A representation of a Bookmark entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'controller': entity_fields.StringField(required=True),
            'name': entity_fields.StringField(required=True),
            'public': entity_fields.BooleanField(null=True),
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


class ComputeAttribute(Entity):
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
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Compute Profile entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': 'api/v2/compute_profiles',
            'server_modes': ('sat'),
        }
        super(ComputeProfile, self).__init__(server_config, **kwargs)


class AbstractComputeResource(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
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
            'description': entity_fields.StringField(null=True),
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
                null=True,
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


class DockerComputeResource(AbstractComputeResource):
    """A representation of a Docker Compute Resource entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'email': entity_fields.EmailField(),
            'password': entity_fields.StringField(null=True),
            'url': entity_fields.URLField(required=True),
            'user': entity_fields.StringField(null=True),
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

    def read(self, entity=None, attrs=None, ignore=('password',)):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1223540
        <https://bugzilla.redhat.com/show_bug.cgi?id=1223540>`_.

        Also, do not try to read the "password" field. No value is returned for
        the field, for obvious reasons.

        """
        if attrs is None:
            attrs = self.read_json()
        if 'email' not in attrs and 'email' not in ignore:
            response = client.put(
                self.path('self'),
                {},
                **self._server_config.get_client_kwargs()
            )
            response.raise_for_status()
            attrs['email'] = response.json()['email']
        return super(DockerComputeResource, self).read(entity, attrs, ignore)


class LibvirtComputeResource(AbstractComputeResource):
    """A representation of a Libvirt Compute Resource entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'display_type': entity_fields.StringField(
                choices=(u'VNC', u'SPICE'),
                required=True,
            ),
            'set_console_password': entity_fields.BooleanField(null=True),
        }
        super(LibvirtComputeResource, self).__init__(server_config, **kwargs)
        self._fields['provider'].default = 'Libvirt'
        self._fields['provider'].required = True
        self._fields['provider_friendly_name'].default = 'Libvirt'


class ConfigGroup(Entity):
    """A representation of a Config Group entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(required=True),
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
        EntityUpdateMixin):
    """A representation of a Config Template entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'audit_comment': entity_fields.StringField(null=True),
            'locked': entity_fields.BooleanField(null=True),
            'name': entity_fields.StringField(required=True),
            'operatingsystem': entity_fields.OneToManyField(
                OperatingSystem,
                null=True,
            ),
            'organization': entity_fields.OneToManyField(
                Organization,
                null=True,
            ),
            'snippet': entity_fields.BooleanField(null=True, required=True),
            'template': entity_fields.StringField(required=True),
            'template_combinations': entity_fields.ListField(null=True),
            'template_kind': entity_fields.OneToOneField(
                TemplateKind,
                null=True,
            ),
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

        FIXME: File a bug at https://bugzilla.redhat.com/ and link to it.

        """
        self.update_json(fields)
        return self.read()

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


class AbstractDockerContainer(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a docker container.

    This class is abstract because all containers must come from somewhere, but
    this class does not have attributes for specifying that information.

    .. WARNING:: A docker compute resource must be specified when creating a
        docker container.

    """

    def __init__(self, server_config=None, **kwargs):
        fields = {
            'attach_stderr': entity_fields.BooleanField(null=True),
            'attach_stdin': entity_fields.BooleanField(null=True),
            'attach_stdout': entity_fields.BooleanField(null=True),
            'command': entity_fields.StringField(
                required=True,
                str_type='latin1',
            ),
            'compute_resource': entity_fields.OneToOneField(
                AbstractComputeResource
            ),
            'cpu_set': entity_fields.StringField(null=True),
            'cpu_shares': entity_fields.StringField(null=True),
            'entrypoint': entity_fields.StringField(null=True),
            'location': entity_fields.OneToManyField(Location, null=True),
            'memory': entity_fields.StringField(null=True),
            # The "name" field may be any of a-zA-Z0-9_.-,
            # "alphanumeric" is a subset of those legal characters.
            'name': entity_fields.StringField(
                required=True,
                str_type='alphanumeric',
            ),
            'organization': entity_fields.OneToManyField(
                Organization,
                null=True,
            ),
            'tty': entity_fields.BooleanField(null=True),
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
        return AbstractDockerContainer(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def power(self, power_action):
        """Run a power operation on a container.

        :param power_action: One of 'start', 'stop' or 'status'.
        :returns: Information about the current state of the container.

        """
        power_actions = ('start', 'stop', 'status')
        if power_action not in power_actions:
            raise ValueError('Received {0} but expected one of {1}'.format(
                power_action, power_actions
            ))
        response = client.put(
            self.path(which='power'),
            {u'power_action': power_action},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)

    def logs(self, stdout=None, stderr=None, tail=None):
        """Get logs from this container.

        :param stdout: ???
        :param stderr: ???
        :param tail: How many lines should be tailed? Server does 100 by
            default.
        :returns: The server's response, with all JSON decoded.

        """
        data = {}
        if stdout is not None:
            data['stdout'] = stdout
        if stderr is not None:
            data['stderr'] = stderr
        if tail is not None:
            data['tail'] = tail
        response = client.get(
            self.path(which='logs'),
            data=data,
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)


class DockerHubContainer(AbstractDockerContainer):
    """A docker container that comes from Docker Hub."""

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

        promote
            /content_view_versions/<id>/promote

        ``super`` is called otherwise.

        """
        if which == 'promote':
            return '{0}/promote'.format(
                super(ContentViewVersion, self).path(which='self')
            )
        return super(ContentViewVersion, self).path(which)

    def promote(self, environment_id, synchronous=True):
        """Helper for promoting an existing published content view.

        :param environment_id: The environment Id to promote to.
        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :return: Return information about the completed foreman task if an HTTP
            202 response is received and ``synchronous`` is true. Return the
            JSON response otherwise.

        """
        response = client.post(
            self.path('promote'),
            {u'environment_id': environment_id},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config, synchronous)


class ContentViewFilterRule(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
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
            'name': entity_fields.StringField(),
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

    def read(self, entity=None, attrs=None, ignore=('content_view_filter',)):
        """Deal with redundant entity fields."""
        if entity is None:
            entity = type(self)(
                self._server_config,
                # pylint:disable=no-member
                content_view_filter=self.content_view_filter,
            )
        if attrs is None:
            attrs = self.read_json()
        # Field should be present in entity only if it was passed in attributes
        for entity_field in entity.get_fields().keys():
            if entity_field not in attrs:
                del entity._fields[entity_field]
        return super(ContentViewFilterRule, self).read(entity, attrs, ignore)


class AbstractContentViewFilter(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
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
            'name': entity_fields.StringField(required=True),
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
            'name': entity_fields.StringField(),
            'puppet_module': entity_fields.OneToOneField(PuppetModule),
        }
        super(ContentViewPuppetModule, self).__init__(server_config, **kwargs)
        self._meta = {
            'server_modes': ('sat'),
            'api_path': '{0}/content_view_puppet_modules'.format(
                self.content_view.path('self')  # pylint:disable=no-member
            )
        }

    def read(self, entity=None, attrs=None, ignore=('content_view',)):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`ContentViewPuppetModule` requires that an
        ``content_view`` be provided, so this technique will not work. Do
        this instead::

            entity = type(self)(content_view=self.content_view.id)

        Also, deal with the weirdly named "uuid" parameter.

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
        uuid = attrs.pop('uuid')
        if uuid is None:
            attrs['puppet_module'] = None
        else:
            attrs['puppet_module'] = {'id': uuid}
        return super(ContentViewPuppetModule, self).read(entity, attrs, ignore)

    def create_payload(self):
        """Rename the ``puppet_module_id`` field to ``uuid``."""
        payload = super(ContentViewPuppetModule, self).create_payload()
        if 'puppet_module_id' in payload:
            payload['uuid'] = payload.pop('puppet_module_id')
        return payload


class ContentView(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Content View entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'component': entity_fields.OneToManyField(ContentViewVersion),
            'composite': entity_fields.BooleanField(),
            'description': entity_fields.StringField(),
            'label': entity_fields.StringField(),
            'name': entity_fields.StringField(required=True),
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

    def publish(self, synchronous=True):
        """Helper for publishing an existing content view.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return a task ID otherwise.
        :return: Return information about the completed foreman task if an HTTP
            202 response is received and ``synchronous`` is true. Return the
            JSON response otherwise.

        """
        response = client.post(
            self.path('publish'),
            {u'id': self.id},  # pylint:disable=no-member
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config, synchronous)

    def set_repository_ids(self, repo_ids):
        """Give this content view some repositories.

        :param repo_ids: A list of repository IDs.
        :returns: The server's response, with all JSON decoded.

        """
        response = client.put(
            self.path(which='self'),
            {u'repository_ids': repo_ids},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)

    def available_puppet_modules(self):
        """Get puppet modules available to be added to the content view.

        :returns: The server's response, with all JSON decoded.

        """
        response = client.get(
            self.path('available_puppet_modules'),
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)

    def add_puppet_module(self, author, name):
        """Add a puppet module to the content view.

        :param author: The author of the puppet module.
        :param name: The name of the puppet module.
        :returns: The server's response, with all JSON decoded.

        """
        response = client.post(
            self.path('content_view_puppet_modules'),
            {u'author': author, u'name': name},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)

    def copy(self, name):
        """Clone provided content view.

        :param name: The name for new cloned content view.
        :returns: The server's response, with all JSON decoded.

        """
        response = client.post(
            self.path('copy'),
            {u'id': self.id, u'name': name},  # pylint:disable=no-member
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)

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
        EntityUpdateMixin):
    """A representation of a Domain entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'dns': entity_fields.OneToOneField(SmartProxy, null=True),
            'domain_parameters_attributes': entity_fields.ListField(null=True),
            'fullname': entity_fields.StringField(null=True),
            'location': entity_fields.OneToManyField(Location, null=True),
            'name': entity_fields.StringField(required=True),
            'organization': entity_fields.OneToManyField(
                Organization,
                null=True,
            ),
        }
        self._meta = {'api_path': 'api/v2/domains', 'server_modes': ('sat')}
        super(Domain, self).__init__(server_config, **kwargs)

    def create_missing(self):
        """Customize the process of auto-generating instance attributes.

        By default, :meth:`nailgun.entity_fields.URLField.gen_value` does not
        return especially unique values. This is problematic, as all domain
        names must be unique.

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

    def read(self, entity=None, attrs=None, ignore=()):
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

        FIXME: File a bug at https://bugzilla.redhat.com/ and link to it.

        """
        self.update_json(fields)
        return self.read()


class Environment(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Environment entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location, null=True),
            'name': entity_fields.StringField(
                required=True,
                str_type='alphanumeric',  # cannot contain whitespace
            ),
            'organization': entity_fields.OneToManyField(
                Organization,
                null=True,
            ),
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


class Errata(Entity):
    """A representation of an Errata entity."""
    # You cannot create an errata. Errata are a read-only entity.

    def __init__(self, server_config=None, **kwargs):
        self._meta = {'api_path': 'api/v2/errata', 'server_modes': ('sat')}
        super(Errata, self).__init__(server_config, **kwargs)


class Filter(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Filter entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location, null=True),
            'organization': entity_fields.OneToManyField(
                Organization,
                null=True,
            ),
            'permission': entity_fields.OneToManyField(Permission, null=True),
            'role': entity_fields.OneToOneField(Role, required=True),
            'search': entity_fields.StringField(null=True),
        }
        self._meta = {'api_path': 'api/v2/filters', 'server_modes': ('sat')}
        super(Filter, self).__init__(server_config, **kwargs)


class ForemanTask(Entity, EntityReadMixin):
    """A representation of a Foreman task."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {
            'api_path': 'foreman_tasks/api/tasks',
            'server_modes': ('sat'),
        }
        super(ForemanTask, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        bulk_search
            /foreman_tasks/api/tasks/bulk_search

        ``super(which='self')`` is called otherwise. There is no path available
        for fetching all tasks.

        """
        if which == 'bulk_search':
            return '{0}/bulk_search'.format(
                super(ForemanTask, self).path(which='base')
            )
        return super(ForemanTask, self).path(which='self')

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


class GPGKey(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a GPG Key entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'content': entity_fields.StringField(required=True),
            'name': entity_fields.StringField(required=True),
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
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Host Collection entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'description': entity_fields.StringField(),
            'max_content_hosts': entity_fields.IntegerField(),
            'name': entity_fields.StringField(required=True),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'system': entity_fields.OneToManyField(System),
            'unlimited_content_hosts': entity_fields.BooleanField(),
        }
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


class HostGroup(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Host Group entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'architecture': entity_fields.OneToOneField(
                Architecture,
                null=True,
            ),
            'domain': entity_fields.OneToOneField(Domain, null=True),
            'environment': entity_fields.OneToOneField(Environment, null=True),
            'location': entity_fields.OneToManyField(Location, null=True),
            'medium': entity_fields.OneToOneField(Media, null=True),
            'name': entity_fields.StringField(required=True),
            'operatingsystem': entity_fields.OneToOneField(
                OperatingSystem,
                null=True,
            ),
            'organization': entity_fields.OneToManyField(
                Organization,
                null=True,
            ),
            'parent': entity_fields.OneToOneField(HostGroup, null=True),
            'ptable': entity_fields.OneToOneField(PartitionTable, null=True),
            'realm': entity_fields.OneToOneField(Realm, null=True),
            'subnet': entity_fields.OneToOneField(Subnet, null=True),
        }
        self._meta = {'api_path': 'api/v2/hostgroups', 'server_modes': ('sat')}
        super(HostGroup, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'hostgroup': super(HostGroup, self).create_payload()}

    def read(self, entity=None, attrs=None, ignore=()):
        """Deal with weirdly named data returned from the server.

        When creating a HostGroup, the server accepts a field named 'parent'.
        When reading a HostGroup, the server returns a semantically identical
        field named 'ancestry'.

        """
        if attrs is None:
            attrs = self.read_json()
        parent_id = attrs.pop('ancestry')
        if parent_id is None:
            attrs['parent'] = None
        else:
            attrs['parent'] = {'id': parent_id}

        return super(HostGroup, self).read(entity, attrs, ignore)


class Host(  # pylint:disable=too-many-instance-attributes
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Host entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'architecture': entity_fields.OneToOneField(
                Architecture,
                null=True,
            ),
            'build': entity_fields.BooleanField(null=True),
            'capabilities': entity_fields.StringField(null=True),
            'compute_profile': entity_fields.OneToOneField(
                ComputeProfile,
                null=True,
            ),
            'compute_resource': entity_fields.OneToOneField(
                AbstractComputeResource,
                null=True,
            ),
            'domain': entity_fields.OneToOneField(Domain, null=True),
            'enabled': entity_fields.BooleanField(null=True),
            'environment': entity_fields.OneToOneField(Environment, null=True),
            'hostgroup': entity_fields.OneToOneField(HostGroup, null=True),
            'host_parameters_attributes': entity_fields.ListField(null=True),
            'image': entity_fields.OneToOneField(Image, null=True),
            'ip': entity_fields.StringField(null=True),
            'location': entity_fields.OneToOneField(Location, required=True),
            'mac': entity_fields.MACAddressField(null=True),
            'managed': entity_fields.BooleanField(null=True),
            'medium': entity_fields.OneToOneField(Media, null=True),
            'model': entity_fields.OneToOneField(Model, null=True),
            'name': entity_fields.StringField(required=True, str_type='alpha'),
            'operatingsystem': entity_fields.OneToOneField(
                OperatingSystem,
                null=True,
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'owner': entity_fields.OneToOneField(User, null=True),
            'owner_type': entity_fields.StringField(
                choices=('User', 'Usergroup'),
                null=True,
            ),
            'provision_method': entity_fields.StringField(null=True),
            'ptable': entity_fields.OneToOneField(PartitionTable, null=True),
            'puppet_classes': entity_fields.OneToManyField(
                PuppetClass,
                null=True,
            ),
            'puppet_proxy': entity_fields.OneToOneField(SmartProxy, null=True),
            'realm': entity_fields.OneToOneField(Realm, null=True),
            'root_pass': entity_fields.StringField(length=(8, 30)),
            'sp_subnet': entity_fields.OneToOneField(Subnet, null=True),
            'subnet': entity_fields.OneToOneField(Subnet, null=True),
        }
        self._meta = {'api_path': 'api/v2/hosts', 'server_modes': ('sat')}
        super(Host, self).__init__(server_config, **kwargs)

    def create_missing(self):
        """Create a bogus managed host.

        The exact set of attributes that are required varies depending on
        whether the host is managed or inherits values from a host group and
        other factors. Unfortunately, the rules for determining which
        attributes should be filled in are mildly complex, and it is hard to
        know which scenario a user is aiming for.

        Populate the values necessary to create a bogus managed host. However,
        _only_ do so if no instance attributes are present. Raise an exception
        if any instance attributes are present. Assuming that this method
        executes in full, the resultant dependency graph will look, in part,
        like this::

                 .-> medium --------.
                 |-> architecture <-V-.
            host --> operatingsystem -|
                 |-> ptable <---------'
                 |-> domain
                 '-> environment

        :raises nailgun.entities.HostCreateMissingError: If any instance
            attributes are present.

        """
        if len(self.get_values()) != 0:
            raise HostCreateMissingError(
                'Found instance attributes: {0}'.format(self.get_values())
            )
        super(Host, self).create_missing()
        # See: https://bugzilla.redhat.com/show_bug.cgi?id=1227854
        self.name = self.name.lower()
        self.mac = self._fields['mac'].gen_value()
        self.root_pass = self._fields['root_pass'].gen_value()

        # Flesh out the dependency graph shown in the docstring.
        self.domain = Domain(
            self._server_config,
            # pylint:disable=no-member
            location=[self.location],
            organization=[self.organization],
        ).create(True)
        self.environment = Environment(
            self._server_config,
            # pylint:disable=no-member
            location=[self.location],
            organization=[self.organization],
        ).create(True)
        self.architecture = Architecture(self._server_config).create(True)
        self.ptable = PartitionTable(self._server_config).create(True)
        self.operatingsystem = OperatingSystem(
            self._server_config,
            architecture=[self.architecture],
            ptable=[self.ptable],
        ).create(True)
        self.medium = Media(
            self._server_config,
            operatingsystem=[self.operatingsystem],
            # pylint:disable=no-member
            location=[self.location],
            organization=[self.organization],
        ).create(True)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'host': super(Host, self).create_payload()}

    def read(self, entity=None, attrs=None, ignore=('root_pass',)):
        """Deal with oddly named and structured data returned by the server."""
        if attrs is None:
            attrs = self.read_json()

        # POST accepts `host_parameters_attributes`, GET returns `parameters`
        attrs['host_parameters_attributes'] = attrs.pop('parameters')
        # The server returns a list of IDs for all OneToOneFields except
        # `puppet_classes`.
        attrs['puppet_classes'] = attrs.pop('puppetclasses')

        return super(Host, self).read(entity, attrs, ignore)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        FIXME: File a bug at https://bugzilla.redhat.com/ and link to it.

        """
        self.update_json(fields)
        return self.read()


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
            'name': entity_fields.StringField(required=True),
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
            'domain': entity_fields.OneToOneField(Domain, null=True),
            'host': entity_fields.OneToOneField(Host, required=True),
            'type': entity_fields.StringField(required=True),
            'ip': entity_fields.IPAddressField(required=True),
            'mac': entity_fields.MACAddressField(required=True),
            'name': entity_fields.StringField(required=True),
            'password': entity_fields.StringField(null=True),
            'provider': entity_fields.StringField(null=True),
            'subnet': entity_fields.OneToOneField(Subnet, null=True),
            'username': entity_fields.StringField(null=True),
        }
        self._meta = {
            'api_path': 'api/v2/hosts/:host_id/interfaces',
            'server_modes': ('sat'),
        }
        super(Interface, self).__init__(server_config, **kwargs)


class LifecycleEnvironment(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Lifecycle Environment entity."""

    def __init__(self, server_config=None, **kwargs):
        # NOTE: The "prior" field is unusual. See `create_missing`'s docstring.
        self._fields = {
            'description': entity_fields.StringField(),
            'name': entity_fields.StringField(required=True),
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

        A ``LifecycleEnvironment`` can be associated to another instance of a
        ``LifecycleEnvironment``. Unusually, this relationship is represented
        via the ``prior`` field, not ``prior_id``.

        """
        data = super(LifecycleEnvironment, self).create_payload()
        if 'prior_id' in data:
            data['prior'] = data.pop('prior_id')
        return data

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
            response = client.get(
                self.path('base'),
                data={
                    u'name': u'Library',
                    # pylint:disable=no-member
                    u'organization_id': self.organization.id,
                },
                **self._server_config.get_client_kwargs()
            )
            response.raise_for_status()
            results = response.json()['results']
            if len(results) != 1:
                raise APIResponseError(
                    'Could not find the "Library" lifecycle environment for '
                    'organization {0}. Search results: {1}'
                    .format(self.organization, results)  # pylint:disable=E1101
                )
            self.prior = LifecycleEnvironment(
                self._server_config,
                id=results[0]['id'],
            )


class Location(Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Location entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'compute_resource': entity_fields.OneToManyField(
                AbstractComputeResource,
                null=True,
            ),
            'config_template': entity_fields.OneToManyField(
                ConfigTemplate,
                null=True,
            ),
            'description': entity_fields.StringField(),
            'domain': entity_fields.OneToManyField(Domain, null=True),
            'environment': entity_fields.OneToManyField(
                Environment,
                null=True,
            ),
            'hostgroup': entity_fields.OneToManyField(HostGroup, null=True),
            'media': entity_fields.OneToManyField(Media, null=True),
            'name': entity_fields.StringField(required=True),
            'organization': entity_fields.OneToManyField(
                Organization,
                null=True,
            ),
            'realm': entity_fields.OneToManyField(Realm, null=True,),
            'smart_proxy': entity_fields.OneToManyField(SmartProxy, null=True),
            'subnet': entity_fields.OneToManyField(Subnet, null=True),
            'user': entity_fields.OneToManyField(User, null=True),
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

    def read(self, entity=None, attrs=None, ignore=('realm',)):
        """Work around a bug in the server's response.

        Do not try to read oany of the attributes listed in the ``ignore``
        argument. See `Bugzilla #1216234
        <https://bugzilla.redhat.com/show_bug.cgi?id=1216234>`_.

        """
        return super(Location, self).read(entity, attrs, ignore)


class Media(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Media entity.

    .. NOTE:: The ``path_`` field is named as such due to a naming conflict
        with :meth:`nailgun.entity_mixins.Entity.path`.

    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'path_': entity_fields.URLField(required=True),
            'name': entity_fields.StringField(required=True),
            'operatingsystem': entity_fields.OneToManyField(
                OperatingSystem,
                null=True,
            ),
            'organization': entity_fields.OneToManyField(
                Organization,
                null=True,
            ),
            'location': entity_fields.OneToManyField(Location, null=True),
            'os_family': entity_fields.StringField(
                choices=(
                    'AIX',
                    'Archlinux',
                    'Debian',
                    'Freebsd',
                    'Gentoo',
                    'Junos',
                    'Redhat',
                    'Solaris',
                    'Suse',
                    'Windows',
                ),
                null=True,
            ),
        }
        self._meta = {'api_path': 'api/v2/media', 'server_modes': ('sat')}
        super(Media, self).__init__(server_config, **kwargs)

    def create_missing(self):
        """Give the ``path_`` instance attribute a value if it is unset.

        By default, :meth:`nailgun.entity_fields.URLField.gen_value` does not
        return especially unique values. This is problematic, as all media must
        have a unique path.

        """
        if not hasattr(self, 'path_'):
            self.path_ = gen_url(subdomain=gen_alpha())
        return super(Media, self).create_missing()

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

    def read(self, entity=None, attrs=None, ignore=()):
        """Rename ``path`` to ``path_``."""
        if attrs is None:
            attrs = self.read_json()
        attrs['path_'] = attrs.pop('path')
        return super(Media, self).read(entity, attrs, ignore)


class Model(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Model entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'hardware_model': entity_fields.StringField(null=True),
            'info': entity_fields.StringField(null=True),
            'name': entity_fields.StringField(required=True),
            'vendor_class': entity_fields.StringField(null=True),
        }
        self._meta = {'api_path': 'api/v2/models', 'server_modes': ('sat')}
        super(Model, self).__init__(server_config, **kwargs)


class OperatingSystem(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Operating System entity.

    ``major`` is listed as a string field in the API docs, but only numeric
    values are accepted, and they may be no longer than 5 digits long. Also see
    bugzilla bug #1122261.

    The following fields are valid despite not being listed in the API docs:

    * architecture
    * medium
    * ptable

    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'architecture': entity_fields.OneToManyField(Architecture),
            'description': entity_fields.StringField(null=True),
            'family': entity_fields.StringField(
                choices=_OPERATING_SYSTEMS,
                null=True,
            ),
            'major': entity_fields.StringField(
                length=(1, 5),
                required=True,
                str_type='numeric',
            ),
            'media': entity_fields.OneToManyField(Media),
            'minor': entity_fields.StringField(
                length=(1, 16),
                null=True,
                str_type='numeric',
            ),
            'name': entity_fields.StringField(required=True),
            'ptable': entity_fields.OneToManyField(PartitionTable),
            'release_name': entity_fields.StringField(null=True),
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


class OperatingSystemParameter(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a parameter for an operating system.

    ``organization`` must be passed in when this entity is instantiated.

    :raises: ``TypeError`` if ``operatingsystem`` is not passed in.

    """

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('operatingsystem', kwargs)
        self._fields = {
            'name': entity_fields.StringField(required=True),
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

    def read(self, entity=None, attrs=None, ignore=('operatingsystem',)):
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
            'name': entity_fields.StringField(required=True),
            'realm': entity_fields.OneToManyField(Realm),
            'smart_proxy': entity_fields.OneToManyField(SmartProxy),
            'subnet': entity_fields.OneToManyField(Subnet),
            'title': entity_fields.StringField(),
            'user': entity_fields.OneToManyField(User),
        }
        self._meta = {
            'api_path': 'katello/api/v2/organizations',
            'server_modes': ('sat', 'sam'),
        }
        super(Organization, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        subscriptions/upload
            /organizations/<id>/subscriptions/upload
        subscriptions/delete_manifest
            /organizations/<id>/subscriptions/delete_manifest
        subscriptions/refresh_manifest
            /organizations/<id>/subscriptions/refresh_manifest
        sync_plans
            /organizations/<id>/sync_plans
        products
            /organizations/<id>/products
        subscriptions
            /organizations/<id>/subscriptions

        Otherwise, call ``super``.

        """
        if which in (
                'products',
                'subscriptions/delete_manifest',
                'subscriptions/refresh_manifest',
                'subscriptions/upload',
                'sync_plans',
                'subscriptions',
        ):
            return '{0}/{1}'.format(
                super(Organization, self).path(which='self'),
                which
            )
        return super(Organization, self).path(which)

    def subscriptions(self):
        """List the organization's subscriptions.

        :returns: A list of available subscriptions.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.

        """
        response = client.get(
            self.path('subscriptions'),
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)['results']

    def upload_manifest(self, path, repository_url=None, synchronous=True):
        """Helper method that uploads a subscription manifest file

        :param path: Local path of the manifest file
        :param repository_url: Optional repository URL
        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.
        :raises: ``nailgun.entity_mixins.TaskTimedOutError`` if an HTTP 202
            response is received, ``synchronous is True`` and the task
            completes with any result other than "success".

        """
        data = None
        if repository_url is not None:
            data = {u'repository_url': repository_url}
        with open(path, 'rb') as manifest:
            response = client.post(
                self.path('subscriptions/upload'),
                data,
                files={'content': manifest},
                **self._server_config.get_client_kwargs()
            )
        return _handle_response(response, self._server_config, synchronous)

    def delete_manifest(self, synchronous=True):
        """Helper method that deletes an organization's manifest

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.
        :raises: ``nailgun.entity_mixins.TaskTimedOutError`` if an HTTP 202
            response is received, ``synchronous is True`` and the task
            completes with any result other than "success".

        """
        response = client.post(
            self.path('subscriptions/delete_manifest'),
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config, synchronous)

    def refresh_manifest(self, synchronous=True):
        """Helper method that refreshes an organization's manifest

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.
        :raises: ``requests.exceptions.HTTPError`` if the response has an HTTP
            4XX or 5XX status code.
        :raises: ``ValueError`` If the response JSON could not be decoded.
        :raises: ``nailgun.entity_mixins.TaskTimedOutError`` if an HTTP 202
            response is received, ``synchronous is True`` and the task
            completes with any result other than "success".

        """
        response = client.put(
            self.path('subscriptions/refresh_manifest'),
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config, synchronous)

    def sync_plan(self, name, interval):
        """Helper for creating a sync_plan.

        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        response = client.post(
            self.path('sync_plans'),
            {
                u'interval': interval,
                u'name': name,
                u'sync_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            },
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)

    def list_rhproducts(self, per_page=None):
        """Lists all the RedHat Products after the importing of a manifest.

        :param per_page: The no.of results to be shown per page.

        """
        response = client.get(
            self.path('products'),
            data={u'per_page': per_page},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)['results']

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1230873
        <https://bugzilla.redhat.com/show_bug.cgi?id=1230873>`_.

        """
        return Organization(
            self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def read(self, entity=None, attrs=None, ignore=('realm',)):
        """Fetch as many attributes as possible for this entity.

        The server does not return any of the attributes listed in the
        ``ignore`` argument. For more information, see `Bugzilla #1230873
        <https://bugzilla.redhat.com/show_bug.cgi?id=1230873>`_.

        """
        return super(Organization, self).read(entity, attrs, ignore)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1232871
        <https://bugzilla.redhat.com/show_bug.cgi?id=1232871>`_.

        Also, beware of `Bugzilla #1230865
        <https://bugzilla.redhat.com/show_bug.cgi?id=1230865>`_:
        "Cannot use HTTP PUT to associate organization with media"

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {
            u'organization': super(Organization, self).update_payload(fields)
        }


class OSDefaultTemplate(Entity):
    """A representation of a OS Default Template entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'config_template': entity_fields.OneToOneField(
                ConfigTemplate,
                null=True,
            ),
            'operatingsystem': entity_fields.OneToOneField(
                OperatingSystem
            ),
            'template_kind': entity_fields.OneToOneField(
                TemplateKind,
                null=True
            ),
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
            'match': entity_fields.StringField(null=True),
            'smart_variable': entity_fields.OneToOneField(SmartVariable),
            'value': entity_fields.StringField(null=True),
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


class Permission(Entity, EntityReadMixin):
    """A representation of a Permission entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(required=True),
            'resource_type': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': 'api/v2/permissions',
            'server_modes': ('sat', 'sam'),
        }
        super(Permission, self).__init__(server_config, **kwargs)

    def search(self, per_page=10000):
        """Searches for permissions using the values for instance name and
        resource_type

        Example usage::

            >>> from nailgun import entities
            >>> entities.Permission(resource_type='User').search()
            [
                {'name': 'view_users', 'resource_type': 'User', 'id': 158},
                {'name': 'create_users', 'resource_type': 'User', 'id': 159},
                {'name': 'edit_users', 'resource_type': 'User', 'id': 160},
                {'name': 'destroy_users', 'resource_type': 'User', 'id': 161},
            ]
            >>> entities.Permission(name='create_users').search()
            [{'name': 'create_users', 'resource_type': 'User', 'id': 159}]

        If both ``name`` and ``resource_type`` are provided, ``name`` is
        ignored.

        :param per_page: number of results per page to return
        :returns: A list of matching permissions.

        """
        search_terms = {u'per_page': per_page}
        if hasattr(self, 'name'):
            search_terms[u'name'] = self.name  # pylint:disable=no-member
        if hasattr(self, 'resource_type'):
            # pylint:disable=no-member
            search_terms[u'resource_type'] = self.resource_type

        response = client.get(
            self.path('base'),
            data=search_terms,
            **self._server_config.get_client_kwargs()
        )
        response.raise_for_status()
        return response.json()['results']


class Ping(Entity):
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
        EntityUpdateMixin):
    """A representation of a Product entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'description': entity_fields.StringField(),
            'gpg_key': entity_fields.OneToOneField(GPGKey),
            'label': entity_fields.StringField(),
            'name': entity_fields.StringField(required=True),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True
            ),
            'repository': entity_fields.OneToManyField(Repository),
            'sync_plan': entity_fields.OneToOneField(SyncPlan, null=True),
        }
        self._meta = {
            'api_path': 'katello/api/v2/products',
            'server_modes': ('sat', 'sam'),
        }
        super(Product, self).__init__(server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        repository_sets
            /products/<product_id>/repository_sets
        repository_sets/<id>/enable
            /products/<product_id>/repository_sets/<id>/enable
        repository_sets/<id>/disable
            /products/<product_id>/repository_sets/<id>/disable

        ``super`` is called otherwise.

        """
        if which is not None and which.startswith("repository_sets"):
            return '{0}/{1}'.format(
                super(Product, self).path(which='self'),
                which,
            )
        return super(Product, self).path(which)

    def read(self, entity=None, attrs=None, ignore=()):
        """Compensate for the weird structure of returned data."""
        if attrs is None:
            attrs = self.read_json()

        # Satellite 6.0 does not include an ID in the `organization` hash.
        if (getattr(self._server_config, 'version', parse_version('6.1')) <
                parse_version('6.1')):
            org_label = attrs.pop('organization')['label']
            response = client.get(
                Organization(self._server_config).path(),
                data={'search': 'label={0}'.format(org_label)},
                **self._server_config.get_client_kwargs()
            )
            response.raise_for_status()
            results = response.json()['results']
            if len(results) != 1:
                raise APIResponseError(
                    'Could not find exactly one organization with label "{0}".'
                    ' Actual search results: {1}'.format(org_label, results)
                )
            attrs['organization'] = {'id': response.json()['results'][0]['id']}

        return super(Product, self).read(entity, attrs, ignore)

    def list_repositorysets(self, per_page=None):
        """Lists all the RepositorySets in a Product.

        :param per_page: The no.of results to be shown per page.

        """
        response = client.get(
            self.path('repository_sets'),
            data={u'per_page': per_page},
            **self._server_config.get_client_kwargs()
        )
        response.raise_for_status()
        return response.json()['results']

    def fetch_rhproduct_id(self, name, org_id):
        """Fetches the RedHat Product Id for a given Product name.

        To be used for the Products created when manifest is imported.
        RedHat Product Id could vary depending upon other custom products.
        So, we use the product name to fetch the RedHat Product Id.

        :param org_id: The Organization Id.
        :param name: The RedHat product's name who's ID is to be fetched.
        :returns: The RedHat Product Id is returned.

        """
        response = client.get(
            self.path(which='base'),
            data={u'organization_id': org_id, u'name': name},
            **self._server_config.get_client_kwargs()
        )
        response.raise_for_status()
        results = response.json()['results']
        if len(results) != 1:
            raise APIResponseError(
                "The length of the results is:", len(results))
        return results[0]['id']

    def fetch_reposet_id(self, name):
        """Fetches the RepositorySet Id for a given name.

        RedHat Products do not directly contain Repositories.
        Product first contains many RepositorySets and each
        RepositorySet contains many Repositories.
        RepositorySet Id could vary. So, we use the reposet name
        to fetch the RepositorySet Id.

        :param name: The RepositorySet's name.
        :returns: The RepositorySet's Id is returned.

        """
        response = client.get(
            self.path('repository_sets'),
            data={u'name': name},
            **self._server_config.get_client_kwargs()
        )
        response.raise_for_status()
        results = response.json()['results']
        if len(results) != 1:
            raise APIResponseError(
                "The length of the results is:", len(results))
        return results[0]['id']

    def enable_rhrepo(self, base_arch,
                      release_ver, reposet_id, synchronous=True):
        """Enables the RedHat Repository

        RedHat Repos needs to be enabled first, so that we can sync it.

        :param reposet_id: The RepositorySet Id.
        :param base_arch: The architecture type of the repo to enable.
        :param release_ver: The release version type of the repo to enable.
        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.

        """
        response = client.put(
            self.path('repository_sets/{0}/enable'.format(reposet_id)),
            {u'basearch': base_arch, u'releasever': release_ver},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config, synchronous)

    def disable_rhrepo(self, base_arch,
                       release_ver, reposet_id, synchronous=True):
        """Disables the RedHat Repository

        :param reposet_id: The RepositorySet Id.
        :param base_arch: The architecture type of the repo to disable.
        :param release_ver: The release version type of the repo to disable.
        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.

        """
        response = client.put(
            self.path('repository_sets/{0}/disable'.format(reposet_id)),
            {u'basearch': base_arch, u'releasever': release_ver},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config, synchronous)

    # pylint:disable=C0103
    def repository_sets_available_repositories(self, reposet_id):
        """Lists available repositories for the repository set

        :param reposet_id: The RepositorySet Id.
        :returns: Returns list of available repositories for the repository set

        """
        response = client.get(
            self.path(
                'repository_sets/{0}/available_repositories'
                .format(reposet_id)
            ),
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)['results']


class PartitionTable(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Partition Table entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'layout': entity_fields.StringField(required=True),
            'name': entity_fields.StringField(required=True),
            'os_family': entity_fields.StringField(
                choices=_OPERATING_SYSTEMS,
                null=True,
            ),
        }
        self._meta = {'api_path': 'api/v2/ptables', 'server_modes': ('sat')}
        super(PartitionTable, self).__init__(server_config, **kwargs)


class PuppetClass(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Puppet Class entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': 'api/v2/puppetclasses',
            'server_modes': ('sat'),
        }
        super(PuppetClass, self).__init__(server_config, **kwargs)


class PuppetModule(Entity, EntityReadMixin):
    """A representation of a Puppet Module entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'author': entity_fields.StringField(),
            'checksums': entity_fields.ListField(),
            'dependencies': entity_fields.ListField(),
            'description': entity_fields.StringField(),
            'license': entity_fields.StringField(),
            'name': entity_fields.StringField(),
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
            'name': entity_fields.StringField(required=True),
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


class Report(Entity):
    """A representation of a Report entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'host': entity_fields.StringField(required=True),
            'logs': entity_fields.ListField(null=True),
            'reported_at': entity_fields.DateTimeField(required=True),
        }
        self._meta = {'api_path': 'api/v2/reports', 'server_modes': ('sat')}
        super(Report, self).__init__(server_config, **kwargs)


class Repository(
        Entity,
        EntityCreateMixin,
        EntityDeleteMixin,
        EntityReadMixin,
        EntityUpdateMixin):
    """A representation of a Repository entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'checksum_type': entity_fields.StringField(
                choices=('sha1', 'sha256'),
            ),
            'content_type': entity_fields.StringField(
                choices=('puppet', 'yum', 'file', 'docker'),
                default='yum',
                required=True,
            ),
            # Just setting `str_type='alpha'` will fail with this error:
            # {"docker_upstream_name":["must be a valid docker name"]}}
            'docker_upstream_name': entity_fields.StringField(
                default='busybox'
            ),
            'gpg_key': entity_fields.OneToOneField(GPGKey),
            'label': entity_fields.StringField(),
            'name': entity_fields.StringField(required=True),
            'product': entity_fields.OneToOneField(Product, required=True),
            'unprotected': entity_fields.BooleanField(),
            'url': entity_fields.URLField(
                default=_FAKE_YUM_REPO,
                required=True,
            ),
        }
        if (getattr(server_config, 'version', parse_version('6.1')) <
                parse_version('6.1')):
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

    def sync(self, synchronous=True):
        """Helper for syncing an existing repository.

        :param synchronous: What should happen if the server returns an
            HTTP 202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return JSON response otherwise.
        :returns: Returns information of the async task if an HTTP
            202 response was received and synchronus set to ``True``.
            Return JSON response otherwise.

        """
        response = client.post(
            self.path('sync'),
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config, synchronous)

    def fetch_repoid(self, org_id, name):
        """Fetch the repository Id.

        This is required for RedHat Repositories, as products, reposets
        and repositories get automatically populated upon the manifest import.

        :param org_id: The org Id for which repository listing is required.
        :param name: The repository name who's ID has to be searched.
        :return: Returns the repository ID.
        :raises: ``APIResponseError`` If the API does not return any results.

        """
        for _ in range(5):
            response = client.get(
                self.path(which=None),
                data={u'organization_id': org_id, u'name': name},
                **self._server_config.get_client_kwargs()
            )
            response.raise_for_status()
            results = response.json()['results']
            if len(results) == 0:
                sleep(5)
            else:
                break
        if len(results) != 1:
            raise APIResponseError(
                'Found {0} repositories named {1} in organization {2}: {3} '
                .format(len(results), name, org_id, results)
            )
        return results[0]['id']

    def upload_content(self, handle):
        """Upload a file to the current repository.

        :param handle: A file object, such as the one returned by
            ``open('path', 'rb')``.
        :returns: The JSON-decoded response.
        :raises nailgun.entities.APIResponseError: If the response has a status
            other than "success".

        """
        response = client.post(
            self.path('upload_content'),
            files={'content': handle},
            **self._server_config.get_client_kwargs()
        )
        response.raise_for_status()
        response_json = response.json()
        if response_json['status'] != 'success':
            raise APIResponseError(
                'Received error when uploading file {0} to repository {1}: {2}'
                .format(handle, self.id, response_json)  # pylint:disable=E1101
            )
        return response_json


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

    def read(self, entity=None, attrs=None, ignore=('rhev_engine_host',)):
        """Normalize the data returned by the server.

        The server's JSON response is in this form::

            {
                "organizations": […],
                "lifecycle_environments": […],
                "discovered_hosts": […],
                "deployment": {…},
            }

        The inner "deployment" dict contains information about this entity. The
        response does not contain any of the attributes listed in the
        ``ignore`` argument.

        """
        if attrs is None:
            attrs = self.read_json()
        attrs = attrs['deployment']
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

    def add_hypervisors(self, hypervisor_ids):
        """Helper for creating an RHCI deployment.

        :param hypervisor_ids: A list of RHEV hypervisor ids to be added to the
            deployment.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        response = client.put(
            self.path(),
            {'discovered_host_ids': hypervisor_ids},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)

    def deploy(self, params):
        """Kickoff the RHCI deployment.

        :param params: Parameters that are encoded to JSON and passed in
            with the request. See the API documentation page for a list of
            parameters and their descriptions.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        response = client.put(
            self.path('deploy'),
            params,
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config)


class RoleLDAPGroups(Entity):
    """A representation of a Role LDAP Groups entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(required=True),
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


class SmartProxy(Entity, EntityReadMixin):
    """A representation of a Smart Proxy entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(required=True),
            'url': entity_fields.URLField(required=True),
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

    def refresh(self, synchronous=True):
        """Refresh Capsule features

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's reponse otherwise.
        :returns: The server's JSON-decoded response.

        """
        response = client.put(
            self.path('refresh'),
            {},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config, synchronous)


class SmartVariable(Entity):
    """A representation of a Smart Variable entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'default_value': entity_fields.StringField(null=True),
            'description': entity_fields.StringField(null=True),
            'override_value_order': entity_fields.StringField(null=True),
            'puppetclass': entity_fields.OneToOneField(PuppetClass, null=True),
            'validator_rule': entity_fields.StringField(null=True),
            'validator_type': entity_fields.StringField(null=True),
            'variable': entity_fields.StringField(required=True),
            'variable_type': entity_fields.StringField(null=True),
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
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Subnet entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'dns_primary': entity_fields.IPAddressField(null=True),
            'dns_secondary': entity_fields.IPAddressField(null=True),
            'domain': entity_fields.OneToManyField(Domain, null=True),
            'from': entity_fields.IPAddressField(null=True),
            'gateway': entity_fields.StringField(null=True),
            'mask': entity_fields.NetmaskField(required=True),
            'name': entity_fields.StringField(required=True),
            'network': entity_fields.IPAddressField(required=True),
            'to': entity_fields.IPAddressField(null=True),
            'vlanid': entity_fields.StringField(null=True),
        }
        if (getattr(server_config, 'version', parse_version('6.1')) >=
                parse_version('6.1')):
            self._fields.update({
                'boot_mode': entity_fields.StringField(
                    choices=('Static', 'DHCP',),
                    default=u'DHCP',
                    null=True,
                ),
                'dhcp': entity_fields.OneToOneField(SmartProxy, null=True),
                # When reading a subnet, no discovery information is
                # returned by the server. See Bugzilla #1217146.
                'discovery': entity_fields.OneToOneField(
                    SmartProxy,
                    null=True,
                ),
                'dns': entity_fields.OneToOneField(SmartProxy, null=True),
                'ipam': entity_fields.StringField(
                    choices=(u'DHCP', u'Internal DB'),
                    default=u'DHCP',
                    null=True,
                ),
                'location': entity_fields.OneToManyField(Location, null=True),
                'organization': entity_fields.OneToManyField(
                    Organization,
                    null=True,
                ),
                'tftp': entity_fields.OneToOneField(SmartProxy, null=True),
            })
        self._meta = {'api_path': 'api/v2/subnets', 'server_modes': ('sat')}
        super(Subnet, self).__init__(server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {u'subnet': super(Subnet, self).create_payload()}

    def read(self, entity=None, attrs=None, ignore=('discovery',)):
        """Fetch as many attributes as possible for this entity.

        The server does not return any of the attributes listed in the
        ``ignore`` argument. For more information, see `Bugzilla #1217146
        <https://bugzilla.redhat.com/show_bug.cgi?id=1217146>`_.

        """
        return super(Subnet, self).read(entity, attrs, ignore)


class Subscription(Entity):
    """A representation of a Subscription entity."""

    def __init__(self, server_config=None, **kwargs):
        # NOTE: When making an HTTP POST call, `pool_uuid` must be renamed to
        # `id`. This logic can be packed in to create_payload().
        self._fields = {
            'activation_key': entity_fields.OneToOneField(ActivationKey),
            'pool_uuid': entity_fields.StringField(),
            'quantity': entity_fields.IntegerField(),
            'subscriptions': entity_fields.OneToManyField(Subscription),
            'system': entity_fields.OneToOneField(System),
        }
        self._meta = {
            'api_path': 'katello/api/v2/subscriptions/:id',
            'server_modes': ('sat', 'sam'),
        }
        super(Subscription, self).__init__(server_config, **kwargs)


class SyncPlan(
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
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
            'name': entity_fields.StringField(required=True),
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

    def read(self, entity=None, attrs=None, ignore=('organization',)):
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

    def add_products(self, product_ids, synchronous=True):
        """Add products to this sync plan.

        .. NOTE:: The ``synchronous`` argument has no effect in certain
            versions of Satellite. See `Bugzilla #1199150
            <https://bugzilla.redhat.com/show_bug.cgi?id=1199150>`_.

        :param product_ids: A list of product IDs to add to this sync plan.
        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's reponse otherwise.
        :returns: The server's JSON-decoded response.

        """
        response = client.put(
            self.path('add_products'),
            {'product_ids': product_ids},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config, synchronous)

    def remove_products(self, product_ids, synchronous=True):
        """Remove products from this sync plan.

        .. NOTE:: The ``synchronous`` argument has no effect in certain
            versions of Satellite. See `Bugzilla #1199150
            <https://bugzilla.redhat.com/show_bug.cgi?id=1199150>`_.

        :param product_ids: A list of product IDs to remove from this syn plan.
        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's reponse otherwise.
        :returns: The server's JSON-decoded response.

        """
        response = client.put(
            self.path('remove_products'),
            {'product_ids': product_ids},
            **self._server_config.get_client_kwargs()
        )
        return _handle_response(response, self._server_config, synchronous)


class SystemPackage(Entity):
    """A representation of a System Package entity."""

    def __init__(self, server_config=None, **kwargs):
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
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a System entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'content_view': entity_fields.OneToOneField(ContentView),
            'description': entity_fields.StringField(),
            'environment': entity_fields.OneToOneField(Environment),
            'facts': entity_fields.DictField(
                default={u'uname.machine': u'unknown'},
                null=True,
                required=True,
            ),
            'host_collection': entity_fields.OneToManyField(HostCollection),
            'installed_products': entity_fields.ListField(null=True),
            'last_checkin': entity_fields.DateTimeField(),
            'location': entity_fields.StringField(),
            'name': entity_fields.StringField(required=True),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'release_ver': entity_fields.StringField(),
            'service_level': entity_fields.StringField(null=True),
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

        """
        if hasattr(self, 'uuid') and (which is None or which == 'self'):
            return '{0}/{1}'.format(
                super(System, self).path(which='base'),
                self.uuid  # pylint:disable=no-member
            )
        return super(System, self).path(which)

    def read(
            self,
            entity=None,
            attrs=None,
            ignore=('facts', 'organization', 'type')):
        """Fetch as many attributes as possible for this entity.

        The server does not return any of the attributes listed in the
        ``ignore`` argument. For more information, see `Bugzilla #1202917
        <https://bugzilla.redhat.com/show_bug.cgi?id=1202917>`_.

        """
        if attrs is None:
            attrs = self.read_json()
        attrs['last_checkin'] = attrs.pop('checkin_time')
        attrs['host_collections'] = attrs.pop('hostCollections')
        attrs['installed_products'] = attrs.pop('installedProducts')
        return super(System, self).read(entity, attrs, ignore)


class TemplateCombination(Entity):
    """A representation of a Template Combination entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'config_template': entity_fields.OneToOneField(
                ConfigTemplate,
                required=True,
            ),
            'environment': entity_fields.OneToOneField(Environment, null=True),
            'hostgroup': entity_fields.OneToOneField(HostGroup, null=True),
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
        Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a User Group entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'admin': entity_fields.BooleanField(),
            'name': entity_fields.StringField(required=True),
            'role': entity_fields.OneToManyField(Role),
            'user': entity_fields.OneToManyField(User, required=True),
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

    def read(self, entity=None, attrs=None, ignore=()):
        """Work around `Redmine #9594`_.

        An HTTP GET request to ``path('self')`` does not return the ``admin``
        attribute, even though it should. Also see `Bugzilla #1197871`_.

        .. _Redmine #9594: http://projects.theforeman.org/issues/9594
        .. _Bugzilla #1197871:
            https://bugzilla.redhat.com/show_bug.cgi?id=1197871

        """
        if attrs is None:
            attrs = self.read_json()
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
        EntityUpdateMixin):
    """A representation of a User entity.

    The LDAP authentication source with an ID of 1 is internal. It is nearly
    guaranteed to exist and be functioning. Thus, ``auth_source`` is set to "1"
    by default for a practical reason: it is much easier to use internal
    authentication than to spawn LDAP authentication servers for each new user.

    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'admin': entity_fields.BooleanField(null=True),
            'auth_source': entity_fields.OneToOneField(
                AuthSourceLDAP,
                default=AuthSourceLDAP(server_config, id=1),
                required=True,
            ),
            'default_location': entity_fields.OneToOneField(
                Location,
                null=True,
            ),
            'default_organization': entity_fields.OneToOneField(
                Organization,
                null=True,
            ),
            'firstname': entity_fields.StringField(null=True, length=(1, 50)),
            'lastname': entity_fields.StringField(null=True, length=(1, 50)),
            'location': entity_fields.OneToManyField(Location, null=True),
            'login': entity_fields.StringField(
                length=(1, 100),
                required=True,
                str_type=('alpha', 'alphanumeric', 'cjk', 'latin1', 'utf8'),
            ),
            'mail': entity_fields.EmailField(required=True),
            'organization': entity_fields.OneToManyField(
                Organization,
                null=True,
            ),
            'password': entity_fields.StringField(required=True),
            'role': entity_fields.OneToManyField(Role, null=True),
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

    def read(self, entity=None, attrs=None, ignore=('password',)):
        """Do not read any attributes listed in the ``ignore`` argument."""
        return super(User, self).read(entity, attrs, ignore)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {u'user': super(User, self).update_payload(fields)}

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        FIXME: File a bug at https://bugzilla.redhat.com/ and link to it.

        """
        self.update_json(fields)
        return self.read()
