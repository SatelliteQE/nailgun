# -*- encoding: utf-8 -*-
"""Tests for :mod:`nailgun.entities`."""
from datetime import datetime
from fauxfactory import gen_integer
from nailgun import client, config, entities
from nailgun.entity_mixins import EntityReadMixin, NoSuchPathError
from unittest2 import TestCase
import mock
# pylint:disable=too-many-lines
# The size of this file is a direct reflection of the size of module
# `nailgun.entities` and the Satellite API.


# This file is divided in to three sets of test cases (`TestCase` subclasses):
#
# 1. Tests for inherited methods.
# 2. Tests for entity-specific methods.
# 3. Other tests.
#
# 1. Tests for inherited methods. ---------------------------------------- {{{1


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

    def test_lifecycle_environment(self):
        """Create a :class:`nailgun.entities.LifecycleEnvironment`."""
        payload = entities.LifecycleEnvironment(
            self.cfg,
            prior=1,
        ).create_payload()
        self.assertNotIn('prior_id', payload)
        self.assertIn('prior', payload)

    def test_media(self):
        """Create a :class:`nailgun.entities.Media`."""
        payload = entities.Media(self.cfg, path_='foo').create_payload()
        self.assertNotIn('path_', payload['medium'])
        self.assertIn('path', payload['medium'])


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
                (entities.Organization, '/organizations'),
                (entities.Product, '/products'),
                (entities.RHCIDeployment, '/deployments'),
                (entities.Repository, '/repositories'),
                (entities.SmartProxy, '/smart_proxies'),
                (entities.System, '/systems'),
        ):
            with self.subTest():
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
                (entities.ContentView, 'available_puppet_module_names'),
                (entities.ContentView, 'content_view_puppet_modules'),
                (entities.ContentView, 'content_view_versions'),
                (entities.ContentView, 'copy'),
                (entities.ContentView, 'publish'),
                (entities.ContentViewVersion, 'promote'),
                (entities.Organization, 'products'),
                (entities.Organization, 'subscriptions'),
                (entities.Organization, 'subscriptions/delete_manifest'),
                (entities.Organization, 'subscriptions/refresh_manifest'),
                (entities.Organization, 'subscriptions/upload'),
                (entities.Organization, 'sync_plans'),
                (entities.Product, 'repository_sets'),
                (entities.Product, 'repository_sets/2396/disable'),
                (entities.Product, 'repository_sets/2396/enable'),
                (entities.Repository, 'sync'),
                (entities.Repository, 'upload_content'),
                (entities.RHCIDeployment, 'deploy'),
        ):
            with self.subTest():
                path = entity(self.cfg, id=self.id_).path(which=which)
                self.assertIn('{}/{}'.format(self.id_, which), path)
                self.assertRegex(path, which + '$')

    def test_noid_and_which(self):
        """Execute ``entity().path(which=…)``."""
        for entity, which in (
                (entities.ConfigTemplate, 'build_pxe_default'),
                (entities.ConfigTemplate, 'revision'),
        ):
            with self.subTest():
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

    def test_sync_plan(self):
        """Test :meth:`nailgun.entities.SyncPlan.path`.

        Assert that the following return appropriate paths:

        * ``SyncPlan(id=…).path('add_products')``
        * ``SyncPlan(id=…).path('remove_products')``

        """
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

        * ``System().path('base')``
        * ``System().path()``
        * ``System(uuid=…).path('self')``
        * ``System(uuid=…).path()``

        """
        for path in (
                entities.System(self.cfg).path('base'),
                entities.System(self.cfg).path(),
        ):
            self.assertIn('/systems', path)
            self.assertRegex(path, 'systems$')
        for path in (
                entities.System(self.cfg, uuid=self.id_).path('self'),
                entities.System(self.cfg, uuid=self.id_).path(),
        ):
            self.assertIn('/systems/{}'.format(self.id_), path)
            self.assertRegex(path, '{}$'.format(self.id_))


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
        """Ensure ``read`` and ``read_json`` are both called once."""
        for entity in (
                # entities.DockerComputeResource,  # see test_attrs_arg_v2
                # entities.UserGroup,  # see test_attrs_arg_v2
                entities.AbstractContentViewFilter,
                entities.AbstractDockerContainer,
                entities.ConfigTemplate,
                entities.ContentView,
                entities.Domain,
                entities.Host,
                entities.HostCollection,
                entities.HostGroup,
                entities.Location,
                entities.Media,
                entities.OperatingSystem,
                entities.Product,
                entities.PuppetModule,
                entities.RPMContentViewFilter,
                entities.Repository,
                entities.System,
                entities.User,
        ):
            with mock.patch.object(EntityReadMixin, 'read_json') as read_json:
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    with self.subTest():
                        entity(self.cfg).read()
                        self.assertEqual(read_json.call_count, 1)
                        self.assertEqual(read.call_count, 1)

    def test_attrs_arg_v2(self):
        """Validate :meth:`nailgun.entities.UserGroup.read`.

        Check that the method calls ``read`` and ``read_json`` once, and that
        ``client.put`` is used to read the ``'admin'`` attribute.

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
                entities.AbstractDockerContainer(self.cfg),
                {'compute_resource_id': None},
                {'compute_resource': None},
            ),
            (
                entities.ConfigTemplate(self.cfg),
                {'template_kind_id': None},
                {'template_kind': None},
            ),
            (
                entities.ContentViewPuppetModule(self.cfg, content_view=1),
                {'uuid': None},
                {'puppet_module': None},
            ),
            (
                entities.Domain(self.cfg),
                {'dns_id': None, 'parameters': None},
                {'dns': None, 'domain_parameters_attributes': None},
            ),
            (
                entities.Host(self.cfg),
                {
                    # These two params are renamed individually.
                    'parameters': None,
                    'puppetclasses': None,
                    # The remaining params are nenamed programmatically.
                    'architecture_id': None,
                    'compute_profile_id': None,
                    'compute_resource_id': None,
                    'domain_id': None,
                    'environment_id': None,
                    'hostgroup_id': None,
                    'image_id': None,
                    'location_id': None,
                    'medium_id': None,
                    'model_id': None,
                    'operatingsystem_id': None,
                    'organization_id': None,
                    'owner_id': None,
                    'ptable_id': None,
                    'puppet_proxy_id': None,
                    'realm_id': None,
                    'sp_subnet_id': None,
                    'subnet_id': None,
                },
                {
                    # These two params are renamed individually.
                    'host_parameters_attributes': None,
                    'puppet_classess': None,
                    # The remaining params are nenamed programmatically.
                    'architecture': None,
                    'compute_profile': None,
                    'compute_resource': None,
                    'domain': None,
                    'environment': None,
                    'hostgroup': None,
                    'image': None,
                    'location': None,
                    'medium': None,
                    'model': None,
                    'operatingsystem': None,
                    'organization': None,
                    'owner': None,
                    'ptable': None,
                    'puppet_proxy': None,
                    'realm': None,
                    'sp_subnet': None,
                    'subnet': None,
                }
            ),
            (
                entities.HostCollection(self.cfg),
                {'organization_id': None, 'system_ids': [1]},
                {'organization': None, 'systems': [{'id': 1}]},
            ),
            (
                entities.HostGroup(self.cfg),
                {
                    'ancestry': None,  # renamed to 'parent'
                    'architecture_id': None,
                    'domain_id': None,
                    'environment_id': None,
                    'medium_id': None,
                    'operatingsystem_id': None,
                    'ptable_id': None,
                    'realm_id': None,
                    'subnet_id': None,
                },
                {
                    'architecture': None,
                    'domain': None,
                    'environment': None,
                    'medium': None,
                    'operatingsystem': None,
                    'parent': None,  # renamed from 'ancestry'
                    'ptable': None,
                    'realm': None,
                    'subnet': None,
                },
            ),
            (
                entities.Product(self.cfg),
                {'gpg_key_id': None, 'sync_plan_id': None},
                {'gpg_key': None, 'sync_plan': None},
            ),
            (
                entities.Repository(self.cfg),
                {'gpg_key_id': None},
                {'gpg_key': None},
            ),
            (
                entities.System(self.cfg),
                {
                    'checkin_time': None,
                    'hostCollections': None,
                    'installedProducts': None,
                    'organization_id': None,
                },
                {
                    'last_checkin': None,
                    'host_collections': None,
                    'installed_products': None,
                    'organization': None,
                },
            ),
            (
                entities.User(self.cfg),
                {'auth_source_id': None},
                {'auth_source': None},
            ),
        )
        for entity, attrs_before, attrs_after in test_data:
            with mock.patch.object(EntityReadMixin, 'read') as read:
                entity.read(attrs=attrs_before)
            self.assertEqual(read.call_args[0][1], attrs_after)

    def test_ignore_arg_v1(self):
        """Call :meth:`nailgun.entities.AuthSourceLDAP.read`.

        Assert that the entity ignores the 'account_password' field.

        """
        with mock.patch.object(EntityReadMixin, 'read') as read:
            entities.AuthSourceLDAP(self.cfg).read(attrs={})
        # `call_args` is a two-tupe of (positional, keyword) args.
        self.assertIn('account_password', read.call_args[0][2])

    def test_ignore_arg_v2(self):
        """Call :meth:`nailgun.entities.DockerComputeResource.read`.

        Assert that the entity ignores the 'password' field.

        """
        with mock.patch.object(EntityReadMixin, 'read') as read:
            entities.DockerComputeResource(self.cfg).read(attrs={'email': 1})
        # `call_args` is a two-tupe of (positional, keyword) args.
        self.assertIn('password', read.call_args[0][2])


