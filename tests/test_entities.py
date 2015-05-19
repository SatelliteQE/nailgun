"""Tests for :mod:`nailgun.entities`."""
from datetime import datetime
from ddt import data, ddt, unpack
from fauxfactory import gen_integer
from nailgun import client, config, entities
from nailgun.entity_mixins import EntityReadMixin, NoSuchPathError
from sys import version_info
from unittest import TestCase
import mock
# pylint:disable=too-many-public-methods


@ddt
class PathTestCase(TestCase):
    """Tests for extensions of :meth:`nailgun.entity_mixins.Entity.path`."""
    longMessage = True

    def setUp(self):
        """Set ``self.server_config`` and ``self.id_``."""
        self.server_config = config.ServerConfig('http://example.com')
        self.id_ = gen_integer(min_value=1)
        if version_info.major == 2:
            self.re_assertion = self.assertRegexpMatches
        else:
            self.re_assertion = self.assertRegex  # pylint:disable=no-member

    @data(
        (entities.AbstractDockerContainer, '/containers'),
        (entities.ActivationKey, '/activation_keys'),
        (entities.ConfigTemplate, '/config_templates'),
        (entities.ContentView, '/content_views'),
        (entities.ContentViewVersion, '/content_view_versions'),
        (entities.ForemanTask, '/tasks'),
        (entities.Organization, '/organizations'),
        (entities.Product, '/products'),
        (entities.Repository, '/repositories'),
        (entities.SmartProxy, '/smart_proxies'),
        (entities.System, '/systems'),
    )
    @unpack
    def test_path_without_which(self, entity, path):
        """Test what happens when the ``which`` argument is omitted.

        Assert that ``path`` returns a valid string when the ``which`` argument
        is omitted, regardless of whether an entity ID is provided.

        """
        # There is no API path for all foreman tasks.
        if entity != entities.ForemanTask:
            self.assertIn(path, entity(self.server_config).path(), entity)
        self.assertIn(
            '{0}/{1}'.format(path, self.id_),
            entity(self.server_config, id=self.id_).path(),
            entity
        )

    @data(
        (entities.AbstractDockerContainer, 'containers', 'logs'),
        (entities.AbstractDockerContainer, 'containers', 'power'),
        (entities.ActivationKey, '/activation_keys', 'add_subscriptions'),
        (entities.ActivationKey, '/activation_keys', 'content_override'),
        (entities.ActivationKey, '/activation_keys', 'releases'),
        (entities.ActivationKey, '/activation_keys', 'remove_subscriptions'),
        (entities.ContentView, '/content_views', 'available_puppet_module_names'),  # noqa pylint:disable=C0301
        (entities.ContentView, '/content_views', 'content_view_puppet_modules'),  # noqa pylint:disable=C0301
        (entities.ContentView, '/content_views', 'content_view_versions'),
        (entities.ContentView, '/content_views', 'copy'),
        (entities.ContentView, '/content_views', 'publish'),
        (entities.ContentViewVersion, '/content_view_versions', 'promote'),
        (entities.Organization, '/organizations', 'products'),
        (entities.Organization, '/organizations', 'subscriptions'),
        (entities.Organization, '/organizations', 'subscriptions/delete_manifest'),  # noqa pylint:disable=C0301
        (entities.Organization, '/organizations', 'subscriptions/refresh_manifest'),  # noqa pylint:disable=C0301
        (entities.Organization, '/organizations', 'subscriptions/upload'),
        (entities.Organization, '/organizations', 'sync_plans'),
        (entities.Product, '/products', 'repository_sets'),
        (entities.Product, '/products', 'repository_sets/2396/disable'),
        (entities.Product, '/products', 'repository_sets/2396/enable'),
        (entities.Repository, '/repositories', 'sync'),
        (entities.Repository, '/repositories', 'upload_content'),
    )
    @unpack
    def test_self_path_with_which(self, entity, path, which):
        """Test what happens when an entity ID is given and ``which=which``.

        Assert that when ``entity(id=<id>).path(which=which)`` is called, the
        resultant path contains the following string::

            'path/<id>/which'

        """
        gen_path = entity(self.server_config, id=self.id_).path(which=which)
        self.assertIn(
            '{0}/{1}/{2}'.format(path, self.id_, which),
            gen_path,
            entity.__name__
        )
        self.re_assertion(gen_path, '{0}$'.format(which), entity.__name__)

    @data(
        (entities.ConfigTemplate, '/config_templates', 'build_pxe_default'),
        (entities.ConfigTemplate, '/config_templates', 'revision'),
    )
    @unpack
    def test_base_path_with_which(self, entity, path, which):
        """Test what happens when no entity ID is given and ``which=which``.

        Assert that a path in the fllowing format is returned::

            {path}/{which}

        """
        gen_path = entity(self.server_config).path(which=which)
        self.assertIn('{0}/{1}'.format(path, which), gen_path, entity.__name__)
        self.re_assertion(gen_path, which + '$', entity.__name__)

    @data(
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
        (entities.SmartProxy, 'refresh'),
        (entities.System, 'self'),
    )
    @unpack
    def test_no_such_path(self, entity, path):
        """Test what happens when no entity ID is provided and ``which=path``.

        Assert that :class:`nailgun.entity_mixins.NoSuchPathError` is raised.

        """
        with self.assertRaises(NoSuchPathError):
            entity(self.server_config).path(which=path)

    def test_foremantask_path(self):
        """Test :meth:`nailgun.entities.ForemanTask.path`.

        Assert that correct paths are returned when:

        * an entity ID is provided and the ``which`` argument to ``path`` is
          omitted
        * ``which = 'bulk_search'``

        """
        self.assertIn(
            '/foreman_tasks/api/tasks/{0}'.format(self.id_),
            entities.ForemanTask(self.server_config, id=self.id_).path()
        )
        for gen_path in (
                entities.ForemanTask(self.server_config).path(
                    which='bulk_search'
                ),
                entities.ForemanTask(self.server_config, id=self.id_).path(
                    which='bulk_search'
                )
        ):
            self.assertIn('/foreman_tasks/api/tasks/bulk_search', gen_path)

    def test_syncplan_path(self):
        """Test :meth:`nailgun.entities.SyncPlan.path`.

        Assert that the correct paths are returned when the following paths are
        provided to :meth:`nailgun.entities.SyncPlan.path`:

        * ``add_products``
        * ``remove_products``

        """
        for which in ('add_products', 'remove_products'):
            path = entities.SyncPlan(
                self.server_config,
                id=2,
                organization=1,
            ).path(which)
            self.assertIn(
                'organizations/1/sync_plans/2/{0}'.format(which),
                path
            )
            self.re_assertion(path, '{0}$'.format(which))

    def test_system_path(self):
        """Test :meth:`nailgun.entities.System.path`.

        Assert that correct paths are returned when:

        * A UUID is provided and ``which`` is omitted.
        * A UUID is provided and ``which='self'``.
        * A UUID is omitted and ``which`` is omitted.
        * A UUID is omitted and ``which='base'``.

        """
        for gen_path in (
                entities.System(self.server_config, uuid=self.id_).path(),
                entities.System(self.server_config, uuid=self.id_).path(
                    which='self'
                )
        ):
            self.assertIn('/systems/{0}'.format(self.id_), gen_path)
            self.re_assertion(gen_path, '{0}$'.format(self.id_))
        for gen_path in (
                entities.System(self.server_config).path(),
                entities.System(self.server_config).path(which='base')):
            self.assertIn('/systems', gen_path)
            self.re_assertion(gen_path, 'systems$')


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
                entities.Host,
                entities.HostCollection,
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
            if version_info < (3, 4):  # subTest() introduced in Python 3.4
                self.assertIsInstance(
                    entity(self.cfg, **params).create_payload(),
                    dict
                )
            else:
                with self.subTest(entity):  # pylint:disable=no-member
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


