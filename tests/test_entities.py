# -*- encoding: utf-8 -*-
"""Tests for :mod:`nailgun.entities`."""
from datetime import datetime
from fauxfactory import gen_integer, gen_string
from nailgun import client, config, entities
from nailgun.entity_mixins import (
    EntityCreateMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
    MissingValueError,
    NoSuchPathError,
)
import inspect
import mock

from sys import version_info
if version_info < (3, 4):
    from unittest2 import TestCase  # pylint:disable=import-error
else:
    from unittest import TestCase
if version_info.major == 2:
    from httplib import ACCEPTED, NO_CONTENT  # pylint:disable=import-error
else:
    from http.client import ACCEPTED, NO_CONTENT  # pylint:disable=import-error

# pylint:disable=too-many-lines
# The size of this file is a direct reflection of the size of module
# `nailgun.entities` and the Satellite API.


def _get_required_field_names(entity):
    """Get the names of all required fields from an entity.

    :param nailgun.entity_mixins.Entity entity: This entity is inspected.
    :returns: A set in the form ``{'field_name_1', 'field_name_2', …}``.

    """
    return set((
        field_name
        for field_name, field
        in entity.get_fields().items()
        if field.required is True
    ))


# This file is divided in to three sets of test cases (`TestCase` subclasses):
#
# 1. Tests for inherited methods.
# 2. Tests for entity-specific methods.
# 3. Other tests.
#
# 1. Tests for inherited methods. ---------------------------------------- {{{1


class InitTestCase(TestCase):
    """Tests for all of the ``__init__`` methods.

    The tests in this class are a sanity check. They simply check to see if you
    can instantiate each entity.

    """

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')

    def test_init_succeeds(self):
        """Instantiate every entity.

        Assert that the returned object is an instance of the class that
        produced it.

        """
        entities_ = [
            (entity, {})
            for entity in (
                # entities.ContentViewFilterRule,  # see below
                # entities.ContentViewPuppetModule,  # see below
                # entities.OperatingSystemParameter,  # see below
                # entities.SyncPlan,  # see below
                entities.AbstractComputeResource,
                entities.AbstractContentViewFilter,
                entities.AbstractDockerContainer,
                entities.ActivationKey,
                entities.Architecture,
                entities.AuthSourceLDAP,
                entities.Bookmark,
                entities.CommonParameter,
                entities.ComputeAttribute,
                entities.ComputeProfile,
                entities.ConfigGroup,
                entities.ConfigTemplate,
                entities.ContentUpload,
                entities.ContentView,
                entities.ContentViewVersion,
                entities.DiscoveredHosts,
                entities.DockerComputeResource,
                entities.DockerHubContainer,
                entities.Domain,
                entities.Environment,
                entities.Errata,
                entities.ErratumContentViewFilter,
                entities.Filter,
                entities.ForemanTask,
                entities.GPGKey,
                entities.Host,
                entities.HostCollection,
                entities.HostCollectionErrata,
                entities.HostCollectionPackage,
                entities.HostGroup,
                entities.Image,
                entities.Interface,
                entities.LibvirtComputeResource,
                entities.LifecycleEnvironment,
                entities.Location,
                entities.Media,
                entities.Model,
                entities.OSDefaultTemplate,
                entities.OperatingSystem,
                entities.Organization,
                entities.OverrideValue,
                entities.PackageGroupContentViewFilter,
                entities.PartitionTable,
                entities.Permission,
                entities.Ping,
                entities.Product,
                entities.PuppetClass,
                entities.PuppetModule,
                entities.RPMContentViewFilter,
                entities.Realm,
                entities.Report,
                entities.Repository,
                entities.Role,
                entities.RoleLDAPGroups,
                entities.SmartProxy,
                entities.SmartVariable,
                entities.Status,
                entities.Subnet,
                entities.Subscription,
                entities.System,
                entities.SystemPackage,
                entities.TemplateCombination,
                entities.TemplateKind,
                entities.User,
                entities.UserGroup,
            )
        ]
        entities_.extend([
            (
                entities.LibvirtComputeResource,
                {'display_type': 'VNC', 'set_console_password': False},
            ),
            (
                entities.DockerComputeResource,
                {'email': 'nobody@example.com', 'url': 'http://example.com'},
            ),
            (entities.ContentViewFilterRule, {'content_view_filter': 1}),
            (entities.ContentViewPuppetModule, {'content_view': 1}),
            (entities.OperatingSystemParameter, {'operatingsystem': 1}),
            (entities.RepositorySet, {'product': 1}),
            (entities.SyncPlan, {'organization': 1}),
        ])
        for entity, params in entities_:
            with self.subTest():
                self.assertIsInstance(entity(self.cfg, **params), entity)

    def test_required_params(self):
        """Instantiate entities that require extra parameters.

        Assert that ``TypeError`` is raised if the required extra parameters
        are not provided.

        """
        for entity in (
                entities.ContentViewFilterRule,
                entities.ContentViewPuppetModule,
                entities.OperatingSystemParameter,
                entities.RepositorySet,
                entities.SyncPlan,
        ):
            with self.subTest():
                with self.assertRaises(TypeError):
                    entity(self.cfg)