# 2. Tests for entity-specific methods. ---------------------------------- {{{1


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

    def test_power(self):
        """Call :meth:`nailgun.entities.AbstractDockerContainer.power`."""
        for power_action in ('start', 'stop', 'status'):
            with mock.patch.object(client, 'put') as client_put:
                with mock.patch.object(
                    entities,
                    '_handle_response',
                    return_value=gen_integer(),  # not realistic
                ) as handler:
                    response = self.abstract_dc.power(power_action)
            self.assertEqual(client_put.call_count, 1)
            self.assertEqual(handler.call_count, 1)
            self.assertEqual(handler.return_value, response)

            # `call_args` is a two-tupe of (positional, keyword) args.
            self.assertEqual(
                client_put.call_args[0][1],
                {'power_action': power_action},
            )

    def test_power_error(self):
        """Call :meth:`nailgun.entities.AbstractDockerContainer.power`.

        Pass an inappropriate argument and assert ``ValueError`` is raised.

        """
        with self.assertRaises(ValueError):
            self.abstract_dc.power('foo')

    def test_logs(self):
        """Call :meth:`nailgun.entities.AbstractDockerContainer.logs`."""
        for kwargs in (
                {},
                {'stdout': gen_integer()},
                {'stderr': gen_integer()},
                {'tail': gen_integer()},
                {
                    'stderr': gen_integer(),
                    'stdout': gen_integer(),
                    'tail': gen_integer(),
                },
        ):
            with mock.patch.object(client, 'get') as client_get:
                with mock.patch.object(
                    entities,
                    '_handle_response',
                    return_value=gen_integer(),  # not realistic
                ) as handler:
                    response = self.abstract_dc.logs(**kwargs)
            self.assertEqual(client_get.call_count, 1)
            self.assertEqual(handler.call_count, 1)
            self.assertEqual(handler.return_value, response)

            # `call_args` is a two-tupe of (positional, keyword) args.
            self.assertEqual(client_get.call_args[1]['data'], kwargs)