@ddt
class OrganizationTestCase(TestCase):
    """Tests for :class:`nailgun.entities.Organization`."""

    def setUp(self):
        """Set ``self.server_config`` and ``self.entity_id``."""
        self.server_config = config.ServerConfig(
            'http://example.com',
            auth=('foo', 'bar'),
            verify=False
        )
        self.entity_id = gen_integer(min_value=1)

    @data(200, 202)
    def test_delete_manifest(self, http_status_code):
        """Call :meth:`nailgun.entities.Organization.delete_manifest`.

        Assert that :meth:`nailgun.entities.Organization.delete_manifest`
        returns a dictionary when an HTTP 202 or some other success status code
        is returned.

        """
        # `client.post` will return this.
        post_return = mock.Mock()
        post_return.status_code = http_status_code
        post_return.raise_for_status.return_value = None
        post_return.json.return_value = {'id': gen_integer()}  # mock task ID

        # Start by patching `client.post` and `ForemanTask.poll`...
        # NOTE: Python 3 allows for better nested context managers.
        with mock.patch.object(client, 'post') as client_post:
            client_post.return_value = post_return
            with mock.patch.object(entities.ForemanTask, 'poll') as ft_poll:
                ft_poll.return_value = {}

                # ... then see if `delete_manifest` acts correctly.
                for synchronous in (True, False):
                    reply = entities.Organization(
                        self.server_config,
                        id=self.entity_id
                    ).delete_manifest(synchronous)
                    self.assertIsInstance(reply, dict)

    def test_subscriptions(self):
        """Call :meth:`nailgun.entities.Organization.subscriptions`.

        Asserts that :meth:`nailgun.entities.Organization.subscriptions`
        returns a list.

        """
        # Create a mock server response object.
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {u'results': []}

        with mock.patch.object(client, 'get') as mocked_client_get:
            mocked_client_get.return_value = mock_response
            # See if `subscriptions` behaves correctly.
            response = entities.Organization(
                self.server_config,
                id=self.entity_id,
            ).subscriptions()
            self.assertEqual(response, [])


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
                entities.AbstractDockerContainer,
                entities.ConfigTemplate,
                entities.ContentView,
                entities.ContentViewFilter,
                entities.Domain,
                entities.Host,
                entities.HostCollection,
                entities.Location,
                entities.Media,
                entities.OperatingSystem,
                entities.Product,
                entities.PuppetModule,
                entities.Repository,
                entities.System,
                entities.User,
        ):
            with mock.patch.object(EntityReadMixin, 'read_json') as read_json:
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    if version_info < (3, 4):  # subTest() introduced in 3.4
                        entity(self.cfg).read()
                        self.assertEqual(read_json.call_count, 1)
                        self.assertEqual(read.call_count, 1)
                    else:
                        with self.subTest(entity):  # pylint:disable=no-member
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
        # read.call_args[0][2] is the `ignore` argument to read()
        self.assertIn('account_password', read.call_args[0][2])

    def test_ignore_arg_v2(self):
        """Call :meth:`nailgun.entities.DockerComputeResource.read`.

        Assert that the entity ignores the 'password' field.

        """
        with mock.patch.object(EntityReadMixin, 'read') as read:
            entities.DockerComputeResource(self.cfg).read(attrs={'email': 1})
        # read.call_args[0][2] is the `ignore` argument to read()
        self.assertIn('password', read.call_args[0][2])