class PathTestCase(TestCase):
    """Tests for extensions of :meth:`nailgun.entity_mixins.Entity.path`."""
    longMessage = True

    def setUp(self):
        """Set ``self.cfg`` and ``self.id_``."""
        self.cfg = config.ServerConfig('http://example.com')
        self.id_ = gen_integer(min_value=1)

    def test_nowhich(self):
        """Execute ``entity().path()`` and ``entity(id=…).path()``."""
        for entity, path in (
                (entities.AbstractDockerContainer, '/containers'),
                (entities.ActivationKey, '/activation_keys'),
                (entities.ConfigTemplate, '/config_templates'),
                (entities.ContentView, '/content_views'),
                (entities.ContentViewVersion, '/content_view_versions'),
                (entities.DiscoveredHosts, '/discovered_hosts'),
                (entities.Organization, '/organizations'),
                (entities.Product, '/products'),
                (entities.RHCIDeployment, '/deployments'),
                (entities.Repository, '/repositories'),
                (entities.SmartProxy, '/smart_proxies'),
                (entities.Subscription, '/subscriptions'),
                (entities.System, '/systems'),
        ):
            with self.subTest((entity, path)):
                self.assertIn(path, entity(self.cfg).path())
                self.assertIn(
                    '{}/{}'.format(path, self.id_),
                    entity(self.cfg, id=self.id_).path()
                )

    def test_id_and_which(self):
        """Execute ``entity(id=…).path(which=…)``."""
        for entity, which in (
                (entities.AbstractDockerContainer, 'logs'),
                (entities.AbstractDockerContainer, 'power'),
                (entities.ActivationKey, 'add_subscriptions'),
                (entities.ActivationKey, 'content_override'),
                (entities.ActivationKey, 'releases'),
                (entities.ActivationKey, 'remove_subscriptions'),
                (entities.ActivationKey, 'subscriptions'),
                (entities.ContentView, 'available_puppet_module_names'),
                (entities.ContentView, 'content_view_puppet_modules'),
                (entities.ContentView, 'content_view_versions'),
                (entities.ContentView, 'copy'),
                (entities.ContentView, 'publish'),
                (entities.ContentViewVersion, 'promote'),
                (entities.Organization, 'subscriptions'),
                (entities.Organization, 'subscriptions/delete_manifest'),
                (entities.Organization, 'subscriptions/manifest_history'),
                (entities.Organization, 'subscriptions/refresh_manifest'),
                (entities.Organization, 'subscriptions/upload'),
                (entities.Organization, 'sync_plans'),
                (entities.Product, 'sync'),
                (entities.Repository, 'sync'),
                (entities.Repository, 'upload_content'),
                (entities.RHCIDeployment, 'deploy'),
        ):
            with self.subTest((entity, which)):
                path = entity(self.cfg, id=self.id_).path(which=which)
                self.assertIn('{}/{}'.format(self.id_, which), path)
                self.assertRegex(path, which + '$')

    def test_noid_and_which(self):
        """Execute ``entity().path(which=…)``."""
        for entity, which in (
                (entities.ConfigTemplate, 'build_pxe_default'),
                (entities.ConfigTemplate, 'revision'),
                (entities.DiscoveredHosts, 'facts'),
        ):
            with self.subTest((entity, which)):
                path = entity(self.cfg).path(which=which)
                self.assertIn(which, path)
                self.assertRegex(path, which + '$')

    def test_no_such_path_error(self):
        """Trigger :class:`nailgun.entity_mixins.NoSuchPathError` exceptions.

        Do this by calling ``entity().path(which=…)``.

        """
        for entity, which in (
                (entities.ActivationKey, 'releases'),
                (entities.ContentView, 'available_puppet_module_names'),
                (entities.ContentView, 'content_view_puppet_modules'),
                (entities.ContentView, 'content_view_versions'),
                (entities.ContentView, 'publish'),
                (entities.ContentViewVersion, 'promote'),
                (entities.ForemanTask, 'self'),
                (entities.Organization, 'products'),
                (entities.Organization, 'self'),
                (entities.Organization, 'subscriptions'),
                (entities.Organization, 'subscriptions/delete_manifest'),
                (entities.Organization, 'subscriptions/refresh_manifest'),
                (entities.Organization, 'subscriptions/upload'),
                (entities.Organization, 'sync_plans'),
                (entities.Product, 'repository_sets'),
                (entities.Repository, 'sync'),
                (entities.Repository, 'upload_content'),
                (entities.RHCIDeployment, 'deploy'),
                (entities.SmartProxy, 'refresh'),
                (entities.System, 'self'),
        ):
            with self.subTest((entity, which)):
                with self.assertRaises(NoSuchPathError):
                    entity(self.cfg).path(which=which)

    def test_foreman_task(self):
        """Test :meth:`nailgun.entities.ForemanTask.path`.

        Assert that the following return appropriate paths:

        * ``ForemanTask(id=…).path()``
        * ``ForemanTask().path('bulk_search')``
        * ``ForemanTask(id=…).path('bulk_search')``

        """
        self.assertIn(
            '/foreman_tasks/api/tasks/{}'.format(self.id_),
            entities.ForemanTask(self.cfg, id=self.id_).path()
        )
        for path in (
                entities.ForemanTask(self.cfg).path('bulk_search'),
                entities.ForemanTask(self.cfg, id=self.id_).path('bulk_search')
        ):
            self.assertIn('/foreman_tasks/api/tasks/bulk_search', path)

    def test_repository_set(self):
        """Test :meth:`nailgun.entities.RepositorySet.path`.

        Assert that the following return appropriate paths:

        * ``RepositorySet(id=…).path()``
        * ``RepositorySet(id=…).path('available_repositories')``
        * ``RepositorySet(id=…).path('disable')``
        * ``RepositorySet(id=…).path('enable')``

        """
        self.assertIn(
            'products/1/repository_sets/2',
            entities.RepositorySet(self.cfg, id=2, product=1).path()
        )
        for which in ('available_repositories', 'disable', 'enable'):
            path = entities.RepositorySet(
                self.cfg,
                id=2,
                product=1,
            ).path(which)
            self.assertIn('products/1/repository_sets/2/' + which, path)
            self.assertRegex(path, '{}$'.format(which))

    def test_sync_plan(self):
        """Test :meth:`nailgun.entities.SyncPlan.path`.

        Assert that the following return appropriate paths:

        * ``SyncPlan(id=…).path()``
        * ``SyncPlan(id=…).path('add_products')``
        * ``SyncPlan(id=…).path('remove_products')``

        """
        self.assertIn(
            'organizations/1/sync_plans/2',
            entities.SyncPlan(self.cfg, id=2, organization=1).path()
        )
        for which in ('add_products', 'remove_products'):
            path = entities.SyncPlan(
                self.cfg,
                id=2,
                organization=1,
            ).path(which)
            self.assertIn('organizations/1/sync_plans/2/' + which, path)
            self.assertRegex(path, '{}$'.format(which))

    def test_system(self):
        """Test :meth:`nailgun.entities.System.path`.

        Assert that the following return appropriate paths:

        * ``System().path()``
        * ``System().path('base')``
        * ``System(uuid=…).path()``
        * ``System(uuid=…).path('self')``
        * ``System(uuid=…).path('subscriptions')``

        """
        system = entities.System(self.cfg)
        for path in (system.path(), system.path('base')):
            self.assertIn('/systems', path)
            self.assertRegex(path, 'systems$')

        system = entities.System(self.cfg, uuid=self.id_)
        for path in (system.path(), system.path('self')):
            self.assertIn('/systems/{}'.format(self.id_), path)
            self.assertRegex(path, '{}$'.format(self.id_))

        path = system.path('subscriptions')
        self.assertIn('/systems/{}/subscriptions'.format(self.id_), path)
        self.assertRegex(path, '{}$'.format('subscriptions'))

    def test_subscription(self):
        """Test :meth:`nailgun.entities.Subscription.path`.

        Assert that the following return appropriate paths:

        * ``Subscription(organization=…).path('delete_manifest')``
        * ``Subscription(organization=…).path('manifest_history')``
        * ``Subscription(organization=…).path('refresh_manifest')``
        * ``Subscription(organization=…).path('upload')``

        """
        sub = entities.Subscription(self.cfg, organization=gen_integer(1, 100))
        for which in (
                'delete_manifest',
                'manifest_history',
                'refresh_manifest',
                'upload'):
            with self.subTest(which):
                path = sub.path(which)
                self.assertIn(
                    'organizations/{}/subscriptions/{}'.format(
                        sub.organization.id,  # pylint:disable=no-member
                        which,
                    ),
                    path
                )
                self.assertRegex(path, '{}$'.format(which))