class ActivationKeyTestCase(TestCase):
    """Tests for :class:`nailgun.entities.ActivationKey`."""

    def setUp(self):
        """Set ``self.activation_key``."""
        self.activation_key = entities.ActivationKey(
            config.ServerConfig('http://example.com'),
            id=gen_integer(min_value=1),
        )

    def test_add_subscriptions(self):
        """Call :meth:`nailgun.entities.ActivationKey.add_subscriptions`."""
        with mock.patch.object(client, 'put') as client_put:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value=gen_integer(),  # not realistic
            ) as handler:
                response = self.activation_key.add_subscriptions({1: 2})
        self.assertEqual(client_put.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

        # This was just executed: client_put(path='…', data={…}, …)
        # `call_args` is a two-tupe of (positional, keyword) args.
        self.assertEqual(client_put.call_args[0][1], {1: 2})

    def test_content_override(self):
        """Call :meth:`nailgun.entities.ActivationKey.content_override`."""
        with mock.patch.object(client, 'put') as client_put:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value=gen_integer(),  # not realistic
            ) as handler:
                content_label = gen_integer()
                value = gen_integer()
                response = self.activation_key.content_override(
                    content_label=content_label,
                    value=value,
                )
        self.assertEqual(client_put.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

        # This was just executed: client_put(path='…', data={…}, …)
        # `call_args` is a two-tupe of (positional, keyword) args.
        self.assertEqual(
            client_put.call_args[0][1]['content_override'],
            {'content_label': content_label, 'value': value},
        )


class OrganizationTestCase(TestCase):
    """Tests for :class:`nailgun.entities.Organization`."""

    def setUp(self):
        """Set ``self.org``."""
        self.org = entities.Organization(
            config.ServerConfig('http://example.com'),
            id=gen_integer(min_value=1),
        )

    def test_subscriptions(self):
        """Call :meth:`nailgun.entities.Organization.subscriptions`."""
        with mock.patch.object(client, 'get') as client_get:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value={'results': gen_integer()},  # not realistic
            ) as handler:
                response = self.org.subscriptions()
        self.assertEqual(client_get.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value['results'], response)

    def test_delete_manifest(self):
        """Call :meth:`nailgun.entities.Organization.delete_manifest`."""
        for synchronous in (True, False):
            with mock.patch.object(client, 'post') as client_post:
                with mock.patch.object(
                    entities,
                    '_handle_response',
                    return_value=gen_integer(),  # not realistic
                ) as handler:
                    response = self.org.delete_manifest(synchronous)
            self.assertEqual(client_post.call_count, 1)
            self.assertEqual(handler.call_count, 1)
            self.assertEqual(handler.return_value, response)

    def test_refresh_manifest(self):
        """Call :meth:`nailgun.entities.Organization.refresh_manifest`."""
        with mock.patch.object(client, 'put') as client_put:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value=gen_integer(),  # not realistic
            ) as handler:
                response = self.org.refresh_manifest()
        self.assertEqual(client_put.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

    def test_sync_plan(self):
        """Call :meth:`nailgun.entities.Organization.sync_plan`."""
        with mock.patch.object(client, 'post') as client_post:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value=gen_integer(),  # not realistic
            ) as handler:
                name = gen_integer()
                interval = gen_integer()
                response = self.org.sync_plan(name=name, interval=interval)
        self.assertEqual(client_post.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

        # This was just executed: client_post(path='…', data={…}, …)
        # `call_args` is a two-tupe of (positional, keyword) args.
        data = client_post.call_args[0][1]
        self.assertEqual(
            set(('interval', 'name', 'sync_date')),
            set(data.keys()),
        )
        self.assertEqual(data['interval'], interval)
        self.assertEqual(data['name'], name)
        self.assertIsInstance('sync_date', type(''))

    def test_list_rhproducts(self):
        """Call :meth:`nailgun.entities.Organization.list_rhproducts`."""
        with mock.patch.object(client, 'get') as client_get:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value={'results': gen_integer()},  # not realistic
            ) as handler:
                response = self.org.list_rhproducts()
        self.assertEqual(client_get.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value['results'], response)