class AbstractDockerTestCase(TestCase):
    """Tests for :class:`nailgun.entities.AbstractDockerContainer`."""

    def setUp(self):
        """Set a server configuration at ``self.cfg``."""
        self.cfg = config.ServerConfig('http://example.com')

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
                entities.ContentViewFilter,
                entities.ContentViewVersion,
                entities.DockerComputeResource,
                entities.DockerHubContainer,
                entities.Domain,
                entities.Environment,
                entities.Errata,
                entities.Filter,
                entities.ForemanTask,
                entities.GPGKey,
                entities.Host,
                entities.HostClasses,
                entities.HostCollection,
                entities.HostCollectionErrata,
                entities.HostCollectionPackage,
                entities.HostGroup,
                entities.HostGroupClasses,
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
                entities.PartitionTable,
                entities.Permission,
                entities.Ping,
                entities.Product,
                entities.PuppetClass,
                entities.PuppetModule,
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
            (entities.ContentViewFilterRule, {'content_view_filter': 1}),
            (entities.ContentViewPuppetModule, {'content_view': 1}),
            (entities.OperatingSystemParameter, {'operatingsystem': 1}),
            (entities.SyncPlan, {'organization': 1}),
        ])
        for entity, params in entities_:
            if version_info < (3, 4):  # subTest() introduced in Python 3.4
                self.assertIsInstance(entity(self.cfg, **params), entity)
            else:
                with self.subTest(entity):  # pylint:disable=no-member
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
            if version_info < (3, 4):  # subTest() introduced in Python 3.4
                with self.assertRaises(TypeError):
                    entity(self.cfg)
            else:
                with self.subTest(entity):  # pylint:disable=no-member
                    with self.assertRaises(TypeError):
                        entity(self.cfg)