class CreateTestCase(TestCase):
    """Tests for :meth:`nailgun.entity_mixins.EntityCreateMixin.create`."""

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')

    def test_generic(self):
        """Call ``create`` on a variety of entities."""
        entities_ = (
            entities.AbstractDockerContainer(self.cfg),
            entities.DockerComputeResource(self.cfg),
            entities.Domain(self.cfg),
            entities.Location(self.cfg),
            entities.Media(self.cfg),
            entities.Organization(self.cfg),
            entities.Realm(self.cfg),
        )
        for entity in entities_:
            with self.subTest(entity):
                with mock.patch.object(entity, 'create_json') as create_json:
                    with mock.patch.object(type(entity), 'read') as read:
                        entity.create()
                self.assertEqual(create_json.call_count, 1)
                self.assertEqual(create_json.call_args[0], (None,))
                self.assertEqual(read.call_count, 1)
                self.assertEqual(read.call_args[0], ())


class CreatePayloadTestCase(TestCase):
    """Tests for extensions of ``create_payload``.

    Several classes extend the ``create_payload`` method and make it do things
    like rename attributes or wrap the submitted dict of data in a second hash.
    It is possible to mess this up in a variety of ways. For example, an
    extended method could could try to rename an attribute that does not exist.
    This class attempts to find such issues by creating an entity, calling
    :meth:`nailgun.entity_mixins.EntityCreateMixin.create_payload` and
    asserting that a ``dict`` is returned.

    """

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')

    def test_no_attributes(self):
        """Instantiate an entity and call ``create_payload`` on it."""
        entities_ = [
            (entity, {})
            for entity in (
                entities.AbstractComputeResource,
                entities.AbstractDockerContainer,
                entities.Architecture,
                entities.ConfigTemplate,
                entities.DiscoveredHosts,
                entities.Domain,
                entities.Environment,
                entities.Host,
                entities.HostCollection,
                entities.HostGroup,
                entities.LifecycleEnvironment,
                entities.Location,
                entities.Media,
                entities.OperatingSystem,
                entities.Subnet,
                entities.User,
                entities.UserGroup,
            )
        ]
        entities_.extend([
            (entities.SyncPlan, {'organization': 1}),
            (entities.ContentViewPuppetModule, {'content_view': 1}),
        ])
        for entity, params in entities_:
            with self.subTest():
                self.assertIsInstance(
                    entity(self.cfg, **params).create_payload(),
                    dict
                )

    def test_sync_plan(self):
        """Call ``create_payload`` on a :class:`nailgun.entities.SyncPlan`."""
        self.assertIsInstance(
            entities.SyncPlan(
                self.cfg,
                organization=1,
                sync_date=datetime.now(),
            ).create_payload()['sync_date'],
            type('')  # different for Python 2 and 3
        )

    def test_content_view_puppet_module(self):
        """Create a :class:`nailgun.entities.ContentViewPuppetModule`."""
        payload = entities.ContentViewPuppetModule(
            self.cfg,
            content_view=1,
            puppet_module=2,
        ).create_payload()
        self.assertNotIn('puppet_module_id', payload)
        self.assertIn('uuid', payload)

    def test_host_collection(self):
        """Create a :class:`nailgun.entities.HostCollection`."""
        payload = entities.HostCollection(
            self.cfg,
            system=[1],
        ).create_payload()
        self.assertNotIn('system_ids', payload)
        self.assertIn('system_uuids', payload)

    def test_media(self):
        """Create a :class:`nailgun.entities.Media`."""
        payload = entities.Media(self.cfg, path_='foo').create_payload()
        self.assertNotIn('path_', payload['medium'])
        self.assertIn('path', payload['medium'])


