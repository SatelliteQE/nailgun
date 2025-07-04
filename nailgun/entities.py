"""All entities which Foreman exposes.

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
from functools import lru_cache
import hashlib
from http.client import ACCEPTED, NO_CONTENT
import os.path
from urllib.parse import urljoin

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
    _get_entity_ids,
    _payload,
    _poll_task,
    to_json_serializable,  # noqa: F401
)

# The size of this file is a direct reflection of the size of Satellite's API.
# This file's size has already been significantly cut down through the use of
# mixins and fields, and cutting the file down in size further would simply
# obfuscate the design of the entities. It might be possible to place entity
# definitions in separate modules, though.

# NailGun aims to be like a traditional database ORM and allow uses of the dot
# operator such as these:
#
#     product = Product(server_config=server_config, id=5).read()
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
    'Coreos',
    'Debian',
    'Fcos',
    'Freebsd',
    'Gentoo',
    'Junos',
    'NXOS',
    'Rancheros',
    'Redhat',
    'Rhcos',
    'Solaris',
    'Suse',
    'VRP',
    'Windows',
    'Xenserver',
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
        return ForemanTask(server_config=server_config, id=response.json()['id']).poll(
            timeout=timeout
        )
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
    example, in :class:`nailgun.entities.HostPackage`:

    >>> def __init__(self, server_config=None, **kwargs):
    >>>     _check_for_value('host', kwargs)
    >>>     # …
    >>>     self._meta = {
    >>>         'api_path': f'{self.host.path()}/packages',
    >>>     }

    :param field_name: A string. A key with this name must be present in
        ``field_values``.
    :param field_values: A dict containing field-name to field-value mappings.
    :raises: ``TypeError`` if ``field_name`` is not present in
        ``field_values``.
    :returns: Nothing.
    """
    if field_name not in field_values:
        raise TypeError(f'A value must be provided for the "{field_name}" field.')