class RHCIDeploymentTestCase(TestCase):
    """Tests for :class:`nailgun.entities.RHCIDeployment`."""

    def setUp(self):
        """Set ``self.rhci_deployment``."""
        self.rhci_deployment = entities.RHCIDeployment(
            config.ServerConfig('http://example.com'),
            id=gen_integer(min_value=1),
        )

    def test_add_hypervisors(self):
        """Call :meth:`nailgun.entities.RHCIDeployment.add_hypervisors`."""
        with mock.patch.object(client, 'put') as client_put:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value={'results': gen_integer()},  # not realistic
            ) as handler:
                hypervisor_ids = [gen_integer(), gen_integer(), gen_integer()]
                response = self.rhci_deployment.add_hypervisors(hypervisor_ids)
        self.assertEqual(client_put.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

        # `call_args` is a two-tupe of (positional, keyword) args.
        self.assertEqual(
            client_put.call_args[0][1],
            {'discovered_host_ids': hypervisor_ids},
        )

    def test_deploy(self):
        """Call :meth:`nailgun.entities.RHCIDeployment.deploy`."""
        with mock.patch.object(client, 'put') as client_put:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value={'results': gen_integer()},  # not realistic
            ) as handler:
                params = {'foo': gen_integer()}
                response = self.rhci_deployment.deploy(params)
        self.assertEqual(client_put.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

        # `call_args` is a two-tupe of (positional, keyword) args.
        self.assertEqual(client_put.call_args[0][1], params)

    def test_update(self):
        """Call :meth:`nailgun.entities.RHCIDeployment.update`."""
        with mock.patch.object(client, 'put') as client_put:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value={'results': gen_integer()},  # not realistic
            ) as handler:
                params = {'foo': gen_integer()}
                response = self.rhci_deployment.update(params)
        self.assertEqual(client_put.call_count, 1)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

        # `call_args` is a two-tupe of (positional, keyword) args.
        self.assertEqual(client_put.call_args[0][1], params)


# 3. Other tests. -------------------------------------------------------- {{{1


class VersionTestCase(TestCase):
    """Tests for entities that vary based on the server's software version."""

    @classmethod
    def setUpClass(cls):
        """Create several server configs with different versions."""
        super(VersionTestCase, cls).setUpClass()
        cls.cfg_608 = config.ServerConfig('bogus url', version='6.0.8')
        cls.cfg_610 = config.ServerConfig('bogus url', version='6.1.0')

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