class CreateMissingTestCase(TestCase):
    """Tests for extensions of ``create_missing``."""

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')
        # Fields optionally populated by AuthSourceLDAP.create_missing()
        cls.AS_LDAP_FIELDS = (
            'account_password',
            'attr_firstname',
            'attr_lastname',
            'attr_login',
            'attr_mail',
        )

    def test_auth_source_ldap_v1(self):
        """Test ``AuthSourceLDAP(onthefly_register=False).create_missing()``"""
        entity = entities.AuthSourceLDAP(self.cfg, onthefly_register=False)
        with mock.patch.object(EntityCreateMixin, 'create_missing'):
            entity.create_missing()
        self.assertTrue(
            set((self.AS_LDAP_FIELDS)).isdisjoint(entity.get_values())
        )

    def test_auth_source_ldap_v2(self):
        """Test ``AuthSourceLDAP(onthefly_register=True).create_missing()``."""
        entity = entities.AuthSourceLDAP(self.cfg, onthefly_register=True)
        with mock.patch.object(EntityCreateMixin, 'create_missing'):
            entity.create_missing()
        self.assertTrue(
            set((self.AS_LDAP_FIELDS)).issubset(entity.get_values())
        )

    def test_auth_source_ldap_v3(self):
        """Does ``AuthSourceLDAP.create_missing`` overwrite fields?"""
        attrs = {
            field: i
            for i, field in enumerate(self.AS_LDAP_FIELDS)
        }
        attrs.update({'onthefly_register': True})
        entity = entities.AuthSourceLDAP(self.cfg, **attrs)
        with mock.patch.object(EntityCreateMixin, 'create_missing'):
            entity.create_missing()
        for key, value in attrs.items():
            with self.subTest((key, value)):
                self.assertEqual(getattr(entity, key), value)

    def test_config_template_v1(self):
        """Test ``ConfigTemplate(snippet=True)``."""
        entity = entities.ConfigTemplate(self.cfg, snippet=True)
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertEqual(
            _get_required_field_names(entity),
            set(entity.get_values().keys()),
        )

    def test_config_template_v2(self):
        """Test ``ConfigTemplate(snippet=False)``."""
        entity = entities.ConfigTemplate(self.cfg, snippet=False)
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertEqual(
            _get_required_field_names(entity).union(['template_kind']),
            set(entity.get_values().keys()),
        )

    def test_config_template_v3(self):
        """Test ``ConfigTemplate(snippet=False, template_kind=…)``."""
        tk_id = gen_integer()
        entity = entities.ConfigTemplate(
            self.cfg,
            snippet=False,
            template_kind=tk_id,
        )
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertEqual(
            _get_required_field_names(entity).union(['template_kind']),
            set(entity.get_values().keys()),
        )
        # pylint:disable=no-member
        self.assertEqual(entity.template_kind.id, tk_id)

    def test_domain_v1(self):
        """Test ``Domain(name='UPPER')``."""
        entity = entities.Domain(self.cfg, name='UPPER')
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertEqual(entity.name, 'UPPER')

    def test_domain_v2(self):
        """Test ``Domain()``."""
        entity = entities.Domain(self.cfg)
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertTrue(entity.name.islower())

    def test_host_v1(self):
        """Test ``Host(any_attribute=…)``."""
        with self.assertRaises(entities.HostCreateMissingError):
            entities.Host(self.cfg, name='foo').create_missing()

    def test_host_v2(self):
        """Test ``Host()``."""
        entity = entities.Host(self.cfg)
        with mock.patch.object(EntityCreateMixin, 'create_json'):
            with mock.patch.object(EntityReadMixin, 'read_json'):
                with mock.patch.object(EntityReadMixin, 'read'):
                    entity.create_missing()
        self.assertEqual(
            set(entity.get_values().keys()),
            _get_required_field_names(entity).union((
                'architecture',
                'domain',
                'environment',
                'mac',
                'medium',
                'operatingsystem',
                'ptable',
                'root_pass',
            )),
        )

    def test_lifecycle_environment_v1(self):
        """Test ``LifecycleEnvironment(name='Library')``."""
        entity = entities.LifecycleEnvironment(self.cfg, name='Library')
        with mock.patch.object(EntityCreateMixin, 'create_missing'):
            with mock.patch.object(EntitySearchMixin, 'search') as search:
                entity.create_missing()
        self.assertEqual(search.call_count, 0)

    def test_lifecycle_environment_v2(self):
        """Test ``LifecycleEnvironment(name='not Library')``."""
        entity = entities.LifecycleEnvironment(
            self.cfg,
            name='not Library',
            organization=1,
        )
        with mock.patch.object(EntityCreateMixin, 'create_missing'):
            with mock.patch.object(EntitySearchMixin, 'search') as search:
                search.return_value = [gen_integer()]
                entity.create_missing()
        self.assertEqual(search.call_count, 1)
        self.assertEqual(entity.prior, search.return_value[0])

    def test_lifecycle_environment_v3(self):
        """What happens when the "Library" lifecycle env cannot be found?"""
        entity = entities.LifecycleEnvironment(
            self.cfg,
            name='not Library',
            organization=1,
        )
        with mock.patch.object(EntityCreateMixin, 'create_missing'):
            with mock.patch.object(EntitySearchMixin, 'search') as search:
                search.return_value = []
                with self.assertRaises(entities.APIResponseError):
                    entity.create_missing()

    def test_media_v1(self):
        """Test ``Media()``."""
        entity = entities.Media(self.cfg)
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertTrue('path_' in entity.get_values())

    def test_media_v2(self):
        """Test ``Media(path_=…)``."""
        path = gen_string('alphanumeric')
        entity = entities.Media(self.cfg, path_=path)
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertEqual(entity.path_, path)

    def test_repository_v1(self):
        """Test ``Repository(content_type='docker')``."""
        entity = entities.Repository(self.cfg, content_type='docker')
        with mock.patch.object(EntityCreateMixin, 'create_missing'):
            entity.create_missing()
        self.assertTrue(entity.get_fields()['docker_upstream_name'].required)

    def test_repository_v2(self):
        """Test ``Repository(content_type='not docker')``."""
        entity = entities.Repository(self.cfg, content_type='not docker')
        with mock.patch.object(EntityCreateMixin, 'create_missing'):
            entity.create_missing()
        self.assertFalse(entity.get_fields()['docker_upstream_name'].required)


class ReadTestCase(TestCase):
    """Tests for :meth:`nailgun.entity_mixins.EntityReadMixin.read`."""

    def setUp(self):
        """Set a server configuration at ``self.cfg``."""
        self.cfg = config.ServerConfig('http://example.com')

    def test_entity_arg(self):
        """Call ``read`` on entities that require parameters for instantiation.

        Some entities require extra parameters when being instantiated. As a
        result, these entities must extend
        :meth:`nailgun.entity_mixins.EntityReadMixin.read` by providing a value
        for the ``entity`` argument. Assert that these entities pass their
        server configuration objects to the child entities that they create and
        pass in to the ``entity`` argument.

        """
        for entity in (
                entities.ContentViewFilterRule(
                    self.cfg,
                    content_view_filter=2,
                ),
                entities.ContentViewPuppetModule(self.cfg, content_view=2),
                entities.OperatingSystemParameter(self.cfg, operatingsystem=2),
                entities.RepositorySet(self.cfg, product=2),
                entities.SyncPlan(self.cfg, organization=2),
        ):
            # We mock read_json() because it may be called by read().
            with mock.patch.object(EntityReadMixin, 'read_json'):
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    entity.read()
            self.assertEqual(read.call_count, 1)
            # read.call_args[0][0] is the `entity` argument to read()
            # pylint:disable=protected-access
            self.assertEqual(read.call_args[0][0]._server_config, self.cfg)

    def test_attrs_arg_v1(self):
        """Ensure ``read`` and ``read_json`` are both called once.

        This test is only appropriate for entities that override the ``read``
        method in order to fiddle with the ``attrs`` argument.

        """
        for entity in (
                # entities.DockerComputeResource,  # see test_attrs_arg_v2
                # entities.HostGroup,  # see HostGroupTestCase.test_read
                # entities.Product,  # See Product.test_read
                # entities.UserGroup,  # see test_attrs_arg_v2
                entities.Domain,
                entities.Host,
                entities.Media,
                entities.RHCIDeployment,
                entities.System,
        ):
            with mock.patch.object(EntityReadMixin, 'read_json') as read_json:
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    with self.subTest():
                        entity(self.cfg).read()
                        self.assertEqual(read_json.call_count, 1)
                        self.assertEqual(read.call_count, 1)

    def test_attrs_arg_v2(self):
        """Ensure ``read``, ``read_json`` and ``client.put`` are called once.

        This test is only appropriate for entities that override the ``read``
        method in order to fiddle with the ``attrs`` argument.

        """
        # test_data is a single-use variable. We use it anyway for formatting
        # purposes.
        test_data = (
            (entities.UserGroup(self.cfg, id=1), {'admin': 'foo'}),
            (entities.DockerComputeResource(self.cfg, id=1), {'email': 'bar'}),
        )
        for entity, server_response in test_data:
            with mock.patch.object(EntityReadMixin, 'read_json') as read_json:
                read_json.return_value = {}
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    with mock.patch.object(client, 'put') as put:
                        put.return_value.json.return_value = server_response
                        entity.read()
            self.assertEqual(read_json.call_count, 1)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(put.call_count, 1)
            self.assertEqual(read.call_args[0][1], server_response)

    def test_entity_ids(self):
        """Test cases where the server returns unusually named attributes.

        Assert that the returned attributes are renamed to be more regular
        before calling ``read()``.

        """
        # test_data is a single-use variable. We use it anyway for formatting
        # purposes.
        test_data = (
            (
                entities.Domain(self.cfg),
                {'parameters': None},
                {'domain_parameters_attributes': None},
            ),
            (
                entities.Host(self.cfg),
                {'parameters': None, 'puppetclasses': None},
                {'host_parameters_attributes': None, 'puppet_class': None},
            ),
            (
                entities.System(self.cfg),
                {
                    'checkin_time': None,
                    'hostCollections': None,
                    'installedProducts': None,
                },
                {
                    'last_checkin': None,
                    'host_collections': None,
                    'installed_products': None,
                },
            ),
        )
        for entity, attrs_before, attrs_after in test_data:
            with self.subTest(entity):
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    entity.read(attrs=attrs_before)
                self.assertEqual(read.call_args[0][1], attrs_after)

    def test_ignore_arg_v1(self):
        """Call ``read`` on a variety of entities.``.

        Assert that the ``ignore`` argument is correctly passed on.

        """
        for entity, ignored_attrs in (
                (entities.Subnet, {'discovery'}),
                (entities.User, {'password'}),
        ):
            with self.subTest(entity):
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    entity(self.cfg).read()
                # `call_args` is a two-tuple of (positional, keyword) args.
                self.assertEqual(ignored_attrs, read.call_args[0][2])

    def test_ignore_arg_v2(self):
        """Call :meth:`nailgun.entities.DockerComputeResource.read`.

        Assert that the entity ignores the 'password' field.

        """
        with mock.patch.object(EntityReadMixin, 'read') as read:
            entities.DockerComputeResource(self.cfg).read(attrs={'email': 1})
        # `call_args` is a two-tuple of (positional, keyword) args.
        self.assertIn('password', read.call_args[0][2])

    def test_ignore_arg_v3(self):
        """Call :meth:`nailgun.entities.AuthSourceLDAP.read`.

        Assert that the entity ignores the 'account_password' field.

        """
        with mock.patch.object(EntityUpdateMixin, 'update_json') as u_json:
            with mock.patch.object(EntityReadMixin, 'read') as read:
                entities.AuthSourceLDAP(self.cfg).read()
        self.assertEqual(u_json.call_count, 1)
        self.assertEqual(read.call_count, 1)
        self.assertEqual({'account_password'}, read.call_args[0][2])

    def test_ignore_arg_v4(self):
        """Call :meth:`nailgun.entities.User.read`.

        Assert that entity`s predefined values of ``ignore`` are always
        correctly passed on.

        """
        for input_ignore, actual_ignore in (
                (None, {'password'}),
                ({'password'}, {'password'}),
                ({'email'}, {'email', 'password'}),
                ({'email', 'password'}, {'email', 'password'}),
        ):
            with self.subTest(input_ignore):
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    entities.User(self.cfg).read(ignore=input_ignore)
                # `call_args` is a two-tuple of (positional, keyword) args.
                self.assertEqual(actual_ignore, read.call_args[0][2])