def _get_org(server_config, label):
    """Find an :class:`nailgun.entities.Organization` object.

    :param nailgun.config.ServerConfig server_config: The server that should be
        searched.
    :param label: A string. The label of the organization to find.
    :raises APIResponseError: If exactly one organization is not found.
    :returns: An :class:`nailgun.entities.Organization` object.
    """
    organizations = Organization(server_config).search(query={'search': f'label={label}'})
    if len(organizations) != 1:
        raise APIResponseError(
            f'Could not find exactly one organization with label "{label}". '
            f'Actual search results: {organizations}'
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


@lru_cache
def _feature_list(server_config, smart_proxy_id=1):
    """Get list of features enabled on capsule."""
    smart_proxy = SmartProxy(server_config=server_config, id=smart_proxy_id).read_json()
    return [feature['name'] for feature in smart_proxy['features']]


class ActivationKey(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
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
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'purpose_usage': entity_fields.StringField(),
            'purpose_role': entity_fields.StringField(),
            'release_version': entity_fields.StringField(),
            'service_level': entity_fields.StringField(),
            'unlimited_hosts': entity_fields.BooleanField(),
        }
        self._meta = {
            'api_path': 'katello/api/v2/activation_keys',
        }
        super().__init__(server_config=server_config, **kwargs)

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
            'subscriptions',
        ):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def update_payload(self, fields=None):
        """Include organization_id in all payloads."""
        payload = super().update_payload(fields)
        # organization is required for the AK update call
        payload['organization_id'] = self.organization.id
        return payload

    def add_host_collection(self, synchronous=True, timeout=None, **kwargs):
        """Associate host collection with activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('host_collections'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def add_subscriptions(self, synchronous=True, timeout=None, **kwargs):
        """Add subscriptions to activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('add_subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def copy(self, synchronous=True, timeout=None, **kwargs):
        """Copy provided activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        if 'data' in kwargs and 'id' not in kwargs['data']:
            kwargs['data']['id'] = self.id
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('copy'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def remove_subscriptions(self, synchronous=True, timeout=None, **kwargs):
        """Remove subscriptions from an activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('remove_subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def subscriptions(self, synchronous=True, timeout=None, **kwargs):
        """Retrieve subscriptions on an activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def content_override(self, synchronous=True, timeout=None, **kwargs):
        """Override the content of an activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('content_override'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def product_content(self, synchronous=True, timeout=None, **kwargs):
        """Show content available for activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('product_content'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def remove_host_collection(self, synchronous=True, timeout=None, **kwargs):
        """Disassociate host collection from the activation key.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('host_collections'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class AlternateContentSource(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of an Alternate Content Source entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'content_type': entity_fields.StringField(choices=('file', 'yum'), default='yum'),
            'alternate_content_source_type': entity_fields.StringField(
                choices=('custom', 'simplified', 'rhui'), default='custom'
            ),
            'description': entity_fields.StringField(),
            'base_url': entity_fields.URLField(),
            'subpaths': entity_fields.ListField(),
            'smart_proxy_ids': entity_fields.ListField(),
            'smart_proxy_names': entity_fields.ListField(),
            'smart_proxies': entity_fields.OneToManyField(SmartProxy),
            'upstream_username': entity_fields.StringField(),
            'upstream_password': entity_fields.StringField(),
            'ssl_ca_cert_id': entity_fields.IntegerField(),
            'ssl_ca_cert': entity_fields.OneToOneField(ContentCredential),
            'ssl_client_cert_id': entity_fields.IntegerField(),
            'ssl_client_cert': entity_fields.OneToOneField(ContentCredential),
            'ssl_client_key_id': entity_fields.IntegerField(),
            'ssl_client_key': entity_fields.OneToOneField(ContentCredential),
            'verify_ssl': entity_fields.BooleanField(),
            'use_http_proxies': entity_fields.BooleanField(),
            'product_ids': entity_fields.ListField(),
            'products': entity_fields.ListField(),
            'last_refresh': entity_fields.DictField(),
        }
        self._meta = {
            'api_path': 'katello/api/alternate_content_sources',
        }
        super().__init__(server_config=server_config, **kwargs)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Handle read values dependencies."""
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()

        # fields depending on the ACS type
        if 'base_url' not in attrs:
            ignore.add('base_url')
        if 'subpaths' not in attrs:
            ignore.add('subpaths')
        if 'products' not in attrs:
            ignore.add('products')
        if 'verify_ssl' not in attrs:
            ignore.add('verify_ssl')
        if 'ssl_ca_cert' not in attrs:
            ignore.add('ssl_ca_cert')
        if 'ssl_client_cert' not in attrs:
            ignore.add('ssl_client_cert')
        if 'ssl_client_key' not in attrs:
            ignore.add('ssl_client_key')
        if 'upstream_username' not in attrs:
            ignore.add('upstream_username')

        # returned in non-id fields
        ignore.add('smart_proxy_ids')
        ignore.add('smart_proxy_names')
        ignore.add('product_ids')
        ignore.add('ssl_ca_cert_id')
        ignore.add('ssl_client_cert_id')
        ignore.add('ssl_client_key_id')

        # always missing
        ignore.add('upstream_password')

        return super().read(entity, attrs, ignore, params)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        refresh
            /katello/api/alternate_content_sources/:id/refresh
        bulk_refresh
            /katello/api/alternate_content_sources/bulk/refresh
        bulk_refresh_all
            /katello/api/alternate_content_sources/bulk/refresh_all
        bulk_destroy
            /katello/api/alternate_content_sources/bulk/destroy
        """
        if which == "refresh":
            return f'{super().path(which="self")}/{which}'
        elif which in (
            'bulk/refresh',
            'bulk/refresh_all',
            'bulk/destroy',
        ):
            return f'{super().path(which="base")}/{which}'
        return super().path(which)

    def refresh(self, synchronous=True, timeout=None, **kwargs):
        """Refresh an ACS.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('refresh'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def bulk_refresh_all(self, synchronous=True, timeout=None, **kwargs):
        """Refresh all ACSes present.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('bulk/refresh_all'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def bulk_refresh(self, synchronous=True, timeout=None, **kwargs):
        """Refresh the set of ACSes.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('bulk/refresh'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def bulk_destroy(self, synchronous=True, timeout=None, **kwargs):
        """Destroy the set of ACSes.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('bulk/destroy'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class Architecture(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Architecture entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'operatingsystem': entity_fields.OneToManyField(OperatingSystem),
        }
        self._meta = {
            'api_path': 'api/v2/architectures',
        }
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'architecture': super().create_payload()}

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1234964
        <https://bugzilla.redhat.com/show_bug.cgi?id=1234964>`_.

        """
        self.update_json(fields)
        return self.read()


class ArfReport(Entity, EntityDeleteMixin, EntityReadMixin, EntitySearchMixin):
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
            'policy': entity_fields.OneToOneField(CompliancePolicies),
        }
        self._meta = {
            'api_path': 'api/compliance/arf_reports',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        download_html
            /api/compliance/arf_reports/:id/download_html

        Otherwise, call ``super``.

        """
        if which in ("download_html",):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def download_html(self, synchronous=True, timeout=None, **kwargs):
        """Download ARF report in HTML.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('download_html'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


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
        }
        super().__init__(server_config=server_config, **kwargs)


class AuthSourceLDAP(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntityUpdateMixin,
    EntitySearchMixin,
):
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
                required=True, str_type='alpha', length=(1, 60), unique=True
            ),
            'onthefly_register': entity_fields.BooleanField(),
            'port': entity_fields.IntegerField(),
            'server_type': entity_fields.StringField(
                choices=('active_directory', 'free_ipa', 'posix')
            ),
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
        }
        super().__init__(server_config=server_config, **kwargs)

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
        super().create_missing()
        if getattr(self, 'onthefly_register', False) is True:
            for field in (
                'account_password',
                'attr_firstname',
                'attr_lastname',
                'attr_login',
                'attr_mail',
            ):
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
        return super().read(entity, attrs, ignore, params)


class Bookmark(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Bookmark entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'controller': entity_fields.StringField(required=True),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'public': entity_fields.BooleanField(),
            'query': entity_fields.StringField(required=True),
        }
        self._meta = {'api_path': 'api/v2/bookmarks'}
        super().__init__(server_config=server_config, **kwargs)


class Capsule(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Capsule entity."""

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
            'hosts_count': entity_fields.IntegerField(),
            'download_policy': entity_fields.StringField(),
            'supported_pulp_types': entity_fields.StringField(),
            'lifecycle_environments': entity_fields.StringField(),
        }
        self._meta = {
            'api_path': 'katello/api/capsules',
        }
        super().__init__(server_config=server_config, **kwargs)

    def content_add_lifecycle_environment(self, synchronous=True, timeout=None, **kwargs):
        """Associate lifecycle environment with capsule.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('content_lifecycle_environments'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def content_delete_lifecycle_environment(self, synchronous=True, timeout=None, **kwargs):
        """Disassociate lifecycle environment from capsule.

        Here is an example of how to use this method::
            capsule.content_delete_lifecycle_environment(data={'environment_id': lce.id})

        Constructs path:
            /katello/api/capsules/:capsule_id/content/lifecycle_environments/:id

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        path = (
            f'{self.path("content_lifecycle_environments")}/{kwargs["data"].pop("environment_id")}'
        )
        response = client.delete(path, **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def content_lifecycle_environments(self, synchronous=True, timeout=None, **kwargs):
        """Get all lifecycle environments associated with a capsule.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('content_lifecycle_environments'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def content_sync(self, synchronous=True, timeout=None, **kwargs):
        """Sync content on a capsule.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('content_sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def content_get_sync(self, synchronous=True, timeout=None, **kwargs):
        """Get content sync status on capsule.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('content_sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def content_counts(self, synchronous=True, timeout=None, **kwargs):
        """List content counts for the capsule.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('content_counts'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def content_update_counts(self, synchronous=True, timeout=None, **kwargs):
        """Update content counts for the capsule.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('content_update_counts'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def content_reclaim_space(self, synchronous=True, timeout=None, **kwargs):
        """Reclaim space for all on_demand repos synced on the Capsule.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('content_reclaim_space'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def content_verify_checksum(self, synchronous=True, timeout=None, **kwargs):
        """Check for missing or corrupted artifacts, and attempt to redownload them.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('content_verify_checksum'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        content_lifecycle_environments
            /capsules/<id>/content/lifecycle_environments
        content_sync
            /capsules/<id>/content/sync
        content_counts
            /capsules/<id>/content/counts
        content_update_counts
            /capsules/<id>/content/update_counts
        content_reclaim_space
            /capsules/<id>/content/reclaim_space
        content_verify_checksum
            /capsules/<id>/content/verify_checksum

        ``super`` is called otherwise.

        """
        if which and which.startswith("content_"):
            return f'{super().path(which="self")}/content/{which.split("content_")[1]}'
        return super().path(which)


class CommonParameter(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Common Parameter entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(required=True, unique=True),
            'value': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': 'api/v2/common_parameters',
        }
        super().__init__(server_config=server_config, **kwargs)


class ComputeAttribute(
    Entity, EntityCreateMixin, EntityReadMixin, EntitySearchMixin, EntityUpdateMixin
):
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
        }
        super().__init__(server_config=server_config, **kwargs)


class ComputeProfile(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Compute Profile entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'compute_attribute': entity_fields.OneToManyField(ComputeAttribute),
        }
        self._meta = {
            'api_path': 'api/v2/compute_profiles',
        }
        super().__init__(server_config=server_config, **kwargs)


class AbstractComputeResource(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
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
                unique=True,
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'provider': entity_fields.StringField(
                choices=(
                    'AzureRm',
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
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        available_images
            /api/compute_resources/:id/available_images
        available_flavors
            /api/compute_resources/:id/available_flavors
        available_zones
            /api/compute_resources/:id/available_zones
        available_networks
            /api/compute_resources/:id/available_networks
        images
            /api/compute_resources/:id/images
        associate
            /api/compute_resources/:id/associate

        Otherwise, call ``super``.

        """
        if which in (
            'available_images',
            'available_zones',
            'available_flavors',
            'available_networks',
            'images',
            'associate',
        ):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'compute_resource': super().create_payload()}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'compute_resource': super().update_payload(fields)}

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1250922
        <https://bugzilla.redhat.com/show_bug.cgi?id=1250922>`_.

        """
        self.update_json(fields)
        return self.read()

    def available_images(self, synchronous=True, timeout=None, **kwargs):
        """Get images available to be added to the compute resource.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('available_images'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def available_zones(self, synchronous=True, timeout=None, **kwargs):
        """Get images available to be added to the compute resource.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('available_zones'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def available_flavors(self, synchronous=True, timeout=None, **kwargs):
        """Get flavors available to be added to the compute resource.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('available_zones'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def available_networks(self, synchronous=True, timeout=None, **kwargs):
        """Get networks available to be selected for host provisioning.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('available_networks'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def images(self, synchronous=True, timeout=None, **kwargs):
        """Get images created in a compute resource.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('images'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def associate(self, synchronous=True, timeout=None, **kwargs):
        """Associate the host.

        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('associate'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class DiscoveredHost(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Foreman Discovered Host entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'ip': entity_fields.IPAddressField(required=True),
            'mac': entity_fields.MACAddressField(required=True),
            'hostgroup': entity_fields.OneToOneField(HostGroup),
            'root_pass': entity_fields.StringField(),
            'build': entity_fields.BooleanField(default=False),
            'organization': entity_fields.OneToOneField(Organization),
            'location': entity_fields.OneToOneField(Location),
        }
        self._meta = {
            'api_path': '/api/v2/discovered_hosts',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        facts
            /discovered_hosts/facts
        refresh_facts
            /discovered_hosts/<id>/refresh_facts
        reboot
            /discovered_hosts/<id>/reboot

        ``super`` is called otherwise.

        """
        if which in (
            'auto_provision',
            'auto_provision_all',
            'facts',
            'refresh_facts',
            'reboot',
            'reboot_all',
        ):
            prefix = 'base' if which in ['auto_provision_all', 'facts', 'reboot_all'] else 'self'
            return f'{super().path(which=prefix)}/{which}'
        return super().path(which)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'discovered_host': super().create_payload()}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'discovered_host': super().update_payload(fields)}

    def facts(self, synchronous=True, timeout=None, **kwargs):
        """Update facts for discovered host, and create the host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('facts'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def refresh_facts(self, synchronous=True, timeout=None, **kwargs):
        """Refresh facts for discovered host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('refresh_facts'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Make sure, everything except `id` and `name` are in the ignore list for read."""
        if ignore is None:
            ignore = set()
        ignore.add('ip')
        ignore.add('mac')
        ignore.add('root_pass')
        ignore.add('hostgroup')
        ignore.add('build')
        ignore.add('organization')
        ignore.add('location')
        return super().read(entity, attrs, ignore, params)

    def reboot(self, synchronous=True, timeout=None, **kwargs):
        """Reboot the discovered host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('reboot'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def reboot_all(self, synchronous=True, timeout=None, **kwargs):
        """Reboot all discovered hosts.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('reboot_all'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def auto_provision(self, synchronous=True, timeout=None, **kwargs):
        """Auto-provision the discovered host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('auto_provision'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def auto_provision_all(self, synchronous=True, timeout=None, **kwargs):
        """Auto-provision of all discovered hosts.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('auto_provision_all'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class DiscoveryRule(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
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
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'priority': entity_fields.IntegerField(),
            'search_': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': '/api/v2/discovery_rules',
        }
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        In addition, rename the ``search_`` field to ``search``.

        """
        payload = super().create_payload()
        if 'search_' in payload:
            payload['search'] = payload.pop('search_')
        return {'discovery_rule': payload}

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1381129
        <https://bugzilla.redhat.com/show_bug.cgi?id=1381129>`_.

        """
        return type(self)(
            server_config=self._server_config,
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
                server_config=self._server_config,
                id=attrs['id'],
            ).update_json([])[attr]
        return super().read(entity, attrs, ignore, params)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1381129
        <https://bugzilla.redhat.com/show_bug.cgi?id=1381129>`_.

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super().update_payload(fields)
        if 'search_' in payload:
            payload['search'] = payload.pop('search_')
        return {'discovery_rule': payload}


class ExternalUserGroup(
    Entity, EntityCreateMixin, EntityDeleteMixin, EntityUpdateMixin, EntityReadMixin
):
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
                parent=True,
            ),
            'auth_source': entity_fields.OneToOneField(AuthSourceLDAP, required=True),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            'api_path': f'{self.usergroup.path()}/external_usergroups',
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Ignore usergroup from read and alter auth_source_ldap with auth_source."""
        entity = entity or self.entity_with_parent()
        if ignore is None:
            ignore = set()
        ignore.add('usergroup')
        if attrs is None:
            attrs = self.read_json()
        attrs['auth_source'] = attrs.pop('auth_source_ldap')
        return super().read(entity, attrs, ignore, params)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        refresh
            /api/usergroups/:usergroup_id/external_usergroups/:id/refresh
        """
        if which == "refresh":
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def refresh(self, synchronous=True, timeout=None, **kwargs):
        """Refresh external usergroup.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.

        :param kwargs: Arguments to pass to requests.

        :returns: The server's response, with all JSON decoded.

        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('refresh'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class KatelloStatus(Entity, EntityReadMixin):
    """A representation of a Status entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'version': entity_fields.StringField(),
            'timeUTC': entity_fields.DateTimeField(),
        }
        self._meta = {
            'api_path': 'katello/api/v2/status',
            'read_type': 'base',
        }
        super().__init__(server_config=server_config, **kwargs)


class LibvirtComputeResource(AbstractComputeResource):
    """A representation of a Libvirt Compute Resource entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'display_type': entity_fields.StringField(
                choices=('vnc', 'spice'),
                required=True,
            ),
            'set_console_password': entity_fields.BooleanField(),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._fields['provider'].default = 'Libvirt'
        self._fields['provider'].required = True
        self._fields['provider_friendly_name'].default = 'Libvirt'


class OVirtComputeResource(AbstractComputeResource):
    """A representation for compute resources with Ovirt provider."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'password': entity_fields.StringField(),
            'user': entity_fields.StringField(),
            'use_v4': entity_fields.BooleanField(),
            'datacenter': entity_fields.StringField(),
            'ovirt_quota': entity_fields.StringField(),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._fields['provider'].default = 'Ovirt'
        self._fields['provider'].required = True
        self._fields['provider_friendly_name'].default = 'OVirt'

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Make sure, ``password`` is in the ignore list for read."""
        if ignore is None:
            ignore = set()
        ignore.add('password')
        return super().read(entity, attrs, ignore, params)


class VMWareComputeResource(AbstractComputeResource):
    """A representation for compute resources with Vmware provider."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'datacenter': entity_fields.StringField(),
            'password': entity_fields.StringField(),
            'set_console_password': entity_fields.BooleanField(),
            'user': entity_fields.StringField(),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._fields['provider'].default = 'Vmware'
        self._fields['provider'].required = True
        self._fields['provider_friendly_name'].default = 'VMware'

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Make sure, ``password`` is in the ignore list for read."""
        if ignore is None:
            ignore = set()
        ignore.add('password')
        return super().read(entity, attrs, ignore, params)


class GCEComputeResource(AbstractComputeResource):
    """A representation of a Google Compute Resource entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'key_path': entity_fields.StringField(required=True),
            'zone': entity_fields.StringField(),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._fields['provider'].default = 'GCE'
        self._fields['provider'].required = True
        self._fields['provider_friendly_name'].default = 'GCE'

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Make sure, ``key_path`` is in the ignore list for read."""
        if ignore is None:
            ignore = set()
        ignore.add('key_path')
        return super().read(entity, attrs, ignore, params)


class AzureRMComputeResource(AbstractComputeResource):
    """A representation for compute resources with AzureRM provider."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'tenant': entity_fields.StringField(required=True),
            'app_ident': entity_fields.StringField(required=True),
            'sub_id': entity_fields.StringField(required=True),
            'secret_key': entity_fields.StringField(required=True),
            'region': entity_fields.StringField(required=True),
        }
        super().__init__(server_config=server_config, **kwargs)
        # Remove 'url' field as not required for AzureRM
        del self._fields['url']
        self._fields['provider'].default = 'AzureRm'
        self._fields['provider'].required = True
        self._fields['provider_friendly_name'].default = 'Azure Resource Manager'

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Make sure, ``secret_key`` is in the ignore list for read."""
        if ignore is None:
            ignore = set()
        ignore.add('secret_key')
        return super().read(entity, attrs, ignore, params)


class ConfigGroup(
    Entity,
    EntityCreateMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
    EntityDeleteMixin,
):
    """A representation of a Config Group entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
        }
        self._meta = {
            'api_path': 'foreman_puppet/api/config_groups',
        }
        super().__init__(server_config=server_config, **kwargs)


class TemplateInput(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
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
            'template': entity_fields.OneToOneField(JobTemplate, required=True, parent=True),
            'variable_name': entity_fields.StringField(),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            'api_path': f'/api/v2/templates/{self.template.id}/template_inputs',
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Create a JobTemplate object before calling read, ignore 'advanced'."""
        entity = entity or self.entity_with_parent()
        if ignore is None:
            ignore = set()
        ignore.add('advanced')
        return super().read(entity=entity, attrs=attrs, ignore=ignore, params=params)


class JobInvocation(Entity, EntityReadMixin, EntitySearchMixin):
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
        self._meta = {'api_path': 'api/job_invocations'}
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        cancel
            /api/job_invocations/<id>/cancel
        rerun
            /api/job_invocations/<id>/rerun
        outputs
            /api/job_invocations/<id>/outputs

        ``super`` is called otherwise.
        """
        if which in (
            'cancel',
            'rerun',
            'outputs',
        ):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def cancel(self, synchronous=True, timeout=None, **kwargs):
        """Cancel JobInvocation running on the host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('cancel'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def rerun(self, synchronous=True, timeout=None, **kwargs):
        """Rerun JobInvocation which already ran on the host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('rerun'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def outputs(self, synchronous=True, timeout=None, **kwargs):
        """Get output of JobInvocation running on the host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('outputs'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def run(self, synchronous=True, **kwargs):
        """Run an existing job template.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param kwargs: Arguments to pass to requests.
            'data' supports next fields:

                required:
                    job_template_id/feature,
                    targeting_type,
                    search_query/bookmark_id,
                optional:
                    inputs,
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
            if 'targeting_type' not in kwargs['data']:
                raise KeyError('Provide targeting_type value')
            kwargs['data'] = {'job_invocation': kwargs['data']}
        response = client.post(self.path('base'), **kwargs)
        response.raise_for_status()
        if synchronous is True:
            return ForemanTask(
                server_config=self._server_config, id=response.json()['task']['id']
            ).poll()
        return response.json()


class JobTemplate(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
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
        self._meta = {'api_path': 'api/v2/job_templates'}
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        payload = super().create_payload()
        effective_user = payload.pop('effective_user', None)
        if effective_user:
            payload['ssh'] = {'effective_user': effective_user}

        return {'job_template': payload}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super().update_payload(fields)
        effective_user = payload.pop('effective_user', None)
        if effective_user:
            payload['ssh'] = {'effective_user': effective_user}
        return {'job_template': payload}

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Ignore the template inputs when initially reading the job template.

        Look up each TemplateInput entity separately
        and afterwards add them to the JobTemplate entity.
        """
        if attrs is None:
            attrs = self.read_json(params=params)
        if ignore is None:
            ignore = set()
        ignore.add('template_inputs')
        ignore.add('audit_comment')
        entity = super().read(entity=entity, attrs=attrs, ignore=ignore, params=params)
        referenced_entities = [
            TemplateInput(
                entity._server_config,
                id=entity_id,
                template=JobTemplate(entity._server_config, id=entity.id),
            )
            for entity_id in _get_entity_ids('template_inputs', attrs)
        ]
        entity.template_inputs = referenced_entities
        return entity

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        clone
            /api/job_templates/:id/clone

        Otherwise, call ``super``.

        """
        if which in ('clone'):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def clone(self, synchronous=True, timeout=None, **kwargs):
        """Clone an existing report template.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('clone'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class ProvisioningTemplate(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Provisioning Template entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'audit_comment': entity_fields.StringField(),
            'locked': entity_fields.BooleanField(),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
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
        }
        super().__init__(server_config=server_config, **kwargs)

    def create_missing(self):
        """Customize the process of auto-generating instance attributes.

        Populate ``template_kind`` if:

        * this template is not a snippet, and
        * the ``template_kind`` instance attribute is unset.

        """
        super().create_missing()
        if getattr(self, 'snippet', None) is False and not hasattr(self, 'template_kind'):
            self.template_kind = TemplateKind(server_config=self._server_config, id=1)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        payload = super().create_payload()
        if 'template_combinations' in payload:
            payload['template_combinations_attributes'] = payload.pop('template_combinations')
        return {'provisioning_template': payload}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super().update_payload(fields)
        if 'template_combinations' in payload:
            payload['template_combinations_attributes'] = payload.pop('template_combinations')
        return {'provisioning_template': payload}

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
        if which in ("build_pxe_default", "clone", "revision"):
            prefix = "self" if which == "clone" else "base"
            return f"{super().path(prefix)}/{which}"
        return super().path(which)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read`` provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`ProvisioningTemplate` requires that a ``audit_comment`` is
        provided, so this technique will not work.
        """
        if ignore is None:
            ignore = set()
        ignore.add('audit_comment')
        return super().read(entity, attrs, ignore, params)

    def build_pxe_default(self, synchronous=True, timeout=None, **kwargs):
        """Build pxe default template.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('build_pxe_default'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def clone(self, synchronous=True, timeout=None, **kwargs):
        """Clone an existing provision template.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('clone'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class ReportTemplate(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Report Template entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'location': entity_fields.OneToManyField(Location),
            'template': entity_fields.StringField(required=True),
            'default': entity_fields.BooleanField(required=True),
            'locked': entity_fields.BooleanField(),
        }
        self._meta = {
            'api_path': 'api/v2/report_templates',
        }
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        payload = super().create_payload()
        if 'template_combinations' in payload:
            payload['template_combinations_attributes'] = payload.pop('template_combinations')
        return {'report_template': payload}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super().update_payload(fields)
        if 'template_combinations' in payload:
            payload['template_combinations_attributes'] = payload.pop('template_combinations')
        return {'report_template': payload}

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        clone
            /report_templates/<id>/clone

        generate
            /report_templates/<id>/generate

        ``super`` is called otherwise.

        """
        if which in ("clone", "generate", "schedule_report", "report_data"):
            prefix = "self"
            return f"{super().path(prefix)}/{which}"
        return super().path(which)

    def clone(self, synchronous=True, timeout=None, **kwargs):
        """Clone an existing report template.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('clone'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def generate(self, synchronous=True, timeout=None, **kwargs):
        """Generate an existing report template.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('generate'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def schedule_report(self, synchronous=True, timeout=None, **kwargs):
        """Schedule an existing report template.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('schedule_report'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def report_data(self, synchronous=True, timeout=None, **kwargs):
        """Call report_data on an existing scheduled report.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        temp_path = self.path('report_data')
        job_id = kwargs.get('data', {}).get('job_id')
        if job_id:
            temp_path = f'{temp_path}/{job_id}'
        response = client.get(temp_path, **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class ContentCredential(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Content Credential entity."""

    def __init__(self, server_config=None, **kwargs):
        self._updatable_fields = ['name', 'content_type', 'content']
        self._fields = {
            'content': entity_fields.StringField(required=True),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
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
        }
        super().__init__(server_config=server_config, **kwargs)


class ContentUpload(
    Entity, EntityCreateMixin, EntityReadMixin, EntityUpdateMixin, EntityDeleteMixin
):
    """A representation of a Content Upload entity."""

    content_chunk_size = 2 * 1024 * 1024

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('repository', kwargs)
        self._fields = {
            'upload_id': entity_fields.StringField(length=36, unique=True),
            'repository': entity_fields.OneToOneField(Repository, required=True, parent=True),
            'size': entity_fields.IntegerField(required=True, min_val=self.content_chunk_size),
        }
        super().__init__(server_config=server_config, **kwargs)
        # a ContentUpload does not have an id field, only an upload_id
        self._fields.pop('id')
        self._meta = {
            'api_path': f'{self.repository.path()}/content_uploads',
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
        entity = entity or self.entity_with_parent()
        if ignore is None:
            ignore = set()
        ignore.add('repository')
        ignore.add('size')
        return super().read(entity, attrs, ignore, params)

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
        return client.put(self.path('self'), fields, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``."""
        base = urljoin(f'{self._server_config.url}/', self._meta['api_path'])
        if (which == 'self' or which is None) and hasattr(self, 'upload_id'):
            return urljoin(f'{base}/', str(self.upload_id))
        return super().path(which)

    def upload(self, filepath, content_type=None, filename=None):
        """Upload content.

        :param filepath: path to the file that should be chunked and uploaded
        :param content_type: type of content
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

            with open(filepath, 'rb') as contentfile:
                chunk = contentfile.read(self.content_chunk_size)
                while len(chunk) > 0:
                    data = {'offset': offset, 'content': chunk, 'size': self.content_chunk_size}
                    content_upload.update(data)

                    offset += len(chunk)
                    chunk = contentfile.read(self.content_chunk_size)

            size = 0
            checksum = hashlib.sha256()
            with open(filepath, 'rb') as contentfile:
                contents = contentfile.read()
                size = len(contents)
                checksum.update(contents)

            uploads = [
                {
                    'id': content_upload.upload_id,
                    'name': filename,
                    'size': size,
                    'checksum': checksum.hexdigest(),
                }
            ]
            json = self.repository.import_uploads(uploads=uploads, content_type=content_type)
        finally:
            content_upload.delete()

        return json


class ContentViewVersion(Entity, EntityDeleteMixin, EntityReadMixin, EntitySearchMixin):
    """A representation of a Content View Version non-entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'ansible_collection_count': entity_fields.IntegerField(),
            'ansible_collection_repository_count': entity_fields.IntegerField(),
            'docker_manifest_count': entity_fields.IntegerField(),
            'docker_manifest_list_count': entity_fields.IntegerField(),
            'docker_repository_count': entity_fields.IntegerField(),
            'docker_tag_count': entity_fields.IntegerField(),
            'component_view_count': entity_fields.IntegerField(),
            'content_view': entity_fields.OneToOneField(ContentView),
            'description': entity_fields.StringField(),
            'environment': entity_fields.OneToManyField(LifecycleEnvironment),
            'errata_counts': entity_fields.DictField(),
            'file_count': entity_fields.IntegerField(),
            'file_repository_count': entity_fields.IntegerField(),
            'filters_applied': entity_fields.BooleanField(),
            'major': entity_fields.IntegerField(),
            'minor': entity_fields.IntegerField(),
            'module_stream_count': entity_fields.IntegerField(),
            'name': entity_fields.StringField(),
            'package_count': entity_fields.IntegerField(),
            'package_group_count': entity_fields.IntegerField(),
            'repository': entity_fields.OneToManyField(Repository),
            'srpm_count': entity_fields.IntegerField(),
            'version': entity_fields.StringField(),
            'yum_repository_count': entity_fields.IntegerField(),
        }
        self._meta = {
            'api_path': 'katello/api/v2/content_view_versions',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        incremental_update
            /content_view_versions/incremental_update
        promote
            /content_view_versions/<id>/promote
        verify_checksum
            /content_view_versions/<id>/verify_checksum
        republish_repositories
            /content_view_versions/<id>/republish_repositories

        ``super`` is called otherwise.

        """
        if which in ("incremental_update", "promote", "verify_checksum", "republish_repositories"):
            prefix = "base" if which == "incremental_update" else "self"
            return f"{super().path(prefix)}/{which}"
        return super().path(which)

    def incremental_update(self, synchronous=True, timeout=None, **kwargs):
        """Incrementally update a content view version.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('incremental_update'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def promote(self, synchronous=True, timeout=None, **kwargs):
        """Promote an existing published content view.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('promote'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def verify_checksum(self, synchronous=True, timeout=None, **kwargs):
        """Verify checksum of repository contents in the content view version.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('verify_checksum'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def republish_repositories(self, synchronous=True, timeout=None, **kwargs):
        """Force a republish of the version's repositories metadata.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('republish_repositories'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class ContentViewFilterRule(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Content View Filter Rule entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('content_view_filter', kwargs)
        self._fields = {
            'content_view_filter': entity_fields.OneToOneField(
                AbstractContentViewFilter, required=True, parent=True
            ),
            'date_type': entity_fields.StringField(
                choices=('issued', 'updated'),
            ),
            'end_date': entity_fields.DateField(),
            'errata': entity_fields.OneToOneField(Errata),
            'max_version': entity_fields.StringField(),
            'min_version': entity_fields.StringField(),
            'name': entity_fields.StringField(str_type='alpha', length=(6, 12), unique=True),
            'start_date': entity_fields.DateField(),
            'types': entity_fields.ListField(),
            'version': entity_fields.StringField(),
            'uuid': entity_fields.StringField(),
            'architecture': entity_fields.StringField(),
            'module_stream': entity_fields.OneToManyField(ModuleStream),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            "api_path": f'{self.content_view_filter.path("self")}/rules',
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
        entity = entity or self.entity_with_parent()
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()
        ignore.add('content_view_filter')
        ignore.update([field_name for field_name in entity.get_fields() if field_name not in attrs])
        return super().read(entity, attrs, ignore, params)

    def create_payload(self):
        """Reset ``errata_id`` from DB ID to ``errata_id``."""
        payload = super().create_payload()
        if 'errata_id' in payload:
            if not hasattr(self.errata, 'errata_id'):
                self.errata = self.errata.read()
            payload['errata_id'] = self.errata.errata_id
        return payload

    def update_payload(self, fields=None):
        """Reset ``errata_id`` from DB ID to ``errata_id``."""
        payload = super().update_payload(fields)
        if 'errata_id' in payload:
            if not hasattr(self.errata, 'errata_id'):
                self.errata = self.errata.read()
            payload['errata_id'] = self.errata.errata_id
        return payload

    def search_payload(self, fields=None, query=None):
        """Reset ``errata_id`` from DB ID to ``errata_id``."""
        payload = super().search_payload(fields, query)
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
    EntityUpdateMixin,
):
    """A representation of a Content View Filter entity."""

    def __init__(self, server_config=None, **kwargs):
        # The `fields={…}; fields.update(…)` idiom lets subclasses add fields.
        fields = {
            'content_view': entity_fields.OneToOneField(ContentView, required=True),
            'description': entity_fields.StringField(),
            'type': entity_fields.StringField(
                choices=('erratum', 'package_group', 'rpm', 'modulemd', 'docker'),
                required=True,
            ),
            'inclusion': entity_fields.BooleanField(),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'repository': entity_fields.OneToManyField(Repository),
        }
        fields.update(getattr(self, '_fields', {}))
        self._fields = fields
        self._meta = {
            'api_path': 'katello/api/v2/content_view_filters',
        }
        super().__init__(server_config=server_config, **kwargs)


class ErratumContentViewFilter(AbstractContentViewFilter):
    """A representation of a Content View Filter of type "erratum"."""

    def __init__(self, server_config=None, **kwargs):
        super().__init__(server_config=server_config, **kwargs)
        self._fields['type'].default = 'erratum'


class ModuleStreamContentViewFilter(AbstractContentViewFilter):
    """A representation of a Content View Filter of type "modulemd"."""

    def __init__(self, server_config=None, **kwargs):
        # Add the `original_module_streams` field to what's provided by parent class.
        self._fields = {'original_module_streams': entity_fields.BooleanField()}
        super().__init__(server_config=server_config, **kwargs)
        self._fields['type'].default = 'modulemd'


class PackageGroupContentViewFilter(AbstractContentViewFilter):
    """A representation of a Content View Filter of type "package_group"."""

    def __init__(self, server_config=None, **kwargs):
        super().__init__(server_config=server_config, **kwargs)
        self._fields['type'].default = 'package_group'


class RPMContentViewFilter(AbstractContentViewFilter):
    """A representation of a Content View Filter of type "rpm"."""

    def __init__(self, server_config=None, **kwargs):
        # Add the `original_packages` field to what's provided by parent class.
        self._fields = {'original_packages': entity_fields.BooleanField()}
        super().__init__(server_config=server_config, **kwargs)
        self._fields['type'].default = 'rpm'


class DockerContentViewFilter(AbstractContentViewFilter):
    """A representation of a Content View Filter of type "docker"."""

    def __init__(self, server_config=None, **kwargs):
        super().__init__(server_config=server_config, **kwargs)
        self._fields['type'].default = 'docker'


class ContentView(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
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
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'needs_publish': entity_fields.BooleanField(),
            'next_version': entity_fields.IntegerField(),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'repository': entity_fields.OneToManyField(Repository),
            'rolling': entity_fields.BooleanField(),
            'solve_dependencies': entity_fields.BooleanField(),
            'version': entity_fields.OneToManyField(ContentViewVersion),
        }
        self._meta = {
            'api_path': 'katello/api/v2/content_views',
        }
        super().__init__(server_config=server_config, **kwargs)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Fetch an attribute missing from the server's response.

        For more information, see `Bugzilla #1237257
        <https://bugzilla.redhat.com/show_bug.cgi?id=1237257>`_.

        Add content_view_component to the response if needed, as
        :meth:`nailgun.entity_mixins.EntityReadMixin.read` can't initialize
        content_view_component.
        """
        attrs = attrs or self.read_json()
        ignore = ignore or set()
        ignore.add('content_view_component')
        if entity is None:
            try:
                entity = type(self)(server_config=self._server_config)
            except TypeError:
                # in the event that an entity's init is overwritten
                # with a positional server_config
                entity = type(self)()
                if self._server_config:
                    entity._server_config = self._server_config
        result = super().read(entity, attrs, ignore, params)
        if attrs.get('content_view_components'):
            result.content_view_component = [
                ContentViewComponent(
                    server_config=self._server_config,
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
            entity = self.entity_with_parent(**result)
            if content_view_components:
                entity.content_view_component = [
                    ContentViewComponent(
                        server_config=self._server_config,
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

        content_view_versions
            /content_views/<id>/content_view_versions
        publish
            /content_views/<id>/publish
        remove
            /content_views/<id>/remove

        ``super`` is called otherwise.

        """
        if which in (
            'content_view_versions',
            'copy',
            'publish',
            'remove',
        ):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def publish(self, synchronous=True, timeout=None, **kwargs):
        """Publish an existing content view.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        if 'data' in kwargs and 'id' not in kwargs['data']:
            kwargs['data']['id'] = self.id
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('publish'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def remove_version(self, versions, synchronous=True, timeout=None):
        """Remove published content view Version(s) from this content view.

        Also remove the CV from the Version's environment(s), including Library.

        :param versions: ContentViewVersion (entity) or ID (int) to remove.
            can also pass a list of entities, or a list of IDs.
        """
        content_view = self.read()
        matched_versions = []
        environment_ids = set()
        # Normalize into a list of ids; from a single entity/:id, or a list.
        if isinstance(versions, list):
            version_ids = [v.id if hasattr(v, 'id') else int(v) for v in versions]
        else:
            version_ids = [versions.id if hasattr(versions, 'id') else int(versions)]
        # Match the Version ID from CV to the provided Versions
        for vid in version_ids:
            matched_versions = [v for v in content_view.version if v.id == vid]
            for version in matched_versions:
                v = version.read()
                environment_ids.update(env.id for env in v.environment)
        if not matched_versions:
            raise ValueError(
                f'No Version(s) or :id(s) provided: {versions} ,'
                f' matched the published Versions of the Content-View[id:{content_view.id}]: {content_view.version}'
            )
        environment_ids = list(environment_ids)
        # PUT request: `remove` these CVV-ids and ENV-ids from this CV.
        response = client.put(
            f'{self.path("remove")}',
            json={'content_view_version_ids': version_ids, 'environment_ids': environment_ids},
            **self._server_config.get_client_kwargs(),
        )
        return _handle_response(response, self._server_config, synchronous, timeout)

    def copy(self, synchronous=True, timeout=None, **kwargs):
        """Clone provided content view.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        if 'data' in kwargs and 'id' not in kwargs['data']:
            kwargs['data']['id'] = self.id
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('copy'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def delete_from_environment(self, environment, synchronous=True, timeout=None):
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
            f'{self.path()}/environments/{environment_id}',
            **self._server_config.get_client_kwargs(),
        )
        return _handle_response(response, self._server_config, synchronous, timeout)


class ContentViewComponent(Entity, EntityReadMixin, EntityUpdateMixin):
    """A representation of a Content View Components entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('composite_content_view', kwargs)
        self._fields = {
            'composite_content_view': entity_fields.OneToOneField(ContentView, parent=True),
            'content_view': entity_fields.OneToOneField(ContentView),
            'content_view_version': entity_fields.OneToOneField(ContentViewVersion),
            'latest': entity_fields.BooleanField(),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            'api_path': f'{self.composite_content_view.path()}/content_view_components',
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Add composite_content_view to the response if needed.

        :meth:`nailgun.entity_mixins.EntityReadMixin.read` can't initialize composite_content_view.
        """
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()
        entity = entity or self.entity_with_parent()

        ignore.add('composite_content_view')
        return super().read(entity, attrs, ignore, params)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        add
            /content_view_components/add
        remove
            /content_view_components/remove

        Otherwise, call ``super``.

        """
        if which in ("add", "remove"):
            return f'{super().path(which="base")}/{which}'

        return super().path(which)

    def add(self, synchronous=True, timeout=None, **kwargs):
        """Add provided Content View Component.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        if 'data' not in kwargs:
            # data is required
            kwargs['data'] = {}
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('add'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def remove(self, synchronous=True, timeout=None, **kwargs):
        """Remove provided Content View Component.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        if 'data' not in kwargs:
            # data is required
            kwargs['data'] = {}
        if 'data' in kwargs and 'component_ids' not in kwargs['data']:
            kwargs['data']['component_ids'] = [self.id]
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('remove'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class Domain(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Domain entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'dns': entity_fields.OneToOneField(SmartProxy),
            'domain_parameters_attributes': entity_fields.ListField(),
            'fullname': entity_fields.StringField(),
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
        }
        self._meta = {'api_path': 'api/v2/domains'}
        super().__init__(server_config=server_config, **kwargs)

    def create_missing(self):
        """Customize the process of auto-generating instance attributes.

        By default, :meth:`nailgun.entity_fields.StringField.gen_value` can
        produce strings in both lower and upper cases, but domain name should
        be always in lower case due logical reason.

        """
        if not hasattr(self, 'name'):
            self.name = gen_alphanumeric().lower()
        super().create_missing()

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'domain': super().create_payload()}

    def create(self, create_missing=None):
        """Manually fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1219654
        <https://bugzilla.redhat.com/show_bug.cgi?id=1219654>`_.

        """
        return type(self)(
            server_config=self._server_config,
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
        return super().read(entity, attrs, ignore, params)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1234999
        <https://bugzilla.redhat.com/show_bug.cgi?id=1234999>`_.

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'domain': super().update_payload(fields)}


class Environment(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Environment entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True,
                str_type='alphanumeric',  # cannot contain whitespace
                length=(6, 12),
                unique=True,
            ),
            'organization': entity_fields.OneToManyField(Organization),
        }
        self._meta = {
            'api_path': 'foreman_puppet/api/environments',
        }
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'environment': super().create_payload()}

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1262029
        <https://bugzilla.redhat.com/show_bug.cgi?id=1262029>`_.

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'environment': super().update_payload(fields)}

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        smart_class_parameters
            /foreman_puppet/api/environments/:environment_id/smart_class_parameters

        Otherwise, call ``super``.

        """
        if which in ("smart_class_parameters",):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def list_scparams(self, synchronous=True, timeout=None, **kwargs):
        """List all smart class parameters.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('smart_class_parameters'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class Errata(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of an Errata entity."""

    # You cannot create an errata. Errata are a read-only entity.

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'content_view_version': entity_fields.OneToOneField(ContentViewVersion),
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
        self._meta = {'api_path': '/katello/api/v2/errata'}
        super().__init__(server_config=server_config, **kwargs)

    def compare(self, synchronous=True, timeout=None, **kwargs):
        """Compare errata from different content view versions.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('compare'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        compare
            /katello/api/errata/compare

        Otherwise, call ``super``.

        """
        if which in ("compare",):
            return f'{super().path(which="base")}/{which}'
        return super().path(which)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Read errata from the server.

        Following fields are only accessible for filtering search results
        and are never returned by the server:

        ``content_view_version_id``, ``environment_id``, ``repository_id``.
        """
        if ignore is None:
            ignore = set()
        ignore.add('content_view_version')
        ignore.add('environment')
        ignore.add('repository')
        return super().read(entity, attrs, ignore, params)


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
        super().__init__(server_config=server_config, **kwargs)


class Filter(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
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
        self._meta = {'api_path': 'api/v2/filters'}
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'filter': super().create_payload()}

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Deal with different named data returned from the server."""
        if attrs is None:
            attrs = self.read_json()
        attrs['override'] = attrs.pop('override?')
        attrs['unlimited'] = attrs.pop('unlimited?')
        return super().read(entity, attrs, ignore, params)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'filter': super().update_payload(fields)}


class FlatpakRemoteRepository(
    Entity,
    EntityReadMixin,
    EntitySearchMixin,
):
    """A representation of a Flatpak remote repository entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'flatpak_remote_id': entity_fields.IntegerField(required=True),
            'name': entity_fields.StringField(),
            'label': entity_fields.StringField(),
        }
        self._meta = {
            'api_path': 'katello/api/flatpak_remote_repositories',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        mirror
            /katello/api/flatpak_remote_repositories/:id/mirror
        """
        if which == "mirror":
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def mirror(self, product_id, synchronous=True, timeout=None, **kwargs):
        """Mirror a flatpak remote repository.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        if 'data' not in kwargs:
            kwargs['data'] = {}
        if 'product_id' not in kwargs['data']:
            kwargs['data']['product_id'] = product_id
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('mirror'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class FlatpakRemote(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Flatpak remote entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'url': entity_fields.URLField(required=True),
            'organization': entity_fields.OneToOneField(Organization, required=True),
            'description': entity_fields.StringField(),
            'username': entity_fields.StringField(),
            'registry_url': entity_fields.StringField(),
            'seeded': entity_fields.BooleanField(),
        }
        self._meta = {
            'api_path': 'katello/api/flatpak_remotes',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        scan
            /katello/api/flatpak_remote/:id/scan
        """
        if which == "scan":
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def scan(self, synchronous=True, timeout=None, **kwargs):
        """Scan a flatpak remote.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('scan'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


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
            'read_type': 'base',
        }
        super().__init__(server_config=server_config, **kwargs)


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
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        bulk_resume
            /foreman_tasks/api/tasks/bulk_resume
        bulk_cancel
            /foreman_tasks/api/tasks/bulk_cancel
        bulk_search
            /foreman_tasks/api/tasks/bulk_search
        summary
            /foreman_tasks/api/tasks/summary

        Otherwise, call ``super``.

        """
        if which in ("bulk_resume", "bulk_search", "summary", "bulk_cancel"):
            return f'{super().path(which="base")}/{which}'
        return super().path(which)

    def poll(self, poll_rate=None, timeout=None, must_succeed=True):
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
        :param must_succeed: Raise error when task finishes with other then success
            result.
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
        return _poll_task(self.id, self._server_config, poll_rate, timeout, must_succeed)

    def summary(self, synchronous=True, timeout=None, **kwargs):
        """View a summary of tasks.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('summary'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def bulk_cancel(self, synchronous=True, timeout=None, **kwargs):
        """Cancel the task(s).

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('bulk_cancel'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def bulk_resume(self, synchronous=True, timeout=None, **kwargs):
        """Resumes the task(s).

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('bulk_resume'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class GPGKey(ContentCredential):
    """A representation of a GPG Key entity."""

    def __init__(self, server_config=None, **kwargs):
        super().__init__(server_config=server_config, **kwargs)


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
        }
        super().__init__(server_config=server_config, **kwargs)


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
        }
        super().__init__(server_config=server_config, **kwargs)


class HostCollection(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Host Collection entity."""

    def __init__(self, server_config=None, **kwargs):
        self._updatable_fields = [
            'name',
            'description',
            'host_ids',
            'max_hosts',
            'unlimited_hosts',
        ]
        self._fields = {
            'description': entity_fields.StringField(),
            'host': entity_fields.OneToManyField(Host),
            'max_hosts': entity_fields.IntegerField(),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'unlimited_hosts': entity_fields.BooleanField(),
        }
        self._meta = {
            'api_path': 'katello/api/v2/host_collections',
        }
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Rename ``system_ids`` to ``system_uuids``."""
        payload = super().create_payload()
        if 'system_ids' in payload:
            payload['system_uuids'] = payload.pop('system_ids')
        return payload

    def create(self, create_missing=None):
        """Manually fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1654383
        <https://bugzilla.redhat.com/show_bug.cgi?id=1654383>`_.

        """
        return type(self)(
            server_config=self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()


class HostGroup(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Host Group entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'architecture': entity_fields.OneToOneField(Architecture),
            'description': entity_fields.StringField(),
            'domain': entity_fields.OneToOneField(Domain),
            'puppet_proxy': entity_fields.OneToOneField(SmartProxy),
            'puppet_ca_proxy': entity_fields.OneToOneField(SmartProxy),
            'content_source': entity_fields.OneToOneField(SmartProxy),
            'content_view': entity_fields.OneToOneField(ContentView),
            'compute_resource': entity_fields.OneToOneField(AbstractComputeResource),
            'compute_profile': entity_fields.OneToOneField(ComputeProfile),
            'environment': entity_fields.OneToOneField(Environment),
            'kickstart_repository': entity_fields.OneToOneField(Repository),
            'lifecycle_environment': entity_fields.OneToOneField(LifecycleEnvironment),
            'location': entity_fields.OneToManyField(Location),
            'medium': entity_fields.OneToOneField(Media),
            'root_pass': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'operatingsystem': entity_fields.OneToOneField(OperatingSystem),
            'organization': entity_fields.OneToManyField(Organization),
            'parent': entity_fields.OneToOneField(HostGroup),
            'ptable': entity_fields.OneToOneField(PartitionTable),
            'pxe_loader': entity_fields.StringField(
                choices=(
                    'PXELinux BIOS',
                    'PXELinux UEFI',
                    'Grub UEFI',
                    'Grub2 BIOS'
                    'Grub2 ELF'
                    'Grub2 UEFI'
                    'Grub2 UEFI SecureBoot'
                    'Grub2 UEFI HTTP'
                    'Grub2 UEFI HTTPS'
                    'Grub2 UEFI HTTPS SecureBoot'
                    'iPXE Embedded'
                    'iPXE UEFI HTTP'
                    'iPXE Chain BIOS'
                    'iPXE Chain UEFI',
                ),
                default='PXELinux BIOS',
            ),
            'realm': entity_fields.OneToOneField(Realm),
            'subnet': entity_fields.OneToOneField(Subnet),
            'subnet6': entity_fields.OneToOneField(Subnet),
            'group_parameters_attributes': entity_fields.ListField(),
        }

        self._fields.update(
            {
                'content_view': entity_fields.OneToOneField(ContentView),
                'lifecycle_environment': entity_fields.OneToOneField(LifecycleEnvironment),
            }
        )
        self._meta = {'api_path': 'api/v2/hostgroups'}
        super().__init__(server_config=server_config, **kwargs)

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1235377
        <https://bugzilla.redhat.com/show_bug.cgi?id=1235377>`_.

        """
        return type(self)(
            server_config=self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'hostgroup': super().create_payload()}

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
        ignore = ignore or set()
        ignore.add('root_pass')
        ignore.add('kickstart_repository')
        ignore.add('compute_resource')

        attrs = attrs or self.read_json()
        attrs['parent_id'] = attrs.pop('ancestry')  # either an ID or None
        attrs['group_parameters_attributes'] = attrs.pop('parameters')

        return super().read(entity, attrs, ignore, params)

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
        return {'hostgroup': super().update_payload(fields)}

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
        assign_ansible_roles
            /api/hostgroups/:hostgroup_id/assign_ansible_roles
        ansible_roles
            /api/hostgroups/:hostgroup_id/ansible_roles

        Otherwise, call ``super``.

        """
        if which in (
            'assign_ansible_roles',
            'ansible_roles',
            'clone',
            'puppetclass_ids',
            'rebuild_config',
            'smart_class_parameters',
        ):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def add_puppetclass(self, synchronous=True, timeout=None, **kwargs):
        """Add a Puppet class to host group.

        Here is an example of how to use this method::
            hostgroup.add_puppetclass(data={'puppetclass_id': puppet.id})

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('puppetclass_ids'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def delete_puppetclass(self, synchronous=True, timeout=None, **kwargs):
        """Remove a Puppet class from host group.

        Here is an example of how to use this method::
            hostgroup.delete_puppetclass(data={'puppetclass_id': puppet.id})

        Constructs path:
            /api/hostgroups/:hostgroup_id/puppetclass_ids/:id

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        path = f'{self.path("puppetclass_ids")}/{kwargs["data"].pop("puppetclass_id")}'
        return _handle_response(
            client.delete(path, **kwargs), self._server_config, synchronous, timeout
        )

    def list_scparams(self, synchronous=True, timeout=None, **kwargs):
        """List all smart class parameters.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('smart_class_parameters'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def clone(self, synchronous=True, timeout=None, **kwargs):
        """Clone an existing host group.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('clone'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def rebuild_config(self, synchronous=True, timeout=None, **kwargs):
        """Rebuild orchestration config of an existing host group.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('rebuild_config'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def assign_ansible_roles(self, synchronous=True, timeout=None, **kwargs):
        """Add an Ansible Role to a hostgroup.

        Here is an example of how to use this method::
            hostgroup.assign_ansible_roles(data={'ansible_role_ids':
            [ansible_role_id1, ansible_role_id2]})

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('assign_ansible_roles'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def list_ansible_roles(self, synchronous=True, timeout=None, **kwargs):
        """List all Ansible Roles assigned to a hostgroup.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('ansible_roles'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def add_ansible_role(self, synchronous=True, timeout=None, **kwargs):
        """Add single Ansible Role to a hostgroup.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        path = f'{self.path("ansible_roles")}/{kwargs["data"].pop("ansible_role_id")}'
        return _handle_response(
            client.put(path, **kwargs), self._server_config, synchronous, timeout
        )

    def remove_ansible_role(self, synchronous=True, timeout=None, **kwargs):
        """Remove single Ansible Role assigned to a hostgroup.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        path = f'{self.path("ansible_roles")}/{kwargs["data"].pop("ansible_role_id")}'
        return _handle_response(
            client.delete(path, **kwargs), self._server_config, synchronous, timeout
        )


class HostPackage(Entity):
    """A representation of a Host Package entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('host', kwargs)
        self._fields = {
            'groups': entity_fields.ListField(),
            'host': entity_fields.OneToOneField(Host, required=True),
            'packages': entity_fields.ListField(),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            'api_path': f'{self.host.path()}/packages',
        }


class HostSubscription(Entity):
    """A representation of a Host Subscription entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('host', kwargs)
        self._fields = {
            'content_label': entity_fields.StringField(),
            'host': entity_fields.OneToOneField(Host, required=True),
            'subscriptions': entity_fields.DictField(),
            'value': entity_fields.StringField(),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            'api_path': f'{self.host.path()}/subscriptions',
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
        if which in ('add_subscriptions', 'remove_subscriptions'):
            return f'{super().path(which="base")}/{which}'
        return super().path(which)

    def subscriptions(self, synchronous=True, timeout=None, **kwargs):
        """Get subscriptions from host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('base'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def add_subscriptions(self, synchronous=True, timeout=None, **kwargs):
        """Add subscriptions to host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('add_subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def remove_subscriptions(self, synchronous=True, timeout=None, **kwargs):
        """Remove subscriptions from host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('remove_subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class Host(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntityUpdateMixin,
    EntitySearchMixin,
):
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
            'compute_resource': entity_fields.OneToOneField(AbstractComputeResource),
            'content_facet_attributes': entity_fields.DictField(),
            'domain': entity_fields.OneToOneField(Domain),
            'enabled': entity_fields.BooleanField(),
            'environment': entity_fields.OneToOneField(Environment),
            'excluded': entity_fields.ListField(),
            'hostgroup': entity_fields.OneToOneField(HostGroup),
            'host_parameters_attributes': entity_fields.ListField(),
            'image': entity_fields.OneToOneField(Image),
            'included': entity_fields.ListField(),
            'interface': entity_fields.OneToManyField(Interface),
            'interfaces_attributes': entity_fields.DictField(),
            'ip': entity_fields.StringField(),
            'ip6': entity_fields.StringField(),
            'location': entity_fields.OneToOneField(Location, required=True),
            'mac': entity_fields.MACAddressField(),
            'managed': entity_fields.BooleanField(),
            'medium': entity_fields.OneToOneField(Media),
            'model': entity_fields.OneToOneField(Model),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
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
            'reported_data': entity_fields.DictField(),
            'root_pass': entity_fields.StringField(length=(8, 30), str_type='alpha'),
            'subnet': entity_fields.OneToOneField(Subnet),
            'subnet6': entity_fields.OneToOneField(Subnet),
            'token': entity_fields.StringField(),
            'traces_status': entity_fields.IntegerField(min_val=-1, max_val=2),
            'traces_status_label': entity_fields.StringField(),
            'uuid': entity_fields.StringField(),
            'pxe_loader': entity_fields.StringField(
                choices=(
                    'PXELinux BIOS',
                    'PXELinux UEFI',
                    'Grub UEFI',
                    'Grub2 BIOS'
                    'Grub2 ELF'
                    'Grub2 UEFI'
                    'Grub2 UEFI SecureBoot'
                    'Grub2 UEFI HTTP'
                    'Grub2 UEFI HTTPS'
                    'Grub2 UEFI HTTPS SecureBoot'
                    'iPXE Embedded'
                    'iPXE UEFI HTTP'
                    'iPXE Chain BIOS'
                    'iPXE Chain UEFI',
                ),
                default='PXELinux BIOS',
            ),
        }
        self._owner_type = None  # actual ``owner_type`` value
        self._meta = {'api_path': 'api/v2/hosts'}
        super().__init__(server_config=server_config, **kwargs)

        # See https://github.com/SatelliteQE/nailgun/issues/258
        if (
            hasattr(self, 'owner')
            and hasattr(self.owner, 'id')
            and isinstance(self.owner.id, Entity)
        ):
            self.owner = self.owner.id

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
                self.owner = User(
                    server_config=self._server_config,
                    id=self.owner.id if isinstance(self.owner, Entity) else self.owner,
                )
        elif value == 'Usergroup':
            self._fields['owner'] = entity_fields.OneToOneField(UserGroup)
            if hasattr(self, 'owner'):
                self.owner = UserGroup(
                    server_config=self._server_config,
                    id=self.owner.id if isinstance(self.owner, Entity) else self.owner,
                )

    def get_values(self):
        """Correctly set the ``owner_type`` attribute."""
        attrs = super().get_values()
        if '_owner_type' in attrs and attrs['_owner_type'] is not None:
            attrs['owner_type'] = attrs.pop('_owner_type')
        else:
            attrs.pop('_owner_type')
        return attrs

    def create_missing(self):  # noqa: PLR0912, PLR0915 - TODO: Refactor this?
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
        super().create_missing()
        # See: https://bugzilla.redhat.com/show_bug.cgi?id=1227854
        self.name = self.name.lower()
        if not hasattr(self, 'mac'):
            self.mac = self._fields['mac'].gen_value()
        if not hasattr(self, 'root_pass'):
            self.root_pass = self._fields['root_pass'].gen_value()

        # Flesh out the dependency graph shown in the docstring.
        if not hasattr(self, 'domain'):
            self.domain = Domain(
                server_config=self._server_config,
                location=[self.location],
                organization=[self.organization],
            ).create(True)
        else:
            if not hasattr(self.domain, 'organization'):
                self.domain = self.domain.read()
            if self.location.id not in [loc.id for loc in self.domain.location]:
                self.domain.location.append(self.location)
                self.domain.update(['location'])
            if self.organization.id not in [org.id for org in self.domain.organization]:
                self.domain.organization.append(self.organization)
                self.domain.update(['organization'])
        if 'Puppet' in _feature_list(self._server_config):
            if not hasattr(self, 'environment'):
                self.environment = Environment(
                    server_config=self._server_config,
                    location=[self.location],
                    organization=[self.organization],
                ).create(True)
            else:
                if not hasattr(self.environment, 'organization'):
                    self.environment = self.environment.read()
                if int(self.location.id) not in [loc.id for loc in self.environment.location]:
                    self.environment.location.append(self.location)
                    self.environment.update(['location'])
                if int(self.organization.id) not in [
                    org.id for org in self.environment.organization
                ]:
                    self.environment.organization.append(self.organization)
                    self.environment.update(['organization'])
        if not hasattr(self, 'architecture'):
            self.architecture = Architecture(server_config=self._server_config).create(True)
        if not hasattr(self, 'ptable'):
            self.ptable = PartitionTable(
                server_config=self._server_config,
                location=[self.location],
                organization=[self.organization],
            ).create(True)
        if not hasattr(self, 'operatingsystem'):
            self.operatingsystem = OperatingSystem(
                server_config=self._server_config,
                architecture=[self.architecture],
                ptable=[self.ptable],
            ).create(True)
        else:
            if not hasattr(self.operatingsystem, 'architecture'):
                self.operatingsystem = self.operatingsystem.read()
            if self.architecture.id not in [arch.id for arch in self.operatingsystem.architecture]:
                self.operatingsystem.architecture.append(self.architecture)
                self.operatingsystem.update(['architecture'])
            if self.ptable.id not in [ptable.id for ptable in self.operatingsystem.ptable]:
                self.operatingsystem.ptable.append(self.ptable)
                self.operatingsystem.update(['ptable'])
        if not hasattr(self, 'medium'):
            self.medium = Media(
                server_config=self._server_config,
                operatingsystem=[self.operatingsystem],
                location=[self.location],
                organization=[self.organization],
            ).create(True)
        else:
            if not hasattr(self.medium, 'organization'):
                self.medium = self.medium.read()
            if self.operatingsystem.id not in [
                operatingsystem.id for operatingsystem in self.medium.operatingsystem
            ]:
                self.medium.operatingsystem.append(self.operatingsystem)
                self.medium.update(['operatingsystem'])
            if self.location.id not in [loc.id for loc in self.medium.location]:
                self.medium.location.append(self.location)
                self.medium.update(['location'])
            if self.organization.id not in [org.id for org in self.medium.organization]:
                self.medium.organization.append(self.organization)
                self.medium.update(['organization'])

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'host': super().create_payload()}

    def create(self, create_missing=None):
        """Manually fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1449749
        <https://bugzilla.redhat.com/show_bug.cgi?id=1449749>`_.
        """
        return type(self)(
            server_config=self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def enc(self, synchronous=True, timeout=None, **kwargs):
        """Return external node classifier (ENC) information.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('enc'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def errata(self, synchronous=True, timeout=None, **kwargs):
        """List errata available for the host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('errata'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def traces(self, synchronous=True, timeout=None, **kwargs):
        """List services that need restarting for the host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('traces'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def bulk_traces(self, synchronous=True, timeout=None, **kwargs):
        """List services that need restarting for the specified set of hosts.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('bulk/traces'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def resolve_traces(self, synchronous=True, timeout=None, **kwargs):
        """Resolve traces for the host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('traces/resolve'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def bulk_resolve_traces(self, synchronous=True, timeout=None, **kwargs):
        """Resolve traces for the specified set of hosts.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('bulk/resolve_traces'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def bulk_destroy(self, synchronous=True, timeout=None, **kwargs):
        """Destroy the set of hosts.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('bulk/destroy'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def packages(self, synchronous=True, timeout=None, **kwargs):
        """List packages installed on the host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('packages'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def debs(self, synchronous=True, timeout=None, **kwargs):
        """List debian packages installed on the host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('debs'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def module_streams(self, synchronous=True, timeout=None, **kwargs):
        """List module_streams available for the host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('module_streams'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def errata_applicability(self, synchronous=True, timeout=None, **kwargs):
        """Force regenerate errata applicability.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('errata/applicability'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def bulk_add_subscriptions(self, synchronous=True, timeout=None, **kwargs):
        """Add subscriptions to one or more hosts.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('bulk/add_subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def bulk_remove_subscriptions(self, synchronous=True, timeout=None, **kwargs):
        """Remove subscriptions from one or more hosts.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('bulk/remove_subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def bulk_available_incremental_updates(self, synchronous=True, timeout=None, **kwargs):
        """Get available_incremental_updates for one or more hosts.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('bulk/available_incremental_updates'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def get_facts(self, synchronous=True, timeout=None, **kwargs):
        """List all fact values of a given host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('facts'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def get_bootc_images(self, synchronous=True, timeout=None, **kwargs):
        """List all bootc_images, for all hosts.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('bootc_images'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def upload_facts(self, synchronous=True, timeout=None, **kwargs):
        """Upload facts for a host, creating the host if required.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('upload_facts'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Deal with oddly named and structured data returned by the server.

        For more information, see `Bugzilla #1235019
        <https://bugzilla.redhat.com/show_bug.cgi?id=1235019>`_
        and `Bugzilla #1449749
        <https://bugzilla.redhat.com/show_bug.cgi?id=1449749>`_.

        `content_facet_attributes` are returned only in case any of facet
        attributes were actually set.

        `traces_status` and `traces_status_label` are returned only in case when
        katello-host-tools-tracer is installed on the host

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
        if 'traces_status' not in attrs and 'traces_status_label' not in attrs:
            ignore.add('traces_status')
            ignore.add('traces_status_label')
        for optional_attr in ['content_facet_attributes', 'token', 'reported_data']:
            if optional_attr not in attrs:
                ignore.add(optional_attr)
        ignore.add('compute_attributes')
        ignore.add('interfaces_attributes')
        ignore.add('root_pass')
        ignore.add('included')
        ignore.add('excluded')
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
        # Ignore puppetclass attribute if we are running against Puppet disabled
        # instance. Ignore it also if the API does not return puppetclasses for
        # the given host, but only if it does not have Puppet proxy assigned.
        if (
            'Puppet' not in _feature_list(self._server_config)
            or 'puppetclasses' not in attrs
            and not attrs['puppet_proxy']
        ):
            ignore.add('puppetclass')
        result = super().read(entity, attrs, ignore, params)
        if attrs.get('image_id'):
            result.image = Image(
                server_config=self._server_config,
                id=attrs.get('image_id'),
                compute_resource=attrs.get('compute_resource_id'),
            )
        else:
            result.image = None
        if attrs.get('interfaces'):
            result.interface = [
                Interface(
                    server_config=self._server_config,
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
        return {'host': super().update_payload(fields)}

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        errata
            /api/hosts/:host_id/errata
        power
            /api/hosts/:host_id/power
        puppetclass_ids
            /api/hosts/:host_id/puppetclass_ids
        smart_class_parameters
            /api/hosts/:host_id/smart_class_parameters
        module_streams
            /api/hosts/:host_id/module_streams
        disassociate
            /api/hosts/:host_id/disassociate
        assign_ansible_roles
            /api/hosts/:host_id/assign_ansible_roles
        ansible_roles
            /api/hosts/:host_id/ansible_roles

        Otherwise, call ``super``.

        """
        if which in (
            'assign_ansible_roles',
            'ansible_roles',
            'disassociate',
            'enc',
            'errata',
            'errata/applicability',
            'facts',
            'packages',
            'debs',
            'play_roles',
            'power',
            'puppetclass_ids',
            'smart_class_parameters',
            'module_streams',
            'disassociate',
            'traces',
            'traces/resolve',
            'template',
            'templates',
        ):
            return f'{super().path(which="self")}/{which}'
        elif which in (
            'bootc_images',
            'bulk/add_subscriptions',
            'bulk/remove_subscriptions',
            'bulk/available_incremental_updates',
            'bulk/traces',
            'bulk/resolve_traces',
            'bulk/destroy',
        ):
            return f'{super().path(which="base")}/{which}'
        elif which in ('upload_facts',):
            return f'{super().path(which="base")}/facts'
        return super().path(which)

    def add_puppetclass(self, synchronous=True, timeout=None, **kwargs):
        """Add a Puppet class to host.

        Here is an example of how to use this method::
            host.add_puppetclass(data={'puppetclass_id': puppet.id})

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('puppetclass_ids'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def delete_puppetclass(self, synchronous=True, timeout=None, **kwargs):
        """Remove a Puppet class from host.

        Here is an example of how to use this method::
            host.delete_puppetclass(data={'puppetclass_id': puppet.id})

        Constructs path:
           /api/hosts/:hostgroup_id/puppetclass_ids/:id

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        path = f'{self.path("puppetclass_ids")}/{kwargs["data"].pop("puppetclass_id")}'
        return _handle_response(
            client.delete(path, **kwargs), self._server_config, synchronous, timeout
        )

    def read_template(self, synchronous=True, timeout=None, **kwargs):
        """Fetch and read the provisioning template for given host.

        Here is an example of how to use this method::
            host.read_template(data={'template_kind': 'iPXE'})

        Constructs path:
           api/hosts/:id/template/:kind

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        kind = f'{kwargs["data"].pop("template_kind")}'
        path = f'{self.path("template")}/{kind}'
        response = client.get(path, **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def list_scparams(self, synchronous=True, timeout=None, **kwargs):
        """List all smart class parameters.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('smart_class_parameters'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def power(self, synchronous=True, timeout=None, **kwargs):
        """Power the host off or on.

        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('power'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

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
            entity = self.entity_with_parent(**result)
            if image:
                entity.image = Image(
                    server_config=self._server_config,
                    id=image,
                    compute_resource=AbstractComputeResource(
                        server_config=self._server_config, id=result.get('compute_resource')
                    ),
                )
            entities.append(entity)
        if filters is not None:
            entities = self.search_filter(entities, filters)
        return entities

    def disassociate(self, synchronous=True, timeout=None, **kwargs):
        """Disassociate the host.

        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('disassociate'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def assign_ansible_roles(self, synchronous=True, timeout=None, **kwargs):
        """Add an Ansible Role to a host.

        Here is an example of how to use this method::
            host.assign_ansible_roles(data={'ansible_role_ids':
            [ansible_role_id1, ansible_role_id2]})

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('assign_ansible_roles'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def list_ansible_roles(self, synchronous=True, timeout=None, **kwargs):
        """List all Ansible Roles assigned to a Host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('ansible_roles'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def add_ansible_role(self, synchronous=True, timeout=None, **kwargs):
        """Add single Ansible Role to a host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        path = f'{self.path("ansible_roles")}/{kwargs["data"].pop("ansible_role_id")}'
        return _handle_response(
            client.put(path, **kwargs), self._server_config, synchronous, timeout
        )

    def remove_ansible_role(self, synchronous=True, timeout=None, **kwargs):
        """Remove single Ansible Role assigned to a host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        path = f'{self.path("ansible_roles")}/{kwargs["data"].pop("ansible_role_id")}'
        return _handle_response(
            client.delete(path, **kwargs), self._server_config, synchronous, timeout
        )

    def play_ansible_roles(self, synchronous=True, timeout=None, **kwargs):
        """Play all assigned ansible roles on a Host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: Ansible task id
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('play_roles'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)['task_id']

    def list_provisioning_templates(self, synchronous=True, timeout=None, **kwargs):
        """List all Provisioning templates assigned to a Host.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('templates'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)['templates']


class Image(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Image entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('compute_resource', kwargs)
        self._fields = {
            'architecture': entity_fields.OneToOneField(Architecture, required=True),
            'compute_resource': entity_fields.OneToOneField(
                AbstractComputeResource, required=True, parent=True
            ),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'operatingsystem': entity_fields.OneToOneField(OperatingSystem, required=True),
            'user_data': entity_fields.BooleanField(),
            'username': entity_fields.StringField(required=True),
            'uuid': entity_fields.StringField(required=True),
            'password': entity_fields.StringField(),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            "api_path": f'{self.compute_resource.path("self")}/images',
        }

    def create_payload(self):
        """Wrap submitted data within an extra dict."""
        return {'image': super().create_payload()}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'image': super().update_payload(fields)}

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
        entity = entity or self.entity_with_parent()
        if ignore is None:
            ignore = set()
        ignore.add('password')
        ignore.add('compute_resource')
        ignore.add('user_data')
        return super().read(entity, attrs, ignore, params)


class Interface(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
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
            'host': entity_fields.OneToOneField(Host, required=True, parent=True),
            'identifier': entity_fields.StringField(),
            'ip': entity_fields.IPAddressField(required=True),
            'mac': entity_fields.MACAddressField(required=True),
            'managed': entity_fields.BooleanField(),
            'mode': entity_fields.StringField(  # for 'bond' type
                choices=(
                    '802.3ad',
                    'active-backup',
                    'balance-alb',
                    'balance-rr',
                    'balance-tlb',
                    'balance-xor',
                    'broadcast',
                )
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
            'subnet6': entity_fields.OneToOneField(Subnet),
            'tag': entity_fields.StringField(),  # for 'virtual' type
            'type': entity_fields.StringField(
                choices=('interface', 'bmc', 'bond', 'bridge'), default='interface', required=True
            ),
            'virtual': entity_fields.BooleanField(),
            'username': entity_fields.StringField(),  # for 'bmc' type
            'execution': entity_fields.BooleanField(),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            'api_path': f'{self.host.path()}/interfaces',
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
        entity = entity or self.entity_with_parent()
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
        if attrs['type'] not in ('bridge', 'bond'):
            ignore.add('attached_devices')
        return super().read(entity, attrs, ignore, params)

    def search_normalize(self, results):
        """Append host id to search results to initialize found :class:`Interface` successfully."""
        for interface in results:
            interface['host_id'] = self.host.id
        return super().search_normalize(results)


class LifecycleEnvironment(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Lifecycle Environment entity."""

    def __init__(self, server_config=None, **kwargs):
        # NOTE: The "prior" field is unusual. See `create_missing`'s docstring.
        self._fields = {
            'description': entity_fields.StringField(),
            'label': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
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
        }
        super().__init__(server_config=server_config, **kwargs)

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
        super().create_missing()
        if self.name != 'Library' and not hasattr(self, 'prior'):
            results = self.search({'organization'}, {'name': 'Library'})
            if len(results) != 1:
                raise APIResponseError(
                    'Could not find the "Library" lifecycle environment for '
                    f'organization {self.organization}. Search results: {results}'
                )
            self.prior = results[0]


class HTTPProxy(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a HTTP Proxy entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'url': entity_fields.URLField(required=True),
            'username': entity_fields.StringField(),
            'password': entity_fields.StringField(),
            'organization': entity_fields.OneToManyField(Organization),
            'location': entity_fields.OneToManyField(Location),
            'cacert': entity_fields.StringField(),
            'content_default_http_proxy': entity_fields.BooleanField(),
        }
        self._meta = {'api_path': 'api/v2/http_proxies'}
        super().__init__(server_config=server_config, **kwargs)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'http_proxy': super().update_payload(fields)}

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.
        """
        return {'http_proxy': super().create_payload()}

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Make sure, password, organization and location is in the ignore list for read.

        For more information, see `Bugzilla #1779642
        <https://bugzilla.redhat.com/show_bug.cgi?id=1779642>`_.
        """
        if attrs is None:
            attrs = self.read_json()
        if ignore is None:
            ignore = set()
        ignore.add('password')
        ignore.add('organization')
        ignore.add('location')
        ignore.add('cacert')
        # Workaround for SAT-30769
        if 'content_default_http_proxy' not in attrs:
            ignore.add('content_default_http_proxy')
        return super().read(entity, attrs, ignore, params)


class Location(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Location entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'compute_resource': entity_fields.OneToManyField(AbstractComputeResource),
            'description': entity_fields.StringField(),
            'domain': entity_fields.OneToManyField(Domain),
            'environment': entity_fields.OneToManyField(Environment),
            'hostgroup': entity_fields.OneToManyField(HostGroup),
            'medium': entity_fields.OneToManyField(Media),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'parent': entity_fields.OneToOneField(Location),
            'provisioning_template': entity_fields.OneToManyField(ProvisioningTemplate),
            'realm': entity_fields.OneToManyField(Realm),
            'smart_proxy': entity_fields.OneToManyField(SmartProxy),
            'subnet': entity_fields.OneToManyField(Subnet),
            'user': entity_fields.OneToManyField(User),
        }
        self._meta = {'api_path': 'api/v2/locations'}
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'location': super().create_payload()}

    def create(self, create_missing=None):
        """Manually fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1216236
        <https://bugzilla.redhat.com/show_bug.cgi?id=1216236>`_.

        """
        attrs = self.create_json(create_missing)
        return type(self)(server_config=self._server_config, id=attrs['id']).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Work around a bug in the server's response.

        Do not read the ``realm`` attribute. See `Bugzilla #1216234
        <https://bugzilla.redhat.com/show_bug.cgi?id=1216234>`_.

        """
        if ignore is None:
            ignore = set()
        ignore.add('realm')
        return super().read(entity, attrs, ignore, params)

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
        return {'location': super().update_payload(fields)}


class Media(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Media entity.

    .. NOTE:: The ``path_`` field is named as such due to a naming conflict
        with :meth:`nailgun.entity_mixins.Entity.path`.
    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'path_': entity_fields.URLField(required=True),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'operatingsystem': entity_fields.OneToManyField(OperatingSystem),
            'organization': entity_fields.OneToManyField(Organization),
            'location': entity_fields.OneToManyField(Location),
            'os_family': entity_fields.StringField(choices=_OPERATING_SYSTEMS),
        }
        self._meta = {'api_path': 'api/v2/media'}
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict and rename ``path_``.

        For more information on wrapping submitted data, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        payload = super().create_payload()
        if 'path_' in payload:
            payload['path'] = payload.pop('path_')
        return {'medium': payload}

    def create(self, create_missing=None):
        """Manually fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1219653
        <https://bugzilla.redhat.com/show_bug.cgi?id=1219653>`_.

        """
        return type(self)(
            server_config=self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Rename ``path`` to ``path_``."""
        if attrs is None:
            attrs = self.read_json()
        attrs['path_'] = attrs.pop('path')
        return super().read(entity, attrs, ignore, params)

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
        payload = super().update_payload(fields)
        if 'path_' in payload:
            payload['path'] = payload.pop('path_')
        return {'medium': payload}


class Model(Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin, EntityUpdateMixin):
    """A representation of a Model entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'hardware_model': entity_fields.StringField(),
            'info': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'vendor_class': entity_fields.StringField(),
        }
        self._meta = {'api_path': 'api/v2/models'}
        super().__init__(server_config=server_config, **kwargs)


class OperatingSystem(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
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
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'ptable': entity_fields.OneToManyField(PartitionTable),
            'provisioning_template': entity_fields.OneToManyField(ProvisioningTemplate),
            'release_name': entity_fields.StringField(),
            'password_hash': entity_fields.StringField(
                choices=('MD5', 'SHA256', 'SHA512'),
                default='MD5',
            ),
            'title': entity_fields.StringField(),
            'os_parameters_attributes': entity_fields.ListField(),
        }
        self._meta = {
            'api_path': 'api/v2/operatingsystems',
        }
        super().__init__(server_config=server_config, **kwargs)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Fetch as many attributes as possible for this entity."""
        if attrs is None:
            attrs = self.read_json()
        if 'parameters' in attrs:
            attrs['os_parameters_attributes'] = attrs.pop('parameters')
        return super().read(entity, attrs, ignore, params)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'operatingsystem': super().create_payload()}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'operatingsystem': super().update_payload(fields)}


class OperatingSystemParameter(Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin):
    """A representation of a parameter for an operating system.

    ``organization`` must be passed in when this entity is instantiated.

    :raises: ``TypeError`` if ``operatingsystem`` is not passed in.
    """

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('operatingsystem', kwargs)
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'operatingsystem': entity_fields.OneToOneField(
                OperatingSystem, required=True, parent=True
            ),
            'value': entity_fields.StringField(required=True),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            "api_path": f'{self.operatingsystem.path("self")}/parameters',
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
        entity = entity or self.entity_with_parent()
        if ignore is None:
            ignore = set()
        ignore.add('operatingsystem')
        return super().read(entity, attrs, ignore, params)


class Organization(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of an Organization entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'compute_resource': entity_fields.OneToManyField(AbstractComputeResource),
            'description': entity_fields.StringField(),
            'domain': entity_fields.OneToManyField(Domain),
            'environment': entity_fields.OneToManyField(Environment),
            'hostgroup': entity_fields.OneToManyField(HostGroup),
            'label': entity_fields.StringField(str_type='alpha'),
            'medium': entity_fields.OneToManyField(Media),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'provisioning_template': entity_fields.OneToManyField(ProvisioningTemplate),
            'realm': entity_fields.OneToManyField(Realm),
            'redhat_repository_url': entity_fields.URLField(),
            'smart_proxy': entity_fields.OneToManyField(SmartProxy),
            'subnet': entity_fields.OneToManyField(Subnet),
            'title': entity_fields.StringField(),
            'user': entity_fields.OneToManyField(User),
            'simple_content_access': entity_fields.BooleanField(),
        }

        self._fields.update(
            {
                'default_content_view': entity_fields.OneToOneField(ContentView),
                'library': entity_fields.OneToOneField(LifecycleEnvironment),
            }
        )
        self._meta = {
            'api_path': 'katello/api/organizations',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        download_debug_certificate
            /organizations/<id>/download_debug_certificate
        simple_content_access/enable
            /organizations/<id>/simple_content_access/enable
        simple_content_access/disable
            /organizations/<id>/simple_content_access/disable
        simple_content_access/eligible
            /organizations/<id>/simple_content_access/eligible
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
        rh_cloud/report
           /organizations/<id>/report
        rh_cloud/inventory_sync
           /organizations/<id>/inventory_sync

        Otherwise, call ``super``.

        """
        if which in (
            'download_debug_certificate',
            'simple_content_access/enable',
            'simple_content_access/disable',
            'simple_content_access/eligible',
            'subscriptions',
            'subscriptions/delete_manifest',
            'subscriptions/manifest_history',
            'subscriptions/refresh_manifest',
            'subscriptions/upload',
            'sync_plans',
            'repo_discover',
        ):
            return f'{super().path(which="self")}/{which}'

        # Foreman Base Endpoints
        if which in ('rh_cloud/report', 'rh_cloud/inventory_sync'):
            self._meta = {'api_path': 'api/organizations'}
            return f'{super().path(which="self")}/{which}'

        return super().path(which)

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1230873
        <https://bugzilla.redhat.com/show_bug.cgi?id=1230873>`_.

        """
        return type(self)(
            server_config=self._server_config,
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
        return super().read(entity, attrs, ignore, params)

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
        org_payload = super().update_payload(fields)
        payload = {'organization': org_payload}
        if 'redhat_repository_url' in org_payload:
            rh_repo_url = org_payload.pop('redhat_repository_url')
            payload['redhat_repository_url'] = rh_repo_url
        return payload

    def download_debug_certificate(self, synchronous=True, timeout=None, **kwargs):
        """Get debug certificate for particular organization.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('download_debug_certificate'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def sca_enable(self, synchronous=True, timeout=None, **kwargs):
        """Enable simple content access mode for particular organization.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('simple_content_access/enable'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def repo_discover(self, synchronous=True, timeout=None, **kwargs):
        """Repo discovery.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('repo_discover'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def sca_disable(self, synchronous=True, timeout=None, **kwargs):
        """Disable simple content access mode for particular organization.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('simple_content_access/disable'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def sca_eligible(self, synchronous=True, timeout=None, **kwargs):
        """Determine if the organization is eligible for simple content access mode.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('simple_content_access/eligible'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def subscriptions(self, synchronous=True, timeout=None, **kwargs):
        """Get subscriptions from organization.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :returns: The server's response, with all content decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('subscriptions'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def rh_cloud_download_report(self, destination, **kwargs):
        """Download RHCloud Inventory report.

        :param destination: File path where report will be saved.
            e.g. robottelo_tmp_dir.joinpath(f'report_{gen_alphanumeric()}.tar.xz')
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('rh_cloud/report'), **kwargs)
        with open(destination, 'wb') as tarfile:
            tarfile.write(response.content)

    def rh_cloud_generate_report(self, synchronous=True, timeout=None, **kwargs):
        """Start RHCloud Inventory report generation process.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('rh_cloud/report'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def rh_cloud_inventory_sync(self, synchronous=True, timeout=None, **kwargs):
        """Start inventory synchronization.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('rh_cloud/inventory_sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def rh_cloud_fetch_last_report_log(self):
        """Fetch latest report log.

        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = {'headers': {'Accept': 'application/json'}}  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        url = f'{self._server_config.url}/foreman_inventory_upload/{self.id}/reports/last'
        return client.get(url, **kwargs).json()

    def rh_cloud_fetch_last_upload_log(self):
        """Fetch latest report log.

        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = {'headers': {'Accept': 'application/json'}}  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        url = f'{self._server_config.url}/foreman_inventory_upload/{self.id}/uploads/last'
        return client.get(url, **kwargs).json()


class OSDefaultTemplate(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a OS Default Template entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('operatingsystem', kwargs)
        self._fields = {
            'operatingsystem': entity_fields.OneToOneField(
                OperatingSystem, required=True, parent=True
            ),
            'provisioning_template': entity_fields.OneToOneField(ProvisioningTemplate),
            'template_kind': entity_fields.OneToOneField(TemplateKind),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            "api_path": f'{self.operatingsystem.path("self")}/os_default_templates',
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Fetch as many attributes as possible for this entity.

        Since operatingsystem is needed to instanciate, prepare the entity
        accordingly.
        """
        entity = entity or self.entity_with_parent()
        if ignore is None:
            ignore = set()
        ignore.add('operatingsystem')
        return super().read(entity, attrs, ignore, params)

    def update_payload(self, fields=None):
        """Wrap payload in ``os_default_template``.

        Relates to `Redmine #21169`_.

        .. _Redmine #21169: http://projects.theforeman.org/issues/21169
        """
        payload = super().update_payload(fields)
        return {'os_default_template': payload}


class OverrideValue(
    Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin, EntityUpdateMixin
):
    """A representation of a Override Value entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'match': entity_fields.StringField(required=True),
            'value': entity_fields.StringField(required=True),
            'smart_class_parameter': entity_fields.OneToOneField(SmartClassParameters, parent=True),
            'omit': entity_fields.BooleanField(),
        }
        super().__init__(server_config=server_config, **kwargs)
        # Create an override value for a specific smart class parameter
        if hasattr(self, 'smart_class_parameter'):
            partial_path = self.smart_class_parameter.path('self')
        else:
            raise TypeError(
                'A value must be provided for one of the following fields: '
                '"smart_class_parameter"'
            )
        self._meta = {
            'api_path': f'{partial_path}/override_values',
        }

    def create_payload(self):
        """Remove ``smart_class_parameter_id``."""
        payload = super().create_payload()
        if hasattr(self, 'smart_class_parameter'):
            del payload['smart_class_parameter_id']
        return payload

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Provide a default value for ``entity``.

        By default, ``nailgun.entity_mixins.EntityReadMixin.read provides a
        default value for ``entity`` like so::

            entity = type(self)()

        However, :class:`OverrideValue` requires that an
        ``smart_class_parameter`` be provided, so this
        technique will not work. Do this instead::

            entity = type(self)(
                smart_class_parameter=self.smart_class_parameter)

        """
        # read() should not change the state of the object it's called on, but
        # super() alters the attributes of any entity passed in. Creating a new
        # object and passing it to super() lets this one avoid changing state.
        entity = entity or self.entity_with_parent()
        if ignore is None:
            ignore = set()
        ignore.update(['smart_class_parameter'])
        return super().read(entity, attrs, ignore, params)


class Parameter(Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin, EntityUpdateMixin):
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
            'parameter_type': entity_fields.StringField(
                choices=('string', 'boolean', 'integer', 'real', 'array', 'hash', 'yaml', 'json')
            ),
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
        super().__init__(server_config=server_config, **kwargs)
        if not any(getattr(self, attr, None) for attr in self._path_fields):
            raise TypeError(f'Must provide value for any of "{self._path_fields.keys()}" fields.')

        self._parent_type = next(attr for attr in self._path_fields if getattr(self, attr, None))
        self._parent_id = getattr(self, self._parent_type).id
        self._meta = {
            'api_path': f'api/v2/{self._parent_type}s/{self._parent_id}/parameters',
        }

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Read parameter from server.

        Ignore path related fields as they're never returned by the server
        and are only added to entity to be able to use proper path.
        """
        entity = entity or self.entity_with_parent(**{self._parent_type: self._parent_id})
        if ignore is None:
            ignore = set()
        for field_name in self._path_fields:
            ignore.add(field_name)
        return super().read(entity, attrs, ignore, params)


class Permission(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Permission entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'resource_type': entity_fields.StringField(required=True),
        }
        self._meta = {
            'api_path': 'api/v2/permissions',
        }
        super().__init__(server_config=server_config, **kwargs)


class Ping(Entity, EntitySearchMixin):
    """A representation of a Ping entity."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {
            'api_path': 'katello/api/v2/ping',
        }
        super().__init__(server_config=server_config, **kwargs)


class Product(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Product entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'description': entity_fields.StringField(),
            'gpg_key': entity_fields.OneToOneField(ContentCredential),
            'label': entity_fields.StringField(),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'organization': entity_fields.OneToOneField(Organization, required=True),
            'repository': entity_fields.OneToManyField(Repository),
            'sync_plan': entity_fields.OneToOneField(SyncPlan),
        }
        self._meta = {
            'api_path': 'katello/api/v2/products',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        sync
            /products/<product_id>/sync

        ``super`` is called otherwise.

        """
        if which == "sync":
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

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
        if ignore is None:
            ignore = set()
        ignore.add('sync_plan')
        result = super().read(entity, attrs, ignore, params)
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
        """Search for entities with missing attribute.

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
            entity = self.entity_with_parent(**result)
            if sync_plan:
                entity.sync_plan = SyncPlan(
                    server_config=self._server_config,
                    id=sync_plan,
                    organization=Organization(
                        server_config=self._server_config, id=result.get('organization')
                    ),
                )
            entities.append(entity)
        if filters is not None:
            entities = self.search_filter(entities, filters)
        return entities

    def sync(self, synchronous=True, timeout=None, **kwargs):
        """Synchronize :class:`repositories <Repository>` in this product.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout=timeout)


class ProductBulkAction(Entity):
    """A representation of a Products bulk actions entity."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {
            'api_path': '/katello/api/products/bulk',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        destroy
            /products/bulk/destroy
        sync
            /products/bulk/sync
        sync_plan
            /products/bulk/sync_plan
        http_proxy
            /products/bulk/http_proxy
        verify_checksum
            /products/bulk/verify_checksum

        ``super`` is called otherwise.

        """
        if which in ("destroy", "sync", "sync_plan", "http_proxy", "verify_checksum"):
            return f'{super().path(which="base")}/{which}'
        return super().path(which)

    def destroy(self, synchronous=True, timeout=None, **kwargs):
        """Destroy one or more products.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('destroy'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def sync(self, synchronous=True, timeout=None, **kwargs):
        """Sync one or more products.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def http_proxy(self, synchronous=True, timeout=None, **kwargs):
        """Update the http proxy configuration on the repositories of one or more products.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('http_proxy'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def sync_plan(self, synchronous=True, timeout=None, **kwargs):
        """Sync one or more products.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('sync_plan'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def verify_checksum(self, synchronous=True, timeout=None, **kwargs):
        """Verify checksum for one or more products.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('verify_checksum'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class PartitionTable(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
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
                required=True, str_type='alpha', length=(4, 30), unique=True
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'os_family': entity_fields.StringField(choices=_OPERATING_SYSTEMS),
        }
        self._meta = {'api_path': 'api/v2/ptables'}
        super().__init__(server_config=server_config, **kwargs)


class PuppetClass(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntityUpdateMixin,
    EntitySearchMixin,
):
    """A representation of a Puppet Class entity."""

    def __init__(self, server_config=None, **kwargs):
        self._updatable_fields = ['name']
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'hostgroup': entity_fields.OneToManyField(HostGroup),
        }
        self._meta = {
            'api_path': 'foreman_puppet/api/puppetclasses',
        }
        super().__init__(server_config=server_config, **kwargs)

    def search_normalize(self, results):
        """Flatten results.

        :meth:`nailgun.entity_mixins.EntitySearchMixin.search_normalize`
        expects structure like
        list(dict_1(name: class_1), dict_2(name: class_2)),
        while Puppet Class entity returns dictionary with lists of subclasses
        split by main puppet class.
        """
        flattened_results = [item for sublist in results.values() for item in sublist]
        return super().search_normalize(flattened_results)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        smart_class_parameters
            /foreman_puppet/api/puppetclasses/:puppetclass_id/smart_class_parameters

        Otherwise, call ``super``.

        """
        if which in ("smart_class_parameters",):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def list_scparams(self, synchronous=True, timeout=None, **kwargs):
        """List of smart class parameters for a specific Puppet class.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('smart_class_parameters'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


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
        super().__init__(server_config=server_config, **kwargs)


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
        super().__init__(server_config=server_config, **kwargs)


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
        self._meta = {'api_path': 'katello/api/v2/module_streams'}
        super().__init__(server_config=server_config, **kwargs)


class CompliancePolicies(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Policy entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(4, 30), unique=True
            ),
            'description': entity_fields.StringField(),
            'scap_content_id': entity_fields.IntegerField(required=True),
            'scap_content_profile_id': entity_fields.IntegerField(required=True),
            'period': entity_fields.StringField(),  # (weekly, monthly, custom)
            'weekday': entity_fields.StringField(),  # (only if period == “weekly”)
            'day_of_month': entity_fields.IntegerField(),  # (only if period == “monthly”)
            'cron_line': entity_fields.StringField(),  # (only if period == “custom”)
            'hostgroup': entity_fields.OneToManyField(HostGroup),
            'host': entity_fields.OneToManyField(Host),
            'tailoring_file_id': entity_fields.IntegerField(),
            'tailoring_file_profile_id': entity_fields.IntegerField(),
            'deploy_by': entity_fields.StringField(choices=('puppet', 'ansible', 'manual')),
            'location': entity_fields.OneToManyField(Location),
            'organization': entity_fields.OneToManyField(Organization),
        }
        self._meta = {'api_path': 'api/v2/compliance/policies'}
        super().__init__(server_config=server_config, **kwargs)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1746934
        <https://bugzilla.redhat.com/show_bug.cgi?id=1746934>`_.

        """
        self.update_json(fields)
        return self.read()


class Realm(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Realm entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
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
        self._meta = {'api_path': 'api/v2/realms'}
        super().__init__(server_config=server_config, **kwargs)

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1232855
        <https://bugzilla.redhat.com/show_bug.cgi?id=1232855>`_.

        """
        return type(self)(
            server_config=self._server_config,
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
        self._meta = {'api_path': 'foreman_tasks/api/recurring_logics'}
        super().__init__(server_config=server_config, **kwargs)

    def cancel(self, synchronous=True, timeout=None, **kwargs):
        """Cancel a recurring logic.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('cancel'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.RecurringLogic.path``.

        The format of the returned path depends on the value of ``which``:

        cancel
            /foreman_tasks/api/recurring_logics/:id/cancel

        Otherwise, call ``super``.

        """
        if which in ("cancel",):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)


class RegistrationCommand(Entity, EntityCreateMixin, EntityReadMixin):
    """A representation of a Registration Command entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'smart_proxy': entity_fields.OneToOneField(SmartProxy),
            'organization': entity_fields.OneToOneField(Organization, required=True),
            'location': entity_fields.OneToOneField(Location, required=True),
            'lifecycle_environment': entity_fields.OneToOneField(LifecycleEnvironment),
            'activation_key': entity_fields.OneToOneField(ActivationKey),
            'activation_keys': entity_fields.OneToManyField(ActivationKey),
            'operatingsystem': entity_fields.OneToOneField(OperatingSystem),
            'hostgroup': entity_fields.OneToOneField(HostGroup),
            'insecure': entity_fields.BooleanField(default=True, required=True),
            'setup_insights': entity_fields.BooleanField(default=False),
            'setup_remote_execution': entity_fields.BooleanField(default=True),
            'setup_remote_execution_pull': entity_fields.BooleanField(default=False),
            'remote_execution_interface': entity_fields.StringField(default=''),
            'jwt_expiration': entity_fields.IntegerField(default=4),
            'repo': entity_fields.StringField(default=''),
            'repo_gpg_key_url': entity_fields.URLField(default=''),
            'packages': entity_fields.StringField(),
            'update_packages': entity_fields.BooleanField(default=False),
            'force': entity_fields.BooleanField(default=False),
            'ignore_subman_errors': entity_fields.BooleanField(default=False),
            'repo_data': entity_fields.ListField(),
            'download_utility': entity_fields.StringField(default='curl', choices=('curl', 'wget')),
        }

        self._meta = {'api_path': '/api/registration_commands'}
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        In addition, rename the ``activation_keys_ids`` field to ``activation_keys``.

        """
        payload = super().create_payload()
        if 'activation_keys_ids' in payload:
            payload['activation_keys'] = payload.pop('activation_keys_ids')
        return payload

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Read registration command from server.

        Override :meth:`nailgun.entity_mixins.EntityReadMixin.read` to ignore
        all the fields and returns 'registration_command' output in dict.
        """
        if attrs is None:
            attrs = self.read_json()
        return attrs['registration_command']


class RegistrationTokens(Entity, EntityDeleteMixin):
    """A representation of Registration Token entity."""

    def __init__(self, server_config=None, user=None, **kwargs):
        self._fields = {
            'location': entity_fields.OneToManyField(Location),
            'organization': entity_fields.OneToManyField(Organization),
        }
        api_path = f'api/users/{user}/registration_tokens' if user else 'api/registration_tokens'
        self._meta = {'api_path': api_path}
        super().__init__(server_config=server_config, **kwargs)

    def invalidate(self, synchronous=True, timeout=None, **kwargs):
        """Invalidate tokens for a single user."""
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.delete(self.path(), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def invalidate_multiple(self, synchronous=True, timeout=None, search=None, **kwargs):
        """Invalidate tokens for multiple users."""
        kwargs = kwargs.copy()
        if search:
            kwargs['params'] = {'search': search}
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.delete(self.path(), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class Report(Entity):
    """A representation of a Report entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'host': entity_fields.StringField(required=True),
            'logs': entity_fields.ListField(),
            'reported_at': entity_fields.DateTimeField(required=True),
        }
        self._meta = {'api_path': 'api/v2/reports'}
        super().__init__(server_config=server_config, **kwargs)


class Repository(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Repository entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'ansible_collection_auth_url': entity_fields.StringField(),
            'ansible_collection_auth_token': entity_fields.StringField(),
            'ansible_collection_requirements': entity_fields.StringField(),
            'backend_identifier': entity_fields.StringField(),
            'checksum_type': entity_fields.StringField(
                choices=('sha1', 'sha256'),
            ),
            'content_counts': entity_fields.DictField(),
            'content_type': entity_fields.StringField(
                choices=('puppet', 'yum', 'file', 'docker', 'ostree', 'deb'),
                default='yum',
                required=True,
            ),
            'is_container_push': entity_fields.BooleanField(default=False),
            'container_repository_name': entity_fields.StringField(),
            # Just setting `str_type='alpha'` will fail with this error:
            # {"docker_upstream_name":["must be a valid docker name"]}}
            'docker_upstream_name': entity_fields.StringField(default='busybox'),
            'include_tags': entity_fields.StringField(),
            'download_policy': entity_fields.StringField(
                choices=('background', 'immediate', 'on_demand'),
                default='immediate',
            ),
            'full_path': entity_fields.StringField(),
            'gpg_key': entity_fields.OneToOneField(ContentCredential),
            'ssl_ca_cert': entity_fields.OneToOneField(ContentCredential),
            'ignorable_content': entity_fields.ListField(),
            'label': entity_fields.StringField(),
            'last_sync': entity_fields.OneToOneField(ForemanTask),
            'mirroring_policy': entity_fields.StringField(
                choices=('additive', 'mirror_content_only', 'mirror_complete'),
                default='additive',
            ),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'organization': entity_fields.OneToOneField(Organization),
            'product': entity_fields.OneToOneField(Product, required=True),
            'retain_package_versions_count': entity_fields.StringField(),
            'unprotected': entity_fields.BooleanField(),
            'url': entity_fields.URLField(
                default=_FAKE_YUM_REPO,
                required=True,
            ),
            'upstream_username': entity_fields.StringField(),
            'upstream_password': entity_fields.StringField(),
            'verify_ssl_on_sync': entity_fields.BooleanField(),
            'http_proxy_policy': entity_fields.StringField(
                choices=('global_default_http_proxy', 'none', 'use_selected_http_proxy')
            ),
            'http_proxy_id': entity_fields.IntegerField(),
            'deb_releases': entity_fields.StringField(),
            'deb_components': entity_fields.StringField(),
            'deb_architectures': entity_fields.StringField(),
            'download_concurrency': entity_fields.IntegerField(),
        }
        if self._fields['content_type'].choices == 'yum':
            self._fields['download_policy'].required = True
        self._meta = {
            'api_path': 'katello/api/v2/repositories',
        }
        if kwargs.get('content_type') == 'deb':
            self._fields['deb_releases'].default = 'stable'
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        docker_manifests
            /repositories/<id>/docker_manifests
        docker_manifest_lists
            /repositories/<id>/docker_manifest_lists
        errata
            /repositories/<id>/errata
        files
            /repositories/<id>/files
        packages
            /repositories/<id>/packages
        module_streams
            /repositories/<id>/module_streams
        remove_content
            /repositories/<id>/remove_content
        sync
            /repositories/<id>/sync
        verify_checksum
            /repositories/<id>/verify_checksum
        upload_content
            /repositories/<id>/upload_content
        import_uploads
            /repositories/<id>/import_uploads

        ``super`` is called otherwise.

        """
        if which in (
            'docker_manifests',
            'docker_manifest_lists',
            'errata',
            'files',
            'packages',
            'module_streams',
            'remove_content',
            'sync',
            'verify_checksum',
            'import_uploads',
            'upload_content',
        ):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Read repository from server.

        Ignore ``organization`` field as it's never returned by the server
        and is only added to entity to be able to use organization path
        dependent helpers and also upstream_password as it is not returned
        for security reasons.
        """
        if ignore is None:
            ignore = set()
        ignore.add('organization')
        ignore.add('upstream_password')
        ignore.add('mirror_on_sync')
        ignore.add('download_concurrency')
        return super().read(entity, attrs, ignore, params)

    def create_missing(self):
        """Conditionally mark ``docker_upstream_name`` as required.

        Mark ``docker_upstream_name`` as required if ``content_type`` is
        "docker".

        """
        if getattr(self, 'content_type', '') == 'docker':
            self._fields['docker_upstream_name'].required = True
        super().create_missing()

    def docker_manifests(self, synchronous=True, timeout=None, **kwargs):
        """List docker manifests inside repository.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('docker_manifests'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def docker_manifest_lists(self, synchronous=True, timeout=None, **kwargs):
        """List docker manifest lists inside repository.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('docker_manifest_lists'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def delete_with_args(self, synchronous=True, timeout=None, **kwargs):
        """Delete a repository, and respect args passed to it.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.delete(self.path(), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def errata(self, synchronous=True, timeout=None, **kwargs):
        """List errata inside repository.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('errata'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def sync(self, synchronous=True, timeout=None, **kwargs):
        """Sync an existing repository.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def verify_checksum(self, synchronous=True, timeout=None, **kwargs):
        """Verify checksum of repository contents.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('verify_checksum'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def upload_content(self, synchronous=True, timeout=None, **kwargs):
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
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
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
        json = _handle_response(response, self._server_config, synchronous, timeout)
        if json['status'] != 'success':
            raise APIResponseError(
                f'Received error when uploading file {kwargs.get("files")} '
                f'to repository {self.id}: {json}'
            )
        return json

    def import_uploads(
        self,
        content_type=None,
        uploads=None,
        upload_ids=None,
        synchronous=True,
        timeout=None,
        **kwargs,
    ):
        """Import uploads into a repository.

        It expects either a list of uploads or upload_ids (but not both).

        :param content_type: content type (`deb`, `docker_manifest`, `file`, `ostree`,
                `rpm`, `srpm`)
        :param uploads: Array of uploads to be imported
        :param upload_ids: Array of upload ids to be imported
        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        if uploads:
            data = {'uploads': uploads, 'content_type': content_type}
        elif upload_ids:
            data = {'upload_ids': upload_ids, 'content_type': content_type}
        response = client.put(self.path('import_uploads'), data, **kwargs)
        json = _handle_response(response, self._server_config, synchronous, timeout)
        return json

    def remove_content(self, synchronous=True, timeout=None, **kwargs):
        """Remove content from a repository.

        It expects content/packages/docker manifests ids sent as data.
        Here is an example of how to use this method::

            repository.remove_content(data={'ids': [package.id]})

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('remove_content'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def packages(self, synchronous=True, timeout=None, **kwargs):
        """List packages associated with repository.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('packages'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def module_streams(self, synchronous=True, timeout=None, **kwargs):
        """List module_streams associated with repository.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('module_streams'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def files(self, synchronous=True, timeout=None, **kwargs):
        """List files associated with repository.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('files'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class RepositorySet(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Repository Set entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'contentUrl': entity_fields.URLField(required=True),
            'gpgUrl': entity_fields.URLField(required=True),
            'label': entity_fields.StringField(required=True),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'organization': entity_fields.OneToOneField(
                Organization,
                required=True,
            ),
            'product': entity_fields.OneToOneField(Product, required=True, parent=True),
            'repositories': entity_fields.OneToManyField(Repository),
            'type': entity_fields.StringField(
                choices=('kickstart', 'yum', 'file'),
                default='yum',
                required=True,
            ),
            'vendor': entity_fields.StringField(required=True),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            'api_path': 'katello/api/v2/repository_sets',
        }

    def available_repositories(self, **kwargs):
        """List available repositories for the repository set.

        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        if 'data' not in kwargs:
            kwargs['data'] = {}
            kwargs['data']['product_id'] = self.product.id
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('available_repositories'), **kwargs)
        return _handle_response(response, self._server_config)

    def enable(self, synchronous=True, timeout=None, **kwargs):
        """Enable a RedHat Repository.

        RedHat repos needs to be enabled first, so that we can sync it.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        if 'data' not in kwargs:
            kwargs['data'] = {}
            kwargs['data']['product_id'] = self.product.id
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('enable'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def disable(self, synchronous=True, timeout=None, **kwargs):
        """Disables a RedHat Repository.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        if 'data' not in kwargs:
            kwargs['data'] = {}
            kwargs['data']['product_id'] = self.product.id
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('disable'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

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
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

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
        entity = entity or self.entity_with_parent()
        if ignore is None:
            ignore = set()
        return super().read(entity, attrs, ignore, params)


class RHCIDeployment(
    Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin, EntityUpdateMixin
):
    """A representation of a RHCI deployment entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'deploy_rhev': entity_fields.BooleanField(required=True),
            'lifecycle_environment': entity_fields.OneToOneField(
                LifecycleEnvironment, required=True
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
        }
        super().__init__(server_config=server_config, **kwargs)

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
        return super().read(entity, attrs, ignore, params)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        deploy
            /deployments/<id>/deploy

        ``super`` is called otherwise.

        """
        if which == "deploy":
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def deploy(self, synchronous=True, timeout=None, **kwargs):
        """Kickoff the RHCI deployment.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('deploy'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class RHCloud(Entity):
    """A representation of a RHCloud entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'organization': entity_fields.OneToOneField(Organization),
            'location': entity_fields.OneToOneField(Location),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {'api_path': 'api/v2/rh_cloud'}

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``."""
        if which in ("enable_connector", "advisor_engine_config"):
            return f'{super().path(which="base")}/{which}'
        return super().path(which)

    def enable_connector(self, synchronous=True, timeout=None, **kwargs):
        """Enable RH Cloud connector."""
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        kwargs['data'] = {}
        if data := _payload(self.get_fields(), self.get_values()):
            kwargs['data'] = data
        response = client.post(self.path('enable_connector'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def advisor_engine_config(self, synchronous=True, timeout=None, **kwargs):
        """Get advisor engine configuration information."""
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('advisor_engine_config'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class RoleLDAPGroups(Entity):
    """A representation of a Role LDAP Groups entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
        }
        self._meta = {
            'api_path': 'katello/api/v2/roles/:role_id/ldap_groups',
        }
        super().__init__(server_config=server_config, **kwargs)


class Role(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Role entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'filters': entity_fields.OneToManyField(Filter),
            'location': entity_fields.OneToManyField(Location),
            'name': entity_fields.StringField(
                required=True,
                str_type='alphanumeric',
                length=(2, 30),  # min length is 2 and max length is arbitrary
                unique=True,
            ),
            'organization': entity_fields.OneToManyField(Organization),
        }
        self._meta = {
            'api_path': 'api/v2/roles',
        }
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'role': super().create_payload()}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'role': super().update_payload(fields)}

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        clone
            /api/roles/:role_id/clone

        Otherwise, call ``super``.

        """
        if which == "clone":
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def clone(self, synchronous=True, timeout=None, **kwargs):
        """Clone an existing Role.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('clone'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


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
        }
        super().__init__(server_config=server_config, **kwargs)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Read setting from server.

        Override :meth:`nailgun.entity_mixins.EntityReadMixin.read` to ignore
        the ``created_at and updated_at``.
        """
        if ignore is None:
            ignore = set()
        ignore.add('created_at')
        ignore.add('updated_at')
        return super().read(entity, attrs, ignore, params)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'setting': super().update_payload(fields)}


class SmartProxy(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Smart Proxy entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'download_policy': entity_fields.StringField(
                choices=('on_demand', 'immediate', 'inherit', 'streamed'),
                default='on_demand',
            ),
            'http_proxy': entity_fields.OneToOneField(HTTPProxy),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'url': entity_fields.URLField(required=True),
            'location': entity_fields.OneToManyField(Location),
            'organization': entity_fields.OneToManyField(Organization),
        }
        self._meta = {
            'api_path': 'api/v2/smart_proxies',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        refresh
            /api/smart_proxies/:id/refresh

        Otherwise, call ``super``.

        """
        if which in ("refresh",):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def refresh(self, synchronous=True, timeout=None, **kwargs):
        """Refresh Capsule features.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('refresh'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def import_puppetclasses(self, synchronous=True, timeout=None, **kwargs):
        """Import puppet classes from puppet Capsule.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
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
            path = f'{self.path()}/environments/{environment_id}/import_puppetclasses'
        else:
            path = f'{self.path()}/import_puppetclasses'
        return _handle_response(
            client.post(path, **kwargs), self._server_config, synchronous, timeout
        )

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Ignore ``download_policy`` field as it's never returned by the server.

        For more information, see `Bugzilla #1486609
        <https://bugzilla.redhat.com/show_bug.cgi?id=1486609>`_.
        """
        if ignore is None:
            ignore = set()
        ignore.add('download_policy')
        ignore.add('http_proxy')
        return super().read(entity, attrs, ignore, params)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1262037
        <https://bugzilla.redhat.com/show_bug.cgi?id=1262037>`_.

        """
        self.update_json(fields)
        return self.read()

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'smart_proxy': super().update_payload(fields)}


class SmartClassParameters(Entity, EntityReadMixin, EntitySearchMixin, EntityUpdateMixin):
    """A representation of a Smart Class Parameters."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'puppetclass': entity_fields.OneToOneField(PuppetClass),
            'override': entity_fields.BooleanField(),
            'description': entity_fields.StringField(),
            'default_value': entity_fields.StringField(),
            'hidden_value': entity_fields.BooleanField(),
            'hidden_value?': entity_fields.BooleanField(),
            'omit': entity_fields.BooleanField(),
            'validator_type': entity_fields.StringField(choices=('regexp', 'list')),
            'validator_rule': entity_fields.StringField(),
            'parameter': entity_fields.StringField(),
            'parameter_type': entity_fields.StringField(
                choices=('string', 'boolean', 'integer', 'real', 'array', 'hash', 'yaml', 'json')
            ),
            'required': entity_fields.BooleanField(),
            'merge_overrides': entity_fields.BooleanField(),
            'merge_default': entity_fields.BooleanField(),
            'avoid_duplicates': entity_fields.BooleanField(),
            'override_value_order': entity_fields.StringField(),
            'override_values': entity_fields.DictField(),
        }
        self._meta = {
            'api_path': 'foreman_puppet/api/smart_class_parameters',
        }
        super().__init__(server_config=server_config, **kwargs)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Do not read the ``hidden_value`` attribute."""
        if ignore is None:
            ignore = set()
        ignore.add('hidden_value')
        return super().read(entity, attrs, ignore, params)


class Snapshot(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
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
    Snapshot(host=<host_id>, id=<snapshot_id>).delete().
    """

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('host', kwargs)
        self._fields = {
            'name': entity_fields.StringField(required=True),
            'description': entity_fields.StringField(required=False),
            'host': entity_fields.OneToOneField(Host, required=True, parent=True),
            'include_ram': entity_fields.BooleanField(required=False),
            'quiesce': entity_fields.BooleanField(required=False),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {
            'api_path': f'{self.host.path("self")}/snapshots',
        }

    def path(self, which=None):
        """Extend nailgun.entity_mixins.Entity.path.

        revert
        /api/v2/hosts/<host-id>/snapshots/<snapshot-id>/revert.
        """
        if which == "revert":
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

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
        entity = entity or self.entity_with_parent()
        if ignore is None:
            ignore = set()
        ignore.add('host')
        ignore.add('include_ram')
        ignore.add('quiesce')
        return super().read(entity, attrs, ignore, params)

    def search_normalize(self, results):
        """Append host id to search results to initialize found :class:`Snapshot` successfully."""
        for snapshot in results:
            snapshot['host_id'] = self.host.id
        return super().search_normalize(results)

    def revert(self, **kwargs):
        """Rollback the Snapshot.

        Makes HTTP PUT call to revert the snapshot.
        """
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('revert'), **kwargs)
        return _handle_response(response, self._server_config)


class SSHKey(Entity, EntityCreateMixin, EntityDeleteMixin, EntityReadMixin, EntitySearchMixin):
    """A representation of a SSH Key entity.

    ``user`` must be passed in when this entity is instantiated.

    :raises: ``TypeError`` if ``user`` is not passed in.
    """

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('user', kwargs)
        self._fields = {
            'user': entity_fields.OneToOneField(User, required=True, parent=True),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'key': entity_fields.StringField(required=True, str_type='alphanumeric', unique=True),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {'api_path': f'{self.user.path()}/ssh_keys'}

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
        entity = entity or self.entity_with_parent()
        if ignore is None:
            ignore = set()
        ignore.add('user')
        return super().read(entity, attrs, ignore, params)

    def search_normalize(self, results):
        """Append user id to search results to initialize found :class:`User` successfully."""
        for sshkey in results:
            sshkey['user_id'] = self.user.id
        return super().search_normalize(results)


class Status(Entity):
    """A representation of a Status entity."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {
            'api_path': 'katello/api/v2/status',
        }
        super().__init__(server_config=server_config, **kwargs)


class Subnet(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Subnet entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'boot_mode': entity_fields.StringField(
                choices=(
                    'Static',
                    'DHCP',
                ),
                default='DHCP',
            ),
            'cidr': entity_fields.IntegerField(),
            'description': entity_fields.StringField(),
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
            'httpboot': entity_fields.OneToOneField(SmartProxy),
            'ipam': entity_fields.StringField(
                choices=('DHCP', 'Internal DB'),
                default='DHCP',
            ),
            'location': entity_fields.OneToManyField(Location),
            'mask': entity_fields.NetmaskField(required=True),
            'mtu': entity_fields.IntegerField(min_val=68, max_val=4294967295),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'network': entity_fields.IPAddressField(required=True),
            'network_type': entity_fields.StringField(
                choices=('IPv4', 'IPv6'),
                default='IPv4',
            ),
            'organization': entity_fields.OneToManyField(Organization),
            'remote_execution_proxy': entity_fields.OneToManyField(SmartProxy),
            'subnet_parameters_attributes': entity_fields.ListField(),
            'template': entity_fields.OneToOneField(SmartProxy),
            'to': entity_fields.IPAddressField(),
            'tftp': entity_fields.OneToOneField(SmartProxy),
            'vlanid': entity_fields.StringField(),
        }
        self._meta = {'api_path': 'api/v2/subnets'}
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        In addition, rename the ``from_`` field to ``from``.

        """
        payload = super().create_payload()
        if 'from_' in payload:
            payload['from'] = payload.pop('from_')
        return {'subnet': payload}

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
        return super().read(entity, attrs, ignore, params)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        payload = super().update_payload(fields)
        if 'from_' in payload:
            payload['from'] = payload.pop('from_')
        return {'subnet': payload}


class Subscription(Entity, EntityReadMixin, EntitySearchMixin):
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
        }
        super().__init__(server_config=server_config, **kwargs)

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
        if which in ('delete_manifest', 'manifest_history', 'refresh_manifest', 'upload'):
            _check_for_value('organization', self.get_values())
            return self.organization.path(f'subscriptions/{which}')
        return super().path(which)

    def _org_path(self, which, payload):
        """Generate paths with organization IDs in them.

        :param which: A path such as "manifest_history" that has an
            organization ID in it.
        :param payload: A dict with an "organization_id" key in it.
        :returns: A string. The requested path.

        """
        return Subscription(
            server_config=self._server_config,
            organization=payload['organization_id'],
        ).path(which)

    def delete_manifest(self, synchronous=True, timeout=1500, **kwargs):
        """Delete manifest from Red Hat provider.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self._org_path('delete_manifest', kwargs['data']), **kwargs)
        return _handle_response(
            response,
            self._server_config,
            synchronous,
            timeout=timeout,
        )

    def manifest_history(self, synchronous=True, timeout=None, **kwargs):
        """Obtain manifest history for subscriptions.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self._org_path('manifest_history', kwargs['data']), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Read subscription from server.

        Ignore ``organization`` field as it's never returned by the server
        and is only added to entity to be able to use organization path
        dependent helpers.
        """
        if ignore is None:
            ignore = set()
        ignore.add('organization')
        return super().read(entity, attrs, ignore, params)

    def refresh_manifest(self, synchronous=True, timeout=1500, **kwargs):
        """Refresh previously imported manifest for Red Hat provider.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self._org_path('refresh_manifest', kwargs['data']), **kwargs)
        return _handle_response(
            response,
            self._server_config,
            synchronous,
            timeout=timeout,
        )

    def upload(self, synchronous=True, timeout=1500, **kwargs):
        """Upload a subscription manifest.

        Here is an example of how to use this method::

            with open('my_manifest.zip') as manifest:
                sub.upload({'organization_id': org.id}, manifest)

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self._org_path('upload', kwargs['data']), **kwargs)
        # Setting custom timeout as manifest upload can take enormously huge
        # amount of time. See BZ#1339696 for more details
        return _handle_response(
            response,
            self._server_config,
            synchronous,
            timeout=timeout,
        )


class SyncPlan(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
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
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'cron_expression': entity_fields.StringField(str_type='alpha'),
            'organization': entity_fields.OneToOneField(Organization, required=True, parent=True),
            'product': entity_fields.OneToManyField(Product),
            'sync_date': entity_fields.DateTimeField(required=True),
            'foreman_tasks_recurring_logic': entity_fields.OneToOneField(RecurringLogic),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {'api_path': f'{self.organization.path()}/sync_plans'}

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
        entity = entity or self.entity_with_parent()
        if ignore is None:
            ignore = set()
        ignore.add('organization')
        return super().read(entity, attrs, ignore, params)

    def create_payload(self):
        """Convert ``sync_date`` to a string.

        The ``sync_date`` instance attribute on the current object is not
        affected. However, the ``'sync_date'`` key in the dict returned by
        ``create_payload`` is a string.

        """
        data = super().create_payload()
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
        if which in ("add_products", "remove_products"):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def add_products(self, synchronous=True, timeout=None, **kwargs):
        """Add products to this sync plan.

        .. NOTE:: The ``synchronous`` argument has no effect in certain
            versions of Satellite. See `Bugzilla #1199150
            <https://bugzilla.redhat.com/show_bug.cgi?id=1199150>`_.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('add_products'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def remove_products(self, synchronous=True, timeout=None, **kwargs):
        """Remove products from this sync plan.

        .. NOTE:: The ``synchronous`` argument has no effect in certain
            versions of Satellite. See `Bugzilla #1199150
            <https://bugzilla.redhat.com/show_bug.cgi?id=1199150>`_.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('remove_products'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def update_payload(self, fields=None):
        """Convert ``sync_date`` to a string if datetime object provided."""
        data = super().update_payload(fields)
        if isinstance(data.get('sync_date'), datetime):
            data['sync_date'] = data['sync_date'].strftime('%Y-%m-%d %H:%M:%S')
        return data


class TailoringFile(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Tailoring File entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(4, 30), unique=True
            ),
            'scap_file': entity_fields.StringField(),
            'original_filename': entity_fields.StringField(),
            'tailoring_file_profiles': entity_fields.StringField(),
            'location': entity_fields.OneToManyField(Location),
            'organization': entity_fields.OneToManyField(Organization),
        }
        if 'scap_file' in kwargs:
            with open(kwargs['scap_file']) as input_file:
                kwargs['scap_file'] = input_file.read()
        self._meta = {'api_path': 'api/v2/compliance/tailoring_files'}
        super().__init__(server_config=server_config, **kwargs)

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1381129
        <https://bugzilla.redhat.com/show_bug.cgi?id=1381129>`_.

        """
        return type(self)(
            server_config=self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def create_payload(self, **kwargs):
        """Wrap submitted data within an extra dict."""
        return {'tailoring_file': super().create_payload()}

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Ignore ``scap_file`` field."""
        if ignore is None:
            ignore = set()
        ignore.update(['scap_file'])
        return super().read(entity, attrs, ignore, params)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1234964
        <https://bugzilla.redhat.com/show_bug.cgi?id=1234964>`_.

        """
        self.update_json(fields)
        return self.read()


class Template(Entity):
    """A representation of a Template entity."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {
            'api_path': 'api/v2/templates',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        import
            /templates/import
        export
            /templates/export

        """
        if which:
            return f'{super().path(which="base")}/{which}'
        return super().path(which)

    def imports(self, synchronous=True, timeout=None, **kwargs):
        """Import templates.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('import'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def exports(self, synchronous=True, timeout=None, **kwargs):
        """Export templates.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('export'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class TemplateCombination(Entity, EntityDeleteMixin, EntityReadMixin):
    """A representation of a Template Combination entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'environment': entity_fields.OneToOneField(Environment),
            'hostgroup': entity_fields.OneToOneField(HostGroup),
            'provisioning_template': entity_fields.OneToOneField(
                ProvisioningTemplate,
                required=True,
            ),
        }
        self._meta = {
            'api_path': 'api/v2/template_combinations',
        }
        super().__init__(server_config=server_config, **kwargs)


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
        }
        super().__init__(server_config=server_config, **kwargs)


class UserGroup(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a User Group entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'admin': entity_fields.BooleanField(),
            'name': entity_fields.StringField(
                required=True, str_type='alpha', length=(6, 12), unique=True
            ),
            'role': entity_fields.OneToManyField(Role),
            'user': entity_fields.OneToManyField(User),
            'usergroup': entity_fields.OneToManyField(UserGroup),
        }
        self._meta = {'api_path': 'api/v2/usergroups'}
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'usergroup': super().create_payload()}

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'usergroup': super().update_payload(fields)}

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1301658
        <https://bugzilla.redhat.com/show_bug.cgi?id=1301658>`_.

        """
        return type(self)(
            server_config=self._server_config,
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
            response = client.put(self.path('self'), {}, **self._server_config.get_client_kwargs())
            response.raise_for_status()
            attrs['admin'] = response.json()['admin']
        return super().read(entity, attrs, ignore, params)


class User(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
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
                default=AuthSourceLDAP(server_config=server_config, id=1),
                required=True,
            ),
            'auth_source_name': entity_fields.StringField(),
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
        }
        super().__init__(server_config=server_config, **kwargs)

    def create_payload(self):
        """Wrap submitted data within an extra dict.

        For more information, see `Bugzilla #1151220
        <https://bugzilla.redhat.com/show_bug.cgi?id=1151220>`_.

        """
        return {'user': super().create_payload()}

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Do not read the ``password`` argument."""
        if ignore is None:
            ignore = set()
        ignore.add('password')
        return super().read(entity, attrs, ignore, params)

    def update_payload(self, fields=None):
        """Wrap submitted data within an extra dict."""
        return {'user': super().update_payload(fields)}

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
    EntityUpdateMixin,
):
    """A representation of a VirtWho Config entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'blacklist': entity_fields.StringField(),
            'debug': entity_fields.BooleanField(),
            'exclude_host_parents': entity_fields.StringField(),
            'filter_host_parents': entity_fields.StringField(),
            'filtering_mode': entity_fields.IntegerField(
                choices=[0, 1, 2], default=0, required=True
            ),
            'http_proxy': entity_fields.OneToOneField(HTTPProxy),
            'http_proxy_id': entity_fields.IntegerField(),
            'hypervisor_id': entity_fields.StringField(
                choices=['hostname', 'uuid', 'hwuuid'], default='hostname', required=True
            ),
            'hypervisor_password': entity_fields.StringField(),
            'hypervisor_server': entity_fields.StringField(),
            'hypervisor_type': entity_fields.StringField(
                choices=['esx', 'hyperv', 'libvirt', 'kubevirt', 'ahv'],
                default='libvirt',
                required=True,
            ),
            'hypervisor_username': entity_fields.StringField(),
            'interval': entity_fields.IntegerField(
                choices=[60, 120, 240, 480, 720, 1440, 2880, 4320], default=120, required=True
            ),
            'name': entity_fields.StringField(required=True),
            'no_proxy': entity_fields.StringField(),
            'organization_id': entity_fields.IntegerField(),
            'satellite_url': entity_fields.StringField(required=True),
            'status': entity_fields.StringField(),
            'whitelist': entity_fields.StringField(),
            'prism_flavor': entity_fields.StringField(
                choices=['central', 'element'], default='element'
            ),
            'kubeconfig_path': entity_fields.StringField(),
            'ahv_internal_debug': entity_fields.BooleanField(),
        }
        self._meta = {
            'api_path': 'foreman_virt_who_configure/api/v2/configs',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        deploy_script
            /foreman_virt_who_configure/api/v2/configs/:id/deploy_script

        configs
            /foreman_virt_who_configure/api/v2/organizations/:organization_id/configs

        ``super`` is called otherwise.

        """
        if which and which in ("deploy_script"):
            return f'{super().path(which="self")}/{which}'
        if which and which in ("configs"):
            return (
                f'{self._server_config.url}/'
                f'foreman_virt_who_configure/api/v2/organizations/'
                f"{self.read(ignore={'http_proxy'}).organization_id}/"
                f'{which}'
            )
        return super().path(which)

    def create_payload(self):
        """Wrap config in extra dict."""
        return {'foreman_virt_who_configure_config': super().create_payload()}

    def update_payload(self, fields=None):
        """Wrap config in extra dict."""
        return {'foreman_virt_who_configure_config': super().update_payload(fields)}

    def deploy_script(self, synchronous=True, timeout=None, **kwargs):
        """Deploy script for a VirtWho Config.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('deploy_script'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Read subscription from server.

        Override :meth:`nailgun.entity_mixins.EntityReadMixin.read` to ignore
        the ``hypervisor_password``.
        """
        if not ignore:
            ignore = set()
        ignore.add('hypervisor_password')
        ignore.add('http_proxy_id')
        return super().read(entity, attrs, ignore, params)

    def get_organization_configs(self, synchronous=True, timeout=None, **kwargs):
        """Get all virt-who configurations per organization.

        Unusually, the ``/foreman_virt_who_configure/api/v2/organizations/
        :organization_id/configs`` path is totally unsupported.
        Support to List of virt-who configurations per organization.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('configs'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class ScapContents(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a ScapContents entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'title': entity_fields.StringField(required=True),
            'scap_file': entity_fields.StringField(required=True),
            'original_filename': entity_fields.StringField(),
            'location': entity_fields.OneToManyField(Location),
            'organization': entity_fields.OneToManyField(Organization),
            'scap_content_profiles': entity_fields.StringField(),
        }
        if 'scap_file' in kwargs:
            with open(kwargs['scap_file']) as input_file:
                kwargs['scap_file'] = input_file.read()
        self._meta = {
            'api_path': 'api/compliance/scap_contents',
        }
        super().__init__(server_config=server_config, **kwargs)

    def create(self, create_missing=None):
        """Do extra work to fetch a complete set of attributes for this entity.

        For more information, see `Bugzilla #1381129
        <https://bugzilla.redhat.com/show_bug.cgi?id=1381129>`_.

        """
        return type(self)(
            server_config=self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Read subscription from server.

        Override :meth:`nailgun.entity_mixins.EntityReadMixin.read` to ignore
        the ``scap_file``.
        """
        if ignore is None:
            ignore = set()
        ignore.add('scap_file')
        return super().read(entity, attrs, ignore, params)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        xml
            api/compliance/scap_contents/:id/xml

        Otherwise, call ``super``.

        """
        if which in ("xml",):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)

    def update(self, fields=None):
        """Fetch a complete set of attributes for this entity."""
        self.update_json(fields)
        return self.read()

    def xml(self, synchronous=True, timeout=None, **kwargs):
        """Download an SCAP content as XML.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()  # shadow the passed-in kwargs
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('xml'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class Srpms(Entity, EntityReadMixin, EntitySearchMixin):
    """A representation of a Srpms entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'arch': entity_fields.StringField(),
            'checksum': entity_fields.StringField(),
            'epoch': entity_fields.StringField(),
            'filename': entity_fields.StringField(),
            'name': entity_fields.StringField(unique=True),
            'nvra': entity_fields.StringField(),
            'release': entity_fields.StringField(),
            'summary': entity_fields.StringField(),
            'version': entity_fields.StringField(),
        }
        self._meta = {'api_path': 'katello/api/v2/srpms'}
        super().__init__(server_config=server_config, **kwargs)


class Webhooks(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Webhook entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': entity_fields.StringField(unique=True, required=True),
            'target_url': entity_fields.URLField(required=True, scheme='http'),
            'http_method': entity_fields.StringField(
                choices=['POST', 'GET', 'PUT', 'DELETE', 'PATCH']
            ),
            'event': entity_fields.StringField(required=True),
            'http_content_type': entity_fields.StringField(),
            'webhook_template_id': entity_fields.StringField(
                length=(1, 128), str_type='alphanumeric'
            ),
            'enabled': entity_fields.BooleanField(),
            'verify_ssl': entity_fields.BooleanField(),
            'ssl_ca_certs': entity_fields.StringField(),
            'user': entity_fields.StringField(),
            'password': entity_fields.StringField(),
            'http_headers': entity_fields.StringField(),
            'proxy_authorization': entity_fields.BooleanField(),
        }
        self._meta = {
            'api_path': 'api/webhooks',
        }
        super().__init__(server_config=server_config, **kwargs)

    def create(self, create_missing=None):
        """Override creation of Webhooks.

        Before creating the Webhook, we want to call
        get_events to get a valid list of events to pass
        into our POST call.
        """
        self._fields['event'] = entity_fields.StringField(required=True, choices=self.get_events())

        return type(self)(
            server_config=self._server_config,
            id=self.create_json(create_missing)['id'],
        ).read()

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Read subscription from server.

        Override :meth:`nailgun.entity_mixins.EntityReadMixin.read` to ignore
        the ``webhook_template_id``, ``password``, and ``proxy_authorization``.
        """
        if ignore is None:
            ignore = set()
        ignore.add('webhook_template_id')
        ignore.add('password')
        ignore.add('proxy_authorization')
        return super().read(entity, attrs, ignore, params)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        events
            api/webhooks/events

        Otherwise, call ``super``.

        """
        if which in ("events",):
            return f'{super().path()}/{which}'
        return super().path(which)

    def get_events(self, synchronous=True, timeout=None, **kwargs):
        """Get all valid events for a Webhook.

        GET api/webhooks/events returns the list of all valid events
        we can use to create a Webhook. Calling this list before our create
        allows us to test all possible events.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.
        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('events'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class AnsiblePlaybooks(Entity):
    """A representation of Ansible Playbooks entity."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {
            'api_path': '/ansible/api/ansible_playbooks',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        fetch
            /ansible_playbooks/fetch
        sync
            /ansible_playbooks/sync

        ``super`` is called otherwise.

        """
        if which in ("sync", "fetch"):
            return f'{super().path(which="base")}/{which}'
        return super().path(which)

    def fetch(self, synchronous=True, timeout=None, **kwargs):
        """Fetch all ansible playbooks.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.get(self.path('fetch'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)

    def sync(self, synchronous=True, timeout=None, **kwargs):
        """Sync ansible playbooks.

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class AnsibleRoles(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of Ansible Roles entity."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {
            'api_path': '/ansible/api/ansible_roles',
        }
        super().__init__(server_config=server_config, **kwargs)

    def path(self, which=None):
        """Extend ``nailgun.entity_mixins.Entity.path``.

        The format of the returned path depends on the value of ``which``:

        sync
            /ansible_roles/sync

        ``super`` is called otherwise.

        """
        if which in ("sync",):
            return f'{super().path(which="base")}/{which}'
        return super().path(which)

    def sync(self, synchronous=True, timeout=None, **kwargs):
        """Sync ansible roles from a proxy.

        AnsibleRoles.sync(data={'proxy_id': "target_sat.ip", 'role_names': ["role_name"]})

        :param synchronous: What should happen if the server returns an HTTP
            202 (accepted) status code? Wait for the task to complete if
            ``True``. Immediately return the server's response otherwise.
        :param timeout: Maximum number of seconds to wait until timing out.
            Defaults to ``nailgun.entity_mixins.TASK_TIMEOUT``.
        :param kwargs: Arguments to pass to requests.
        :returns: The server's response, with all JSON decoded.
        :raises: ``requests.exceptions.HTTPError`` If the server responds with
            an HTTP 4XX or 5XX message.

        """
        kwargs = kwargs.copy()
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.put(self.path('sync'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)


class AnsibleVariable(
    Entity,
    EntityCreateMixin,
    EntityReadMixin,
    EntityDeleteMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Ansible Variable entity."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'variable': entity_fields.StringField(required=True),
            'ansible_role_id': entity_fields.IntegerField(required=True),
            'default_value': entity_fields.StringField(),
            'override_value_order': entity_fields.StringField(),
            'description': entity_fields.StringField(),
            'validator_type': entity_fields.ListField(),
            'validator_rule': entity_fields.StringField(),
            'variable_type': entity_fields.StringField(
                default='string',
                choices=(
                    'string',
                    'boolean',
                    'integer',
                    'real',
                    'array',
                    'hash',
                    'yaml',
                    'json',
                ),
            ),
            'merge_overrides': entity_fields.BooleanField(),
            'merge_default': entity_fields.BooleanField(),
            'avoid_duplicates': entity_fields.BooleanField(),
            'override': entity_fields.BooleanField(),
        }
        self._meta = {'api_path': 'ansible/api/ansible_variables'}
        super().__init__(server_config=server_config, **kwargs)


class TablePreferences(
    Entity,
    EntityCreateMixin,
    EntityDeleteMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
):
    """A representation of a Table Preference entity."""

    def __init__(self, server_config=None, **kwargs):
        _check_for_value('user', kwargs)
        self._fields = {
            'name': entity_fields.StringField(),
            'columns': entity_fields.ListField(),
            'created_at': entity_fields.DateTimeField(),
            'updated_at': entity_fields.DateTimeField(),
        }
        self._path_fields = {
            'user': entity_fields.OneToOneField(User),
        }
        self._fields.update(self._path_fields)
        self.user = kwargs.get('user')
        if isinstance(self.user, int):
            self._meta = {
                'api_path': f'/api/v2/users/{self.user}/table_preferences',
            }
        else:
            self._meta = {
                'api_path': f'/api/v2/users/{self.user.id}/table_preferences',
            }
        super().__init__(server_config=server_config, **kwargs)

    def read(self, entity=None, attrs=None, ignore=None, params=None):
        """Read table preferences from server.

        Ignore path related fields as they're never returned by the server
        and are only added to entity to be able to use proper path.
        """
        entity = entity or self.entity_with_parent(user=self.user)
        if ignore is None:
            ignore = set()
        ignore.add('user')
        return super().read(entity, attrs, ignore, params)

    def search(self, fields=None, query=None, filters=None):
        """List/search for TablePreferences.

        Field 'user' is only used for path and is not returned.
        """
        return super().search(
            fields=fields, query=query, filters=filters, path_fields={'user': self.user}
        )


class NotificationRecipients(Entity, EntityReadMixin):
    """A representation of /notification_recipients endpoint."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'notifications': entity_fields.ListField(),
        }
        self._meta = {
            'api_path': '/notification_recipients',
            'read_type': 'base',
        }
        super().__init__(server_config=server_config, **kwargs)