class SearchRawTestCase(TestCase):
    """Tests for :meth:`nailgun.entity_mixins.EntitySearchMixin.search_raw`."""

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')

    def test_subscription_v1(self):
        """Test :meth:`nailgun.entities.Subscription.search_raw`.

        Sucessfully call the ``search_raw`` method.

        """
        kwargs_iter = (
            {'activation_key': entities.ActivationKey(self.cfg, id=1)},
            {'organization': entities.Organization(self.cfg, id=1)},
            {'system': entities.System(self.cfg, uuid=1)},
        )
        for kwargs in kwargs_iter:
            sub = entities.Subscription(self.cfg, **kwargs)
            with self.subTest(sub):
                with mock.patch.object(client, 'get') as get:
                    with mock.patch.object(sub, 'search_payload'):
                        sub.search_raw()
                self.assertEqual(get.call_count, 1)
                self.assertIn('subscriptions', get.call_args[0][0])

    def test_subscription_v2(self):
        """Test :meth:`nailgun.entities.Subscription.search_raw`.

        Raise a :class:`nailgun.entity_mixins.MissingValueError` by failing to
        provide necessary values.

        """
        with self.assertRaises(MissingValueError):
            entities.Subscription(self.cfg).search_raw()


class UpdateTestCase(TestCase):
    """Tests for :meth:`nailgun.entity_mixins.EntityUpdateMixin.update`."""

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')

    def test_generic(self):
        """Call ``update`` on a variety of entities."""
        entities_ = (
            entities.AbstractComputeResource(self.cfg),
            entities.Architecture(self.cfg),
            entities.ConfigTemplate(self.cfg),
            entities.Domain(self.cfg),
            entities.Host(self.cfg),
            entities.HostGroup(self.cfg),
            entities.Location(self.cfg),
            entities.Organization(self.cfg),
            entities.User(self.cfg),
        )
        for entity in entities_:
            with self.subTest(entity):

                # Call update()
                with mock.patch.object(entity, 'update_json') as update_json:
                    with mock.patch.object(entity, 'read') as read:
                        self.assertEqual(entity.update(), read.return_value)
                self.assertEqual(update_json.call_count, 1)
                self.assertEqual(update_json.call_args[0], (None,))
                self.assertEqual(read.call_count, 1)
                self.assertEqual(read.call_args[0], ())

                # Call update(fields)
                fields = gen_integer()
                with mock.patch.object(entity, 'update_json') as update_json:
                    with mock.patch.object(entity, 'read') as read:
                        self.assertEqual(
                            entity.update(fields),
                            read.return_value,
                        )
                self.assertEqual(update_json.call_count, 1)
                self.assertEqual(update_json.call_args[0], (fields,))
                self.assertEqual(read.call_count, 1)
                self.assertEqual(read.call_args[0], ())


class UpdatePayloadTestCase(TestCase):
    """Tests for extensions of ``update_payload``."""

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')

    def test_generic(self):
        """Instantiate a variety of entities and call ``update_payload``."""
        entities_payloads = [
            (entities.AbstractComputeResource, {'compute_resource': {}}),
            (entities.ConfigTemplate, {'config_template': {}}),
            (entities.DiscoveredHosts, {'discovered_host': {}}),
            (entities.Domain, {'domain': {}}),
            (entities.Host, {'host': {}}),
            (entities.HostGroup, {'hostgroup': {}}),
            (entities.Location, {'location': {}}),
            (entities.Organization, {'organization': {}}),
            (entities.User, {'user': {}}),
        ]
        for entity, payload in entities_payloads:
            with self.subTest((entity, payload)):
                self.assertEqual(entity(self.cfg).update_payload(), payload)

    def test_syncplan_sync_date(self):
        """Test ``update_payload`` for different syncplan sync_date formats."""
        date_string = '2015-07-20 20:54:38'
        date_datetime = datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S')
        kwargs_responses = [
            (
                {'organization': 1},
                {'organization_id': 1},
            ),
            (
                {'organization': 1, 'sync_date': date_string},
                {'organization_id': 1, 'sync_date': date_string},
            ),
            (
                {'organization': 1, 'sync_date': date_datetime},
                {'organization_id': 1, 'sync_date': date_string},
            ),
        ]
        for kwargs, payload in kwargs_responses:
            with self.subTest((kwargs, payload)):
                self.assertEqual(
                    entities.SyncPlan(self.cfg, **kwargs).update_payload(),
                    payload,
                )


# 2. Tests for entity-specific methods. ---------------------------------- {{{1


class GenericTestCase(TestCase):
    """Generic tests for the helper methods on entities."""

    @classmethod
    def setUpClass(cls):
        """Create test data as ``cls.methods_requests``.

        ``methods_requests`` is a tuple of two-tuples, like so::

            (
                entity_obj1.method, 'post',
                entity_obj2.method, 'post',
                entity_obj3.method1, 'get',
                entity_obj3.method2, 'put',
            )

        """
        cfg = config.ServerConfig('http://example.com')
        generic = {'server_config': cfg, 'id': 1}
        repo_set = {'server_config': cfg, 'id': 1, 'product': 2}
        cls.methods_requests = (
            (entities.AbstractDockerContainer(**generic).logs, 'get'),
            (entities.AbstractDockerContainer(**generic).power, 'put'),
            (entities.ActivationKey(**generic).add_subscriptions, 'put'),
            (entities.ActivationKey(**generic).content_override, 'put'),
            (entities.ContentView(**generic).available_puppet_modules, 'get'),
            (entities.ContentView(**generic).copy, 'post'),
            (entities.ContentView(**generic).publish, 'post'),
            (entities.ContentViewVersion(**generic).promote, 'post'),
            (entities.DiscoveredHosts(cfg).facts, 'post'),
            (entities.Product(**generic).sync, 'post'),
            (entities.RHCIDeployment(**generic).deploy, 'put'),
            (entities.Repository(**generic).sync, 'post'),
            (entities.RepositorySet(**repo_set).available_repositories, 'get'),
            (entities.RepositorySet(**repo_set).disable, 'put'),
            (entities.RepositorySet(**repo_set).enable, 'put'),
            (entities.SmartProxy(**generic).refresh, 'put'),
        )

    def test_generic(self):
        """Check that a variety of helper method sane.

        Assert that:

        * Each method has a correct signature.
        * Each method calls `client.*` once.
        * Each method passes the right arguments to `client.*`.
        * Each method calls `entities._handle_response` once.
        * The result of `_handle_response(…)` is the return value.

        """
        for method, request in self.methods_requests:
            with self.subTest((method, request)):
                self.assertEqual(
                    inspect.getargspec(method),
                    (['self', 'synchronous'], None, 'kwargs', (True,))
                )
                kwargs = {'kwarg': gen_integer()}
                with mock.patch.object(entities, '_handle_response') as handlr:
                    with mock.patch.object(client, request) as client_request:
                        response = method(**kwargs)
                self.assertEqual(client_request.call_count, 1)
                self.assertEqual(len(client_request.call_args[0]), 1)
                self.assertEqual(client_request.call_args[1], kwargs)
                self.assertEqual(handlr.call_count, 1)
                self.assertEqual(handlr.return_value, response)


class AbstractDockerContainerTestCase(TestCase):
    """Tests for :class:`nailgun.entities.AbstractDockerContainer`."""

    def setUp(self):
        """Set a server configuration at ``self.cfg``."""
        self.cfg = config.ServerConfig('http://example.com')
        self.abstract_dc = entities.AbstractDockerContainer(
            self.cfg,
            id=gen_integer(min_value=1),
        )

    def test_get_fields(self):
        """Call ``nailgun.entity_mixins.Entity.get_fields``.

        Assert that ``nailgun.entities.DockerHubContainer.get_fields`` returns
        a dictionary of attributes that match what is returned by
        ``nailgun.entities.AbstractDockerContainer.get_fields`` but also
        returns extra attibutes unique to
        :class:`nailgun.entities.DockerHubContainer`.

        """
        abstract_docker = entities.AbstractDockerContainer(
            self.cfg
        ).get_fields()
        docker_hub = entities.DockerHubContainer(self.cfg).get_fields()
        # Attributes should not match
        self.assertNotEqual(abstract_docker, docker_hub)
        # All attributes from a `entities.AbstractDockerContainer`
        # should be found in a `entities.DockerHubContainer`.
        for key in abstract_docker:
            self.assertIn(key, docker_hub)
        # These fields should be present in a `entities.DockerHubContainer`
        # class but not in a `entities.AbstractDockerContainer` class.
        for attr in ['repository_name', 'tag']:
            self.assertIn(attr, docker_hub)
            self.assertNotIn(attr, abstract_docker)


class ForemanTaskTestCase(TestCase):
    """Tests for :class:`nailgun.entities.ForemanTask`."""

    def setUp(self):
        """Set ``self.foreman_task``."""
        self.foreman_task = entities.ForemanTask(
            config.ServerConfig('http://example.com'),
            id=gen_integer(min_value=1),
        )

    def test_poll(self):
        """Call :meth:`nailgun.entities.ForemanTask.poll`."""
        for kwargs in (
                {},
                {'poll_rate': gen_integer()},
                {'timeout': gen_integer()},
                {'poll_rate': gen_integer(), 'timeout': gen_integer()}
        ):
            with self.subTest(kwargs):
                with mock.patch.object(entities, '_poll_task') as poll_task:
                    self.foreman_task.poll(**kwargs)
                self.assertEqual(poll_task.call_count, 1)
                self.assertEqual(
                    poll_task.call_args[0][2],
                    kwargs.get('poll_rate', None),
                )
                self.assertEqual(
                    poll_task.call_args[0][3],
                    kwargs.get('timeout', None),
                )


class HostGroupTestCase(TestCase):
    """Tests for :class:`nailgun.entities.HostGroup`."""

    def test_read(self):
        """Ensure ``read``, ``read_json`` and ``update_json`` are called once.

        This test is only appropriate for entities that override the ``read``
        method in order to fiddle with the ``attrs`` argument.

        """
        entity = entities.HostGroup(config.ServerConfig('some url'))
        with mock.patch.object(entity, 'read_json') as read_json:
            read_json.return_value = {'ancestry': None, 'id': 641212}  # random
            with mock.patch.object(
                entities.HostGroup,
                'update_json',
                return_value={
                    'content_view_id': None,
                    'lifecycle_environment_id': None,
                },
            ) as update_json:
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    entity.read()
        for meth in (read_json, update_json, read):
            self.assertEqual(meth.call_count, 1)
        self.assertEqual(
            read.call_args[0][1],
            {
                'content_view_id': None,
                'id': 641212,
                'lifecycle_environment_id': None,
                'parent_id': None,
            },
        )


class RepositoryTestCase(TestCase):
    """Tests for :class:`nailgun.entities.Repository`."""

    def setUp(self):
        """Set ``self.repo``."""
        self.repo = entities.Repository(
            config.ServerConfig('http://example.com'),
            id=gen_integer(min_value=1),
        )

    def test_upload_content_v1(self):
        """Call :meth:`nailgun.entities.Repository.upload_content`.

        Make the (mock) server return a "success" status. Make the same
        assertions as for
        :meth:`tests.test_entities.GenericTestCase.test_generic`.

        """
        kwargs = {'kwarg': gen_integer()}
        with mock.patch.object(client, 'post') as post:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value={'status': 'success'},
            ) as handler:
                response = self.repo.upload_content(**kwargs)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(post.call_args[0]), 1)
        self.assertEqual(post.call_args[1], kwargs)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

    def test_upload_content_v2(self):
        """Call :meth:`nailgun.entities.Repository.upload_content`.

        Assert that :class:`nailgun.entities.APIResponseError` is raised when
        the (mock) server fails to return a "success" status.

        """
        kwargs = {'kwarg': gen_integer()}
        with mock.patch.object(client, 'post') as post:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value={'status': 'failure'},
            ) as handler:
                with self.assertRaises(entities.APIResponseError):
                    self.repo.upload_content(**kwargs)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(post.call_args[0]), 1)
        self.assertEqual(post.call_args[1], kwargs)
        self.assertEqual(handler.call_count, 1)


class RepositorySetTestCase(TestCase):
    """Tests for :class:`nailgun.entities.RepositorySet`."""

    def setUp(self):
        """Set ``self.product``."""
        self.product = entities.Product(
            config.ServerConfig('http://example.com'),
            id=gen_integer(min_value=1),
        )
        self.reposet = entities.RepositorySet(
            config.ServerConfig('http://example.com'),
            id=gen_integer(min_value=1),
            product=self.product,
        )

    def test_search_normalize(self):
        """Call :meth:`nailgun.entities.RepositorySet.search_normalize`"""
        with mock.patch.object(EntitySearchMixin, 'search_normalize') as s_n:
            self.reposet.search_normalize([{}, {}])
        self.assertEqual(s_n.call_count, 1)
        for result in s_n.call_args[0][0]:
            # pylint:disable=no-member
            self.assertEqual(result['product_id'], self.product.id)


class SubscriptionTestCase(TestCase):
    """Tests for :class:`nailgun.entities.Subscription`."""

    def setUp(self):
        """Set ``self.subscription``."""
        self.subscription = entities.Subscription(
            config.ServerConfig('http://example.com'),
        )
        self.payload = gen_integer()

    def test__org_path(self):
        """Call ``nailgun.entities.Subscription._org_path``."""
        which = gen_integer()
        payload = {'organization_id': gen_integer()}
        with mock.patch.object(entities.Subscription, 'path') as path:
            # pylint:disable=protected-access
            response = self.subscription._org_path(which, payload)
        self.assertEqual(path.call_count, 1)
        self.assertEqual(path.call_args[0], (which,))
        self.assertEqual(path.return_value, response)
        self.assertFalse(hasattr(self.subscription, 'organization'))

    def test_delete_manifest(self):
        """Call :meth:`nailgun.entities.Subscription.delete_manifest`."""
        with mock.patch.object(self.subscription, '_org_path') as org_path:
            with mock.patch.object(entities, '_handle_response') as handler:
                with mock.patch.object(client, 'post') as post:
                    response = self.subscription.delete_manifest(self.payload)
        self.assertEqual(org_path.call_count, 1)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(
            org_path.call_args[0],
            ('delete_manifest', self.payload),
        )
        self.assertEqual(handler.return_value, response)

    def test_manifest_history(self):
        """Call :meth:`nailgun.entities.Subscription.manifest_history`."""
        with mock.patch.object(self.subscription, '_org_path') as org_path:
            with mock.patch.object(entities, '_handle_response') as handler:
                with mock.patch.object(client, 'get') as get:
                    response = self.subscription.manifest_history(self.payload)
        self.assertEqual(org_path.call_count, 1)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(
            org_path.call_args[0],
            ('manifest_history', self.payload),
        )
        self.assertEqual(handler.return_value, response)

    def test_refresh_manifest(self):
        """Call :meth:`nailgun.entities.Subscription.refresh_manifest`."""
        with mock.patch.object(self.subscription, '_org_path') as org_path:
            with mock.patch.object(entities, '_handle_response') as handler:
                with mock.patch.object(client, 'put') as put:
                    response = self.subscription.refresh_manifest(self.payload)
        self.assertEqual(org_path.call_count, 1)
        self.assertEqual(put.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(
            org_path.call_args[0],
            ('refresh_manifest', self.payload),
        )
        self.assertEqual(handler.return_value, response)

    def test_upload(self):
        """Call :meth:`nailgun.entities.Subscription.upload`."""
        manifest = gen_integer()
        with mock.patch.object(self.subscription, '_org_path') as org_path:
            with mock.patch.object(entities, '_handle_response') as handler:
                with mock.patch.object(client, 'post') as post:
                    response = self.subscription.upload(self.payload, manifest)
        self.assertEqual(org_path.call_count, 1)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(org_path.call_args[0], ('upload', self.payload))
        self.assertEqual(post.call_args[1]['files'], {'content': manifest})
        self.assertEqual(handler.return_value, response)


class SyncPlanTestCase(TestCase):
    """Tests for :class:`nailgun.entities.SyncPlan`."""

    def setUp(self):
        """Set ``self.sync_plan``."""
        self.sync_plan = entities.SyncPlan(
            config.ServerConfig('http://example.com'),
            id=gen_integer(min_value=1),
            organization=gen_integer(min_value=1),
        )

    def test_add_products(self):
        """Call :meth:`nailgun.entities.SyncPlan.add_products`."""
        with mock.patch.object(client, 'put') as client_put:
            with mock.patch.object(entities, '_handle_response') as handler:
                response = self.sync_plan.add_products({1: 2})
        self.assertEqual(client_put.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

    def test_remove_products(self):
        """Call :meth:`nailgun.entities.SyncPlan.remove_products`."""
        with mock.patch.object(client, 'put') as client_put:
            with mock.patch.object(entities, '_handle_response') as handler:
                response = self.sync_plan.remove_products({1: 2})
        self.assertEqual(client_put.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)


# 3. Other tests. -------------------------------------------------------- {{{1


class GetOrgTestCase(TestCase):
    """Test ``nailgun.entities._get_org``."""

    def setUp(self):
        """Set ``self.args``, which can be passed to ``_get_org``."""
        self.args = [config.ServerConfig('some url'), gen_string('utf8')]

    def test_default(self):
        """Run the method with a sane and normal set of arguments."""
        with mock.patch.object(entities.Organization, 'search') as search:
            search.return_value = [mock.Mock()]
            self.assertEqual(
                entities._get_org(*self.args),  # pylint:disable=W0212
                search.return_value[0].read.return_value,
            )
        self.assertEqual(search.call_count, 1)

    def test_api_response_error(self):
        """Trigger an :class:`nailgun.entities.APIResponseError`."""
        for return_value in ([], [mock.Mock() for _ in range(2)]):
            with mock.patch.object(entities.Organization, 'search') as search:
                search.return_value = return_value
                with self.assertRaises(entities.APIResponseError):
                    # pylint:disable=protected-access
                    entities._get_org(*self.args)
            self.assertEqual(search.call_count, 1)


class HandleResponseTestCase(TestCase):
    """Test ``nailgun.entities._handle_response``."""

    def test_default(self):
        """Don't give the response any special status code."""
        response = mock.Mock()
        self.assertEqual(
            entities._handle_response(response, 'foo'),  # pylint:disable=W0212
            response.json.return_value,
        )
        self.assertEqual(
            response.mock_calls,
            [mock.call.raise_for_status(), mock.call.json()],
        )

    def test_no_content(self):
        """Give the response an HTTP "NO CONTENT" status code."""
        response = mock.Mock()
        response.status_code = NO_CONTENT
        self.assertEqual(
            entities._handle_response(response, 'foo'),  # pylint:disable=W0212
            None,
        )
        self.assertEqual(response.mock_calls, [mock.call.raise_for_status()])

    def test_accepted_v1(self):
        """Give the response an HTTP "ACCEPTED" status code.

        Call ``_handle_response`` twice:

        * Do not pass the ``synchronous`` argument.
        * Pass ``synchronous=False``.

        """
        response = mock.Mock()
        response.status_code = ACCEPTED
        for args in [response, 'foo'], [response, 'foo', False]:
            self.assertEqual(
                entities._handle_response(*args),  # pylint:disable=W0212
                response.json.return_value,
            )
            self.assertEqual(
                response.mock_calls,
                [mock.call.raise_for_status(), mock.call.json()],
            )
            response.reset_mock()

    def test_accepted_v2(self):
        """Give the response an HTTP "ACCEPTED" status code.

        Pass ``synchronous=True`` as an argument.

        """
        response = mock.Mock()
        response.status_code = ACCEPTED
        response.json.return_value = {'id': gen_integer()}
        with mock.patch.object(entities, 'ForemanTask') as foreman_task:
            self.assertEqual(
                foreman_task.return_value.poll.return_value,
                # pylint:disable=protected-access
                entities._handle_response(response, 'foo', True),
            )


class VersionTestCase(TestCase):
    """Tests for entities that vary based on the server's software version."""

    @classmethod
    def setUpClass(cls):
        """Create several server configs with different versions."""
        super(VersionTestCase, cls).setUpClass()
        cls.cfg_608 = config.ServerConfig('bogus url', version='6.0.8')
        cls.cfg_610 = config.ServerConfig('bogus url', version='6.1.0')

    def test_missing_org_id(self):
        """Test methods for which no organization ID is returned.

        Affected methods:

        * :meth:`nailgun.entities.ContentView.read`
        * :meth:`nailgun.entities.Product.read`

        Assert that ``read_json``, ``_get_org`` and ``read`` are all called
        once, and that the second is called with the correct arguments.

        """
        for entity in (entities.ContentView, entities.Product):
            # Version 6.0.8
            label = gen_integer()  # unrealistic value
            with mock.patch.object(EntityReadMixin, 'read_json') as read_json:
                read_json.return_value = {'organization': {'label': label}}
                with mock.patch.object(entities, '_get_org') as helper:
                    with mock.patch.object(EntityReadMixin, 'read') as read:
                        entity(self.cfg_608).read()
            self.assertEqual(read_json.call_count, 1)
            self.assertEqual(helper.call_count, 1)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(helper.call_args[0], (self.cfg_608, label))

            # Version 6.1.0
            with mock.patch.object(EntityReadMixin, 'read') as read:
                entity(self.cfg_610).read()
            self.assertEqual(read.call_args[0][2], None)

    def test_lifecycle_environment(self):
        """Create a :class:`nailgun.entities.LifecycleEnvironment`.

        Assert that
        :meth:`nailgun.entities.LifecycleEnvironment.create_payload` returns a
        dict having a ``prior`` key in Satellite 6.0.8 and ``prior_id`` in
        Satellite 6.1.0.

        """
        payload = entities.LifecycleEnvironment(
            self.cfg_608,
            prior=1,
        ).create_payload()
        self.assertNotIn('prior_id', payload)
        self.assertIn('prior', payload)

        payload = entities.LifecycleEnvironment(
            self.cfg_610,
            prior=1,
        ).create_payload()
        self.assertNotIn('prior', payload)
        self.assertIn('prior_id', payload)

    def test_hostgroup_fields(self):
        """Check :class:`nailgun.entities.HostGroup`'s fields.

        Assert that version 6.1.0 adds the ``content_view`` and
        ``lifecycle_environment`` fields.

        """
        entity_608 = entities.HostGroup(self.cfg_608)
        entity_610 = entities.HostGroup(self.cfg_610)
        for field_name in ('content_view', 'lifecycle_environment'):
            self.assertNotIn(field_name, entity_608.get_fields())
            self.assertIn(field_name, entity_610.get_fields())

    def test_repository_fields(self):
        """Check :class:`nailgun.entities.Repository`'s fields.

        Assert that ``Repository`` has fields named "docker_upstream_name" and
        "checksum_type", and that "docker" is a choice for the "content_type"
        field starting with version 6.1.

        """
        repo_608 = entities.Repository(self.cfg_608)
        repo_610 = entities.Repository(self.cfg_610)
        for field_name in ('docker_upstream_name', 'checksum_type'):
            self.assertNotIn(field_name, repo_608.get_fields())
            self.assertIn(field_name, repo_610.get_fields())
        self.assertNotIn(
            'docker',
            repo_608.get_fields()['content_type'].choices
        )
        self.assertIn('docker', repo_610.get_fields()['content_type'].choices)

    def test_subnet_fields(self):
        """Check :class:`nailgun.entities.Subnet`'s fields.

        Assert that ``Subnet`` has the following fields starting in version
        6.1:

        * boot_mode
        * dhcp
        * dns
        * location
        * organization
        * tftp

        """
        subnet_608 = entities.Subnet(self.cfg_608)
        subnet_610 = entities.Subnet(self.cfg_610)
        for field_name in (
                'boot_mode',
                'dhcp',
                'dns',
                'location',
                'organization',
                'tftp'):
            self.assertNotIn(field_name, subnet_608.get_fields())
            self.assertIn(field_name, subnet_610.get_fields())
