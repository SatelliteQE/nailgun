# -*- encoding: utf-8 -*-
"""Tests for :mod:`nailgun.entities`."""
import json
import os
from datetime import datetime, date
from fauxfactory import gen_integer, gen_string
from nailgun import client, config, entities
from nailgun.entity_mixins import (
    EntityCreateMixin,
    EntityReadMixin,
    EntitySearchMixin,
    EntityUpdateMixin,
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
    _BUILTIN_OPEN = '__builtin__.open'
else:
    from http.client import ACCEPTED, NO_CONTENT  # pylint:disable=import-error
    _BUILTIN_OPEN = 'builtins.open'

# pylint:disable=too-many-lines
# The size of this file is a direct reflection of the size of module
# `nailgun.entities` and the Satellite API.


def make_entity(cls, **kwargs):
    """Helper function to create entity with dummy ServerConfig"""
    cfg = config.ServerConfig(
        url='https://foo.bar', verify=False,
        auth=('foo', 'bar'))
    return cls(cfg, **kwargs)


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
        cls.cfg_610 = config.ServerConfig(
            'http://example.com', version='6.1.0')

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
                entities.ArfReport,
                entities.Audit,
                entities.AuthSourceLDAP,
                entities.Bookmark,
                entities.Capsule,
                entities.CommonParameter,
                entities.ComputeAttribute,
                entities.ComputeProfile,
                entities.ConfigGroup,
                entities.ConfigTemplate,
                entities.ProvisioningTemplate,
                entities.ReportTemplate,
                # entities.ContentUpload,  # see below
                entities.ContentCredential,
                entities.ContentView,
                entities.ContentViewVersion,
                entities.DiscoveredHost,
                entities.DiscoveryRule,
                entities.DockerComputeResource,
                entities.DockerHubContainer,
                entities.DockerRegistryContainer,
                entities.Domain,
                entities.Environment,
                entities.Errata,
                entities.ErratumContentViewFilter,
                entities.File,
                entities.Filter,
                entities.ForemanStatus,
                entities.ForemanTask,
                entities.GPGKey,
                entities.Host,
                entities.HostCollection,
                entities.HostCollectionErrata,
                entities.HostCollectionPackage,
                entities.HostGroup,
                entities.KatelloStatus,
                entities.LibvirtComputeResource,
                entities.LifecycleEnvironment,
                entities.JobInvocation,
                entities.JobTemplate,
                entities.Location,
                entities.Media,
                entities.Model,
                # entities.OSDefaultTemplate,  # see below
                entities.OperatingSystem,
                entities.Organization,
                entities.OVirtComputeResource,
                entities.PackageGroupContentViewFilter,
                entities.PartitionTable,
                entities.Permission,
                entities.Ping,
                entities.Package,
                entities.PackageGroup,
                entities.Product,
                entities.PuppetClass,
                entities.PuppetModule,
                entities.RPMContentViewFilter,
                entities.Realm,
                entities.RecurringLogic,
                entities.Registry,
                entities.Report,
                entities.Repository,
                entities.RepositorySet,
                entities.Role,
                entities.RoleLDAPGroups,
                entities.Setting,
                entities.SmartClassParameters,
                entities.SmartProxy,
                entities.SmartVariable,
                # entities.Snapshot,  # see below
                entities.Status,
                entities.Subnet,
                entities.Subscription,
                # entities.System,  # see below
                # entities.SystemPackage,  # see below
                entities.TemplateCombination,
                entities.Template,
                entities.TemplateKind,
                entities.User,
                entities.UserGroup,
                entities.VirtWhoConfig,
                entities.VMWareComputeResource,
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
            (entities.ContentUpload, {'repository': 1}),
            (entities.ContentViewComponent, {'composite_content_view': 1}),
            (entities.ContentViewFilterRule, {'content_view_filter': 1}),
            (entities.ContentViewPuppetModule, {'content_view': 1}),
            (entities.ExternalUserGroup, {'usergroup': 1}),
            (entities.HostPackage, {'host': 1}),
            (entities.HostSubscription, {'host': 1}),
            (entities.Interface, {'host': 1}),
            (entities.Image, {'compute_resource': 1}),
            (entities.OperatingSystemParameter, {'operatingsystem': 1}),
            (entities.OSDefaultTemplate, {'operatingsystem': 1}),
            (entities.OverrideValue, {'smart_class_parameter': 1}),
            (entities.OverrideValue, {'smart_variable': 1}),
            (entities.Parameter, {'domain': 1}),
            (entities.Parameter, {'host': 1}),
            (entities.Parameter, {'hostgroup': 1}),
            (entities.Parameter, {'location': 1}),
            (entities.Parameter, {'operatingsystem': 1}),
            (entities.Parameter, {'organization': 1}),
            (entities.Parameter, {'subnet': 1}),
            (entities.RepositorySet, {'product': 1}),
            (entities.Snapshot, {'host': 1}),
            (entities.SSHKey, {'user': 1}),
            (entities.SyncPlan, {'organization': 1}),
            (entities.TemplateInput, {'template': 1}),
        ])
        for entity, params in entities_:
            with self.subTest(entity):
                self.assertIsInstance(entity(self.cfg, **params), entity)
        # Deprecated entities
        deprecated_entities = [
            (entity, {})
            for entity in (
                entities.System,
                entities.SystemPackage,
            )
        ]
        for entity, params in deprecated_entities:
            with self.subTest(entity):
                self.assertIsInstance(entity(self.cfg_610, **params), entity)

    def test_required_params(self):
        """Instantiate entities that require extra parameters.

        Assert that ``TypeError`` is raised if the required extra parameters
        are not provided.

        """
        for entity in (
                entities.ContentViewComponent,
                entities.ContentViewFilterRule,
                entities.ContentViewPuppetModule,
                entities.ExternalUserGroup,
                entities.HostPackage,
                entities.HostSubscription,
                entities.Image,
                entities.OverrideValue,
                entities.OperatingSystemParameter,
                entities.OSDefaultTemplate,
                entities.Parameter,
                entities.SyncPlan,
                entities.TemplateInput,
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
        self.cfg_610 = config.ServerConfig(
            'http://example.com', version='6.1.0')
        self.id_ = gen_integer(min_value=1)

    def test_nowhich(self):
        """Execute ``entity().path()`` and ``entity(id=…).path()``."""
        for entity, path in (
                (entities.AbstractDockerContainer, '/containers'),
                (entities.ActivationKey, '/activation_keys'),
                (entities.Capsule, '/capsules'),
                (entities.ConfigTemplate, '/config_templates'),
                (entities.ProvisioningTemplate, '/provisioning_templates'),
                (entities.ReportTemplate, '/report_templates'),
                (entities.Role, '/roles'),
                (entities.ContentView, '/content_views'),
                (entities.ContentViewVersion, '/content_view_versions'),
                (entities.DiscoveredHost, '/discovered_hosts'),
                (entities.DiscoveryRule, '/discovery_rules'),
                (entities.Environment, '/environments'),
                (entities.Errata, '/errata'),
                (entities.Organization, '/organizations'),
                (entities.Host, '/hosts'),
                (entities.HostGroup, '/hostgroups'),
                (entities.Product, '/products'),
                (entities.PuppetClass, '/puppetclasses'),
                (entities.RHCIDeployment, '/deployments'),
                (entities.Repository, '/repositories'),
                (entities.Setting, '/settings'),
                (entities.SmartProxy, '/smart_proxies'),
                (entities.Subscription, '/subscriptions'),
                (entities.VirtWhoConfig,
                 '/foreman_virt_who_configure/api/v2/configs')
        ):
            with self.subTest((entity, path)):
                self.assertIn(path, entity(self.cfg).path())
                self.assertIn(
                    '{}/{}'.format(path, self.id_),
                    entity(self.cfg, id=self.id_).path()
                )
        # Deprecated entities
        for entity, path in (
                (entities.System, '/systems'),
        ):
            with self.subTest((entity, path)):
                self.assertIn(path, entity(self.cfg_610).path())
                self.assertIn(
                    '{}/{}'.format(path, self.id_),
                    entity(self.cfg_610, id=self.id_).path()
                )

    def test_id_and_which(self):
        """Execute ``entity(id=…).path(which=…)``."""
        for entity, which in (
                (entities.AbstractDockerContainer, 'logs'),
                (entities.AbstractDockerContainer, 'power'),
                (entities.ActivationKey, 'add_subscriptions'),
                (entities.ActivationKey, 'content_override'),
                (entities.ActivationKey, 'copy'),
                (entities.ActivationKey, 'host_collections'),
                (entities.ActivationKey, 'releases'),
                (entities.ActivationKey, 'remove_subscriptions'),
                (entities.ActivationKey, 'subscriptions'),
                (entities.ArfReport, 'download_html'),
                (entities.ConfigTemplate, 'clone'),
                (entities.ProvisioningTemplate, 'clone'),
                (entities.ReportTemplate, 'clone'),
                (entities.Role, 'clone'),
                (entities.ContentView, 'available_puppet_module_names'),
                (entities.ContentView, 'content_view_puppet_modules'),
                (entities.ContentView, 'content_view_versions'),
                (entities.ContentView, 'copy'),
                (entities.ContentView, 'publish'),
                (entities.ContentViewVersion, 'promote'),
                (entities.Environment, 'smart_class_parameters'),
                (entities.Host, 'enc'),
                (entities.Host, 'errata'),
                (entities.Host, 'errata/apply'),
                (entities.Host, 'errata/applicability'),
                (entities.Host, 'module_streams'),
                (entities.Host, 'packages'),
                (entities.Host, 'puppetclass_ids'),
                (entities.Host, 'smart_class_parameters'),
                (entities.Host, 'smart_variables'),
                (entities.HostGroup, 'clone'),
                (entities.HostGroup, 'puppetclass_ids'),
                (entities.HostGroup, 'rebuild_config'),
                (entities.HostGroup, 'smart_class_parameters'),
                (entities.HostGroup, 'smart_variables'),
                (entities.Organization, 'download_debug_certificate'),
                (entities.Organization, 'subscriptions'),
                (entities.Organization, 'subscriptions/delete_manifest'),
                (entities.Organization, 'subscriptions/manifest_history'),
                (entities.Organization, 'subscriptions/refresh_manifest'),
                (entities.Organization, 'subscriptions/upload'),
                (entities.Organization, 'sync_plans'),
                (entities.Product, 'sync'),
                (entities.PuppetClass, 'smart_class_parameters'),
                (entities.Repository, 'errata'),
                (entities.Repository, 'packages'),
                (entities.Repository, 'puppet_modules'),
                (entities.Repository, 'remove_content'),
                (entities.Repository, 'sync'),
                (entities.Repository, 'upload_content'),
                (entities.RHCIDeployment, 'deploy'),
                (entities.VirtWhoConfig, 'deploy_script')
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
                (entities.ProvisioningTemplate, 'build_pxe_default'),
                (entities.ProvisioningTemplate, 'revision'),
                (entities.ContentViewVersion, 'incremental_update'),
                (entities.DiscoveredHost, 'facts'),
                (entities.Errata, 'compare'),
                (entities.ForemanTask, 'bulk_resume'),
                (entities.ForemanTask, 'bulk_search'),
                (entities.ForemanTask, 'summary'),
                (entities.Host, 'bulk/install_content'),
                (entities.Template, 'imports'),
                (entities.Template, 'exports')
        ):
            with self.subTest((entity, which)):
                path = entity(self.cfg).path(which)
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
                (entities.HostGroup, 'rebuild_config'),
                (entities.Organization, 'products'),
                (entities.Organization, 'self'),
                (entities.Organization, 'subscriptions'),
                (entities.Organization, 'download_debug_certificate'),
                (entities.Organization, 'subscriptions/delete_manifest'),
                (entities.Organization, 'subscriptions/refresh_manifest'),
                (entities.Organization, 'subscriptions/upload'),
                (entities.Organization, 'sync_plans'),
                (entities.Product, 'repository_sets'),
                (entities.Repository, 'sync'),
                (entities.Repository, 'upload_content'),
                (entities.RHCIDeployment, 'deploy'),
                (entities.SmartProxy, 'refresh'),
                (entities.VirtWhoConfig, 'deploy_script'),
                (entities.VirtWhoConfig, 'configs')
        ):
            with self.subTest((entity, which)):
                with self.assertRaises(NoSuchPathError):
                    entity(self.cfg).path(which=which)
        # Deprecated entities
        for entity, which in (
                (entities.System, 'self'),
        ):
            with self.subTest((entity, which)):
                with self.assertRaises(NoSuchPathError):
                    entity(self.cfg_610).path(which=which)

    def test_arfreport(self):
        """Test :meth:`nailgun.entities.ArfReport.path`.
        Assert that the following return appropriate paths:
        * ``ArfReport(id=…).path()``
        * ``ArfReport(id=…).path('download_html')``
        """
        self.assertIn(
            'compliance/arf_reports/1',
            entities.ArfReport(self.cfg, id=1).path()
        )
        for which in ['download_html']:
            path = entities.ArfReport(
                self.cfg,
                id=1,
            ).path(which)
            self.assertIn('compliance/arf_reports/1/' + which, path)
            self.assertRegex(path, '{}$'.format(which))

    def test_os_default_template(self):
        """ Test ``nailgun.entities.OSDefaultTemplate.path``

        Assert that the following return appropriate paths:

        * ``OSDefaultTemplate(id=…).path()``
        """
        self.assertIn(
            'operatingsystems/1/os_default_templates/2',
            entities.OSDefaultTemplate(
                self.cfg, id=2, operatingsystem=1).path()
        )

    def test_externalusergroup(self):
        """Test :meth:`nailgun.entities.ExternalUserGroup.path`.

        Assert that the following return appropriate paths:

        * ``ExternalUserGroup(id=…,usergroup=…).path()``
        * ``ExternalUserGroup(id=…,usergroup=…).path('refresh')``

        """
        self.assertIn(
            'usergroups/1/external_usergroups/2',
            entities.ExternalUserGroup(self.cfg, id=2, usergroup=1).path()
        )
        for which in ['refresh']:
            path = entities.ExternalUserGroup(
                self.cfg,
                id=2,
                usergroup=1,
            ).path(which)
            self.assertIn('usergroups/1/external_usergroups/2/' + which, path)
            self.assertRegex(path, '{}$'.format(which))

    def test_repository_set(self):
        """Test :meth:`nailgun.entities.RepositorySet.path`.

        Assert that the following return appropriate paths:

        * ``RepositorySet(id=…).path()``
        * ``RepositorySet(id=…).path('available_repositories')``
        * ``RepositorySet(id=…).path('disable')``
        * ``RepositorySet(id=…).path('enable')``

        """
        self.assertIn(
            '/repository_sets/2',
            entities.RepositorySet(self.cfg, id=2, product=1).path()
        )
        for which in ('available_repositories', 'disable', 'enable'):
            path = entities.RepositorySet(
                self.cfg,
                id=2,
                product=1,
            ).path(which)
            self.assertIn('/repository_sets/2/' + which, path)
            self.assertRegex(path, '{}$'.format(which))

    def test_snapshot(self):
        """Test :meth:`nailgun.entities.Snapshot.path`.

        Assert that the following return appropriate paths:

        * ``Snapshot(id=…).path()``
        * ``Snapshot(id=…).path('revert')``

        """
        self.assertIn(
            'hosts/1/snapshots/snapshot-2',
            entities.Snapshot(self.cfg, id='snapshot-2', host=1).path()
        )
        which = 'revert'
        path = entities.Snapshot(
            self.cfg,
            id='snapshot-2',
            host=1,
        ).path(which)
        self.assertIn('hosts/1/snapshots/snapshot-2/' + which, path)
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
        system = entities.System(self.cfg_610)
        for path in (system.path(), system.path('base')):
            self.assertIn('/systems', path)
            self.assertRegex(path, 'systems$')

        system = entities.System(self.cfg_610, uuid=self.id_)
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

    def test_capsule(self):
        """Test :meth:`nailgun.entities.Capsule.path`.

        Assert that the following return appropriate paths:

        * ``Capsule().path('content_lifecycle_environments')``
        * ``Capsule().path('content_sync')``

        """
        capsule = entities.Capsule(self.cfg, id=gen_integer(1, 100))
        for which in (
                'content_lifecycle_environments',
                'content_sync'):
            with self.subTest(which):
                path = capsule.path(which)
                self.assertIn(
                    'capsules/{}/content/{}'.format(
                        capsule.id,  # pylint:disable=no-member
                        which.split('_', 1)[1],
                    ),
                    path
                )
                self.assertRegex(path, '{}/{}$'.format(*which.split('_', 1)))

    def test_hostsubscription(self):
        """Test :meth:`nailgun.entities.HostSubscription.path`.

        Assert that the following return appropriate paths:

        * ``HostSubscription(host=…).path('add_subscriptions')``
        * ``HostSubscription(host=…).path('remove_subscriptions')``

        """
        sub = entities.HostSubscription(self.cfg, host=gen_integer(1, 100))
        for which in ('add_subscriptions', 'remove_subscriptions'):
            with self.subTest(which):
                path = sub.path(which)
                self.assertIn(
                    'hosts/{}/subscriptions/{}'.format(
                        sub.host.id,  # pylint:disable=no-member
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
            entities.ConfigGroup(self.cfg),
            entities.DiscoveryRule(self.cfg),
            entities.DockerComputeResource(self.cfg),
            entities.Domain(self.cfg),
            entities.Host(self.cfg),
            entities.HostCollection(self.cfg),
            entities.HostGroup(self.cfg),
            entities.Location(self.cfg),
            entities.Media(self.cfg),
            entities.Organization(self.cfg),
            entities.Realm(self.cfg),
            entities.Registry(self.cfg),
            entities.SmartProxy(self.cfg),
            entities.UserGroup(self.cfg),
            entities.VirtWhoConfig(self.cfg)
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
    extended method could try to rename an attribute that does not exist.
    This class attempts to find such issues by creating an entity, calling
    :meth:`nailgun.entity_mixins.EntityCreateMixin.create_payload` and
    asserting that a ``dict`` is returned.

    """

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')
        cls.cfg_610 = config.ServerConfig(
            'http://example.com', version='6.1.0')

    def test_no_attributes(self):
        """Instantiate an entity and call ``create_payload`` on it."""
        entities_ = [
            (entity, {})
            for entity in (
                entities.AbstractComputeResource,
                entities.AbstractDockerContainer,
                entities.Architecture,
                entities.ConfigGroup,
                entities.ConfigTemplate,
                entities.ProvisioningTemplate,
                entities.ReportTemplate,
                entities.DiscoveredHost,
                entities.DiscoveryRule,
                entities.Domain,
                entities.Environment,
                entities.Filter,
                entities.Host,
                entities.HostCollection,
                entities.HostGroup,
                entities.JobTemplate,
                entities.LifecycleEnvironment,
                entities.Location,
                entities.Media,
                entities.OperatingSystem,
                entities.Registry,
                entities.Role,
                entities.SmartVariable,
                entities.Subnet,
                entities.User,
                entities.UserGroup,
                entities.VirtWhoConfig
            )
        ]
        entities_.extend([
            (entities.ExternalUserGroup, {'usergroup': 1}),
            (entities.Image, {'compute_resource': 1}),
            (entities.SyncPlan, {'organization': 1}),
            (entities.ContentViewFilterRule, {'content_view_filter': 1})
        ])
        for entity, params in entities_:
            with self.subTest():
                self.assertIsInstance(
                    entity(self.cfg, **params).create_payload(),
                    dict
                )

    def test_external_usergroup_payload(self):
        """Call ``create_payload`` on a :class:`nailgun.entities.ExternalUserGroup`."""
        payload = entities.ExternalUserGroup(
            self.cfg,
            usergroup=1,
        ).create_payload()
        self.assertEqual({'usergroup_id': 1}, payload)

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

    def test_host_collection(self):
        """Create a :class:`nailgun.entities.HostCollection`."""
        payload = entities.HostCollection(
            self.cfg_610,
            system=[1],
        ).create_payload()
        self.assertNotIn('system_ids', payload)
        self.assertIn('system_uuids', payload)

    def test_content_view_filter_rule(self):
        """Create a :class:`nailgun.entities.ContentViewFilterRule`."""
        errata_kwargs = {
            "id": 1,
            "uuid": "1a321570-cd30-4622-abff-2290b47ef814",
            "title": "Bird_Erratum",
            "errata_id": "RHEA-2012:0003",
            "issued": "2012-01-27",
            "updated": "2012-01-27",
            "severity": "",
            "description": "Bird_Erratum",
            "solution": "",
            "summary": "",
            "reboot_suggested": False,
            "name": "Bird_Erratum",
            "type": "security",
            "cves": [],
            "hosts_available_count": 0,
            "hosts_applicable_count": 0,
            "packages": ["stork-0.12-2.noarch"],
            "module_streams": [
                {
                    "name": "duck",
                    "stream": "0",
                    "version": "201809302113907",
                    "context": "deadbeef",
                    "arch": "noarch",
                    "id": 1,
                    "packages": [
                        "duck-0.8-1.noarch"
                    ]
                }
            ]

        }

        with mock.patch.object(entities.Errata, 'read_json') as read_json:
            read_json.return_value = errata_kwargs
            payload = entities.ContentViewFilterRule(
                self.cfg,
                content_view_filter=1,
                errata=1,
            ).create_payload()
            self.assertEqual("RHEA-2012:0003", payload['errata_id'])

    def test_image(self):
        """Create a :class:`nailgun.entities.Image`."""
        payload = entities.Image(
            self.cfg,
            compute_resource=1,
        ).create_payload()
        self.assertEqual({'image': {'compute_resource_id': 1}}, payload)

    def test_media(self):
        """Create a :class:`nailgun.entities.Media`."""
        payload = entities.Media(self.cfg, path_='foo').create_payload()
        self.assertNotIn('path_', payload['medium'])
        self.assertIn('path', payload['medium'])

    def test_discovery_rule(self):
        """Create a :class:`nailgun.entities.DiscoveryRule`."""
        payload = entities.DiscoveryRule(
            self.cfg,
            search_='foo',
        ).create_payload()
        self.assertNotIn('search_', payload['discovery_rule'])
        self.assertIn('search', payload['discovery_rule'])

    def test_override_value(self):
        """Create a :class:`nailgun.entities.OverrideValue`."""
        payload = entities.OverrideValue(
            self.cfg,
            smart_class_parameter=1,
        ).create_payload()
        self.assertNotIn('smart_class_parameter_id', payload)
        payload = entities.OverrideValue(
            self.cfg,
            smart_variable=1,
        ).create_payload()
        self.assertNotIn('smart_variable_id', payload)

    def test_job_template(self):
        """Create a :class:`nailgun.entities.JobTemplate`."""
        payload = entities.JobTemplate(
            self.cfg,
            effective_user={'value': 'foo'},
            name='brick system',
            template='rm -rf --no-preserve-root /',
        ).create_payload()
        self.assertNotIn('effective_user', payload)
        self.assertIn('effective_user', payload['job_template']['ssh'])

    def test_subnet(self):
        """Create a :class:`nailgun.entities.Subnet`."""
        payload = entities.Subnet(
            self.cfg,
            from_='10.0.0.1',
        ).create_payload()
        self.assertNotIn('from_', payload['subnet'])
        self.assertIn('from', payload['subnet'])


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

    def test_report_template_v1(self):
        """Test ``ReportTemplate(name='testName')``."""
        entity = entities.ReportTemplate(self.cfg, name='testName')
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertEqual(entity.name, 'testName')

    def test_report_template_v2(self):
        """Test ``ReportTemplate()``."""
        entity = entities.ReportTemplate(self.cfg)
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertNotEqual(entity.name, '')

    def test_report_template_v3(self):
        """Test ``ReportTemplate(default=True)``."""
        entity = entities.ReportTemplate(self.cfg, default=True)
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertEqual(
            _get_required_field_names(entity),
            set(entity.get_values().keys()),
        )

    def test_report_template_v4(self):
        """Test ``ReportTemplate(default=False)``."""
        entity = entities.ReportTemplate(self.cfg, default=False)
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertEqual(
            _get_required_field_names(entity),
            set(entity.get_values().keys()),
        )

    def test_provisioning_template_v1(self):
        """Test ``ProvisioningTemplate(snippet=True)``."""
        entity = entities.ProvisioningTemplate(self.cfg, snippet=True)
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertEqual(
            _get_required_field_names(entity),
            set(entity.get_values().keys()),
        )

    def test_provisioning_template_v2(self):
        """Test ``ProvisioningTemplate(snippet=False)``."""
        entity = entities.ProvisioningTemplate(self.cfg, snippet=False)
        with mock.patch.object(EntityCreateMixin, 'create_raw'):
            with mock.patch.object(EntityReadMixin, 'read_raw'):
                entity.create_missing()
        self.assertEqual(
            _get_required_field_names(entity).union(['template_kind']),
            set(entity.get_values().keys()),
        )

    def test_provisioning_template_v3(self):
        """Test ``ProvisioningTemplate(snippet=False, template_kind=…)``."""
        tk_id = gen_integer()
        entity = entities.ProvisioningTemplate(
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

    def test_external_usergroup(self):
        """Test ``ExternalUserGroup()`` """
        entity = entities.ExternalUserGroup(self.cfg, usergroup=1)
        with mock.patch.object(EntityCreateMixin, 'create_missing'):
            entity.create_missing()
        self.assertTrue(entity.get_fields()['usergroup'].required)

    def test_host_v1(self):
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

    def test_host_v2(self):
        """Test ``Host()`` with providing all the optional entities unlinked"""
        # pylint:disable=no-member,too-many-locals
        org = entities.Organization(self.cfg, id=1)
        loc = entities.Location(self.cfg, id=1)
        domain = entities.Domain(
            self.cfg,
            id=1,
            location=[2],
            organization=[2],
        )
        env = entities.Environment(
            self.cfg,
            id=1,
            location=[2],
            organization=[2],
        )
        arch = entities.Architecture(self.cfg, id=1)
        ptable = entities.PartitionTable(
            self.cfg,
            id=1,
            location=[2],
            organization=[2],
        )
        oper_sys = entities.OperatingSystem(
            self.cfg,
            id=1,
            architecture=[2],
            ptable=[2],
        )
        media = entities.Media(
            self.cfg,
            id=1,
            location=[2],
            operatingsystem=[2],
            organization=[2],
        )
        entity = entities.Host(
            self.cfg,
            architecture=arch,
            domain=domain,
            environment=env,
            location=loc,
            medium=media,
            operatingsystem=oper_sys,
            organization=org,
            ptable=ptable,
        )
        with mock.patch.object(EntityCreateMixin, 'create_json'):
            with mock.patch.object(EntityReadMixin, 'read_json'):
                with mock.patch.object(EntityUpdateMixin, 'update_json'):
                    with mock.patch.object(EntityReadMixin, 'read'):
                        entity.create_missing()
        for subentity in domain, env, media:
            self.assertIn(loc.id, [loc_.id for loc_ in subentity.location])
            self.assertIn(org.id, [org_.id for org_ in subentity.organization])
        self.assertIn(arch.id, [arch_.id for arch_ in oper_sys.architecture])
        self.assertIn(ptable.id, [ptable_.id for ptable_ in oper_sys.ptable])
        self.assertIn(oper_sys.id, [os_.id for os_ in media.operatingsystem])

    def test_host_v3(self):
        """Test ``Host()`` providing optional entities with id only.
        Check that additional read was called for that entities.
        """
        # pylint:disable=no-member,too-many-locals
        optional = {
            'domain': entities.Domain(self.cfg, id=1),
            'env': entities.Environment(self.cfg, id=1),
            'arch': entities.Architecture(self.cfg, id=1),
            'oper_sys': entities.OperatingSystem(self.cfg, id=1),
            'media': entities.Media(self.cfg, id=1),
        }
        entity = entities.Host(
            self.cfg,
            architecture=optional['arch'],
            domain=optional['domain'],
            environment=optional['env'],
            medium=optional['media'],
            operatingsystem=optional['oper_sys'],
        )
        with mock.patch.object(EntityCreateMixin, 'create_json'):
            with mock.patch.object(EntityReadMixin, 'read_json'):
                with mock.patch.object(EntityUpdateMixin, 'update_json'):
                    with mock.patch.object(EntityReadMixin, 'read') as read:
                        entity.create_missing()
        self.assertGreaterEqual(read.call_count, len(optional))

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
        self.cfg_610 = config.ServerConfig(
            'http://example.com', version='6.1.0')

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
                entities.ContentViewComponent(self.cfg, composite_content_view=2, content_view=1),
                entities.ContentViewPuppetModule(self.cfg, content_view=2),
                entities.ExternalUserGroup(self.cfg, usergroup=1),
                entities.Interface(self.cfg, host=2),
                entities.Image(self.cfg, compute_resource=1),
                entities.OperatingSystemParameter(self.cfg, operatingsystem=2),
                entities.OSDefaultTemplate(self.cfg, operatingsystem=2),
                entities.OverrideValue(self.cfg, smart_class_parameter=2),
                entities.OverrideValue(self.cfg, smart_variable=2),
                entities.Parameter(self.cfg, domain=2),
                entities.Parameter(self.cfg, host=2),
                entities.Parameter(self.cfg, hostgroup=2),
                entities.Parameter(self.cfg, location=2),
                entities.Parameter(self.cfg, operatingsystem=2),
                entities.Parameter(self.cfg, organization=2),
                entities.Parameter(self.cfg, subnet=2),
                entities.RepositorySet(self.cfg, product=2),
                entities.Snapshot(self.cfg, host=2),
                entities.SSHKey(self.cfg, user=2),
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
                # entities.DiscoveryRule,  # see test_discovery_rule
                # entities.DockerComputeResource,  # see test_attrs_arg_v2
                # entities.HostGroup,  # see HostGroupTestCase.test_read
                # entities.Product,  # See Product.test_read
                # entities.UserGroup,  # see test_attrs_arg_v2
                entities.ContentView,
                entities.Domain,
                entities.Filter,
                entities.Host,
                entities.Media,
                entities.RHCIDeployment,
        ):
            with mock.patch.object(EntityReadMixin, 'read_json') as read_json:
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    with self.subTest():
                        entity(self.cfg).read()
                        self.assertEqual(read_json.call_count, 1)
                        self.assertEqual(read.call_count, 1)
        # Deprecated entities
        for entity in (
                entities.System,
        ):
            with mock.patch.object(EntityReadMixin, 'read_json') as read_json:
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    with self.subTest():
                        entity(self.cfg_610).read()
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
                {'parameters': None},
                {'host_parameters_attributes': None},
            ),
            (
                entities.System(self.cfg_610),
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
            (
                entities.Filter(self.cfg),
                {'override?': None,
                 'unlimited?': None},
                {'override': None,
                 'unlimited': None},
            )
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
                (entities.Errata,
                 {'content_view_version', 'environment', 'repository'}),
                (entities.OVirtComputeResource, {'password'}),
                (entities.SmartProxy, {'download_policy'}),
                (entities.SmartClassParameters, {'hidden_value'}),
                (entities.SmartVariable, {'hidden_value'}),
                (entities.Subnet, {
                    'discovery',
                    'remote_execution_proxy',
                    'subnet_parameters_attributes'}),
                (entities.Subscription, {'organization'}),
                (entities.Repository, {'organization', 'upstream_password'}),
                (entities.User, {'password'}),
                (entities.VirtWhoConfig, {'hypervisor_password'}),
                (entities.VMWareComputeResource, {'password'}),
        ):
            with self.subTest(entity):
                with mock.patch.object(EntityReadMixin, 'read') as read,\
                        mock.patch.object(EntityReadMixin, 'read_json'):
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

    def test_interface_ignore_arg(self):
        """Call :meth:`nailgun.entities.Interface.read`.

        Assert that entity`s predefined values of ``ignore`` are always
        correctly passed on.
        """
        for input_type, actual_ignore in (
                ('interface', {'host', 'username', 'password', 'provider',
                               'mode', 'bond_options', 'attached_to', 'tag',
                               'attached_devices'}),
                ('bmc', {'host', 'mode', 'bond_options', 'attached_to', 'tag',
                         'attached_devices'}),
                ('bond', {'host', 'username', 'password', 'provider',
                          'attached_to', 'tag'}),
                ('bridge', {'host', 'username', 'password', 'provider', 'mode',
                            'bond_options', 'attached_to', 'tag'}),
                ('virtual', {'host', 'username', 'password', 'provider',
                             'mode', 'bond_options', 'attached_devices'}),
        ):
            with self.subTest(input_type):
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    with mock.patch.object(
                        EntityReadMixin,
                        'read_json',
                        return_value={'type': input_type},
                    ):
                        entities.Interface(
                            self.cfg, id=2, host=2, type=input_type).read()
                # `call_args` is a two-tuple of (positional, keyword) args.
                self.assertEqual(actual_ignore, read.call_args[0][2])

    def test_parameter_ignore_arg(self):
        """Call :meth:`nailgun.entities.Parameter.read`.

        Assert that entity`s predefined values of ``ignore`` are always
        correctly passed on.
        """
        parents = {
            'domain', 'host', 'hostgroup', 'location', 'operatingsystem',
            'organization', 'subnet'
        }
        for parent in parents:
            with self.subTest(parent):
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    with mock.patch.object(
                        EntityReadMixin,
                        'read_json',
                        return_value={parent: 3},
                    ):
                        entities.Parameter(
                            self.cfg, id=2, **{parent: 3}).read()
                # `call_args` is a two-tuple of (positional, keyword) args.
                self.assertEqual(parents, read.call_args[0][2])

    def test_snapshot_ignore_arg(self):
        """Call :meth:`nailgun.entities.Snapshot.read`.

        Assert that entity`s predefined values of ``ignore`` are always
        correctly passed on.
        """
        with mock.patch.object(EntityReadMixin, 'read') as read:
            with mock.patch.object(
                EntityReadMixin,
                'read_json',
                return_value={'host': 3},
            ):
                entities.Snapshot(self.cfg, id=2, host=3).read()
        # `call_args` is a two-tuple of (positional, keyword) args.
        self.assertEqual(set(['host']), read.call_args[0][2])

    def test_host_with_interface(self):
        """Call :meth:`nailgun.entities.Host.read`.

        Assert that host will have interfaces initialized and assigned
        correctly.
        """
        with mock.patch.object(
            EntityReadMixin,
            'read',
            return_value=entities.Host(self.cfg, id=2),
        ):
            with mock.patch.object(
                EntityReadMixin,
                'read_json',
                return_value={
                    'interfaces': [{'id': 2}, {'id': 3}],
                    'parameters': None,
                },
            ):
                host = entities.Host(self.cfg, id=2).read()
        self.assertTrue(hasattr(host, 'interface'))
        self.assertTrue(isinstance(host.interface, list))
        for interface in host.interface:
            self.assertTrue(isinstance(interface, entities.Interface))
        self.assertEqual(
            {interface.id for interface in host.interface},
            {2, 3}
        )

    def test_discovery_rule(self):
        """Call :meth:`nailgun.entities.DiscoveryRule.read`.

        Ensure that the ``max_count`` attribute is fetched.

        """
        with mock.patch.object(EntityUpdateMixin, 'update_json') as u_json:
            u_json.return_value = {'max_count': 'max_count'}
            with mock.patch.object(EntityReadMixin, 'read_json') as read_json:
                read_json.return_value = {'id': 'id', 'search': 'search'}
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    entities.DiscoveryRule(self.cfg).read()
        for mock_obj in (u_json, read_json, read):
            self.assertEqual(mock_obj.call_count, 1)
        self.assertEqual(u_json.call_args, mock.call([]))

    def test_product_with_sync_plan(self):
        """Call :meth:`nailgun.entities.Product.read` for a product with sync
        plan assigned.

        Ensure that the sync plan entity was correctly fetched.

        """
        sync_plan = entities.SyncPlan(self.cfg, id=1, organization=1)
        product = entities.Product(self.cfg, id=1, organization=1)
        with mock.patch.object(EntityReadMixin, 'read_json') as read_json:
            with mock.patch.object(EntityReadMixin, 'read') as read:
                read_json.return_value = {
                    'sync_plan_id': 1,
                    'sync_plan': {'name': 'test_sync_plan'},
                }
                read.return_value = product
                product = product.read()
                self.assertTrue(hasattr(product, 'sync_plan'))
                # pylint:disable=no-member
                self.assertEqual(product.sync_plan.id, sync_plan.id)

    def test_hostgroup_ignore_root_pass(self):
        """Call :meth:`nailgun.entities.HostGroup.read`.

        Assert that the entity ignores the ``root_pass`` field.

        """
        with mock.patch.object(EntityReadMixin, 'read') as read:
            with mock.patch.object(EntityReadMixin, 'read_json'):
                entities.HostGroup(self.cfg).read()
        # `call_args` is a two-tuple of (positional, keyword) args.
        self.assertIn('root_pass', read.call_args[0][2])

    def test_usergroup_with_external_usergroup(self):
        """Call :meth:`nailgun.entities.ExternalUserGroup.read` for a usergroup with external
        usergroup assigned.

        Ensure that the external usergroup entity was correctly fetched.

        """
        with mock.patch.object(EntityReadMixin, 'read') as read:
            with mock.patch.object(EntityReadMixin, 'read_json'):
                ext_usergrp = entities.ExternalUserGroup(self.cfg, usergroup=1).read()
        usergrp = ext_usergrp.read()
        self.assertTrue(hasattr(usergrp, 'usergroup'))
        self.assertIn('usergroup', read.call_args[0][2])

    def test_subnet(self):
        """Call :meth:`nailgun.entities.Subnet.read`.

        Ensure that the ``from_`` attribute is successfully set.

        """
        with mock.patch.object(EntityReadMixin, 'read_json') as read_json:
            read_json.return_value = {'from': 'foo'}
            with mock.patch.object(EntityReadMixin, 'read') as read:
                entities.Subnet(self.cfg).read()
        for mock_obj in (read_json, read):
            self.assertEqual(mock_obj.call_count, 1)
        self.assertIn('from_', read.call_args[0][1])


class SearchTestCase(TestCase):
    """Tests for
    :meth:`nailgun.entity_mixins.EntitySearchMixin.search`.
    """

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')

    def test_product_with_sync_plan(self):
        """Call :meth:`nailgun.entities.Product.search` for a product with sync
        plan assigned.

        Ensure that the sync plan entity was correctly fetched.

        """
        with mock.patch.object(EntitySearchMixin, 'search_json') as search_json:
            # Synplan set
            search_json.return_value = {
                'results': [
                    {'id': 2,
                     'name': 'test_product',
                     'organization': {
                         'id': 1,
                         'label': 'Default_Organization',
                         'name': 'Default Organization'},
                     'organization_id': 1,
                     'sync_plan': {
                         'id': 1,
                         'interval': 'hourly',
                         'name': 'sync1'},
                     'sync_plan_id': 1}]
            }
            result = entities.Product(self.cfg, organization=1).search()
            self.assertIsNotNone(result[0].sync_plan)
            self.assertEqual(result[0].sync_plan.id, 1)
            # Synplan not set
            search_json.return_value = {
                'results': [
                    {'id': 3,
                     'name': 'test_product2',
                     'organization': {
                         'id': 1,
                         'label': 'Default_Organization',
                         'name': 'Default Organization'},
                     'organization_id': 1,
                     'sync_plan': None,
                     'sync_plan_id': None}]
            }
            result = entities.Product(self.cfg, organization=1).search()
            self.assertIsNone(result[0].sync_plan)

    def test_host_with_image(self):
        """Call :meth:`nailgun.entities.Host.search` for a host with image
        assigned.

        Ensure that the image entity was correctly fetched.

        """
        with mock.patch.object(EntitySearchMixin, 'search_json') as search_json:
            # Image is set
            search_json.return_value = {
                'results': [
                    {'id': 2,
                     'name': 'host1',
                     'organization': {
                         'id': 1,
                         'name': 'Default Organization'},
                     'organization_id': 1,
                     'image_name': 'rhel7_image',
                     'image_file': '/usr/share/imagefile/xyz7.img',
                     'image_id': 1}]
            }
            result = entities.Host(self.cfg, organization=1).search()
            self.assertIsNotNone(result[0].image)
            self.assertEqual(result[0].image.id, 1)
            # image not set
            search_json.return_value = {
                'results': [
                    {'id': 3,
                     'name': 'host2',
                     'organization': {
                         'id': 1,
                         'name': 'Default Organization'},
                     'organization_id': 1,
                     'image_name': None,
                     'image_file': '',
                     'image_id': None}]
            }
            result = entities.Host(self.cfg, organization=1).search()
            self.assertIsNone(result[0].image)


class SearchNormalizeTestCase(TestCase):
    """Tests for
    :meth:`nailgun.entity_mixins.EntitySearchMixin.search_normalize`.
    """

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')

    def test_snapshot(self):
        """Test :meth:`nailgun.entities.Snapshot.search_normalize`.

        Assert that ``host_id`` was added with correct user's id to search
        results.
        """
        results = [
            {'id': 1, 'name': 'foo'},
            {'id': 2, 'name': 'bar', 'description': 'This is bar'},
        ]
        with mock.patch.object(
            EntitySearchMixin,
            'search_normalize',
        ) as search_normalize:
            entities.Snapshot(self.cfg, host=4).search_normalize(results)
            for args in search_normalize.call_args[0][0]:
                self.assertIn('host_id', args)
                self.assertEqual(args['host_id'], 4)

    def test_sshkey(self):
        """Test :meth:`nailgun.entities.SSHKey.search_normalize`.

        Assert that ``user_id`` was added with correct user's id to search
        results.
        """
        results = [
            {'id': 1, 'login': 'foo'},
            {'id': 2, 'login': 'bar'},
        ]
        with mock.patch.object(
            EntitySearchMixin,
            'search_normalize',
        ) as search_normalize:
            entities.SSHKey(self.cfg, user=4).search_normalize(results)
            for args in search_normalize.call_args[0][0]:
                self.assertIn('user_id', args)
                self.assertEqual(args['user_id'], 4)

    def test_interface(self):
        """Test :meth:`nailgun.entities.Interface.search_normalize`.

        Assert that ``host_id`` was added with correct host's id to search
        results.
        """
        results = [
            {'id': 1, 'name': 'foo'},
            {'id': 2, 'name': 'bar'},
        ]
        with mock.patch.object(
            EntitySearchMixin,
            'search_normalize',
        ) as search_normalize:
            entities.Interface(self.cfg, host=3).search_normalize(results)
            for args in search_normalize.call_args[0][0]:
                self.assertIn('host_id', args)
                self.assertEqual(args['host_id'], 3)

    def test_host_with_image(self):
        """Call :meth:`nailgun.entities.Host.read` for a host with image
        assigned.

        Ensure that the image entity was correctly fetched.
        """
        image = entities.Image(self.cfg, id=1, compute_resource=1)
        host = entities.Host(self.cfg, id=1)
        with mock.patch.object(EntityReadMixin, 'read_json') as read_json:
            with mock.patch.object(EntityReadMixin, 'read') as read:
                # Image was set
                read_json.return_value = {
                    'image_id': 1,
                    'compute_resource_id': 1,
                    'parameters': {},
                }
                read.return_value = host
                host = host.read()
                self.assertTrue(hasattr(host, 'image'))
                # pylint:disable=no-member
                self.assertEqual(host.image.id, image.id)
                # Image wasn't set
                read_json.return_value = {
                    'parameters': {},
                }
                read.return_value = host
                host = host.read()
                self.assertTrue(hasattr(host, 'image'))
                # pylint:disable=no-member
                self.assertIsNone(host.image)


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
            entities.ContentCredential(self.cfg),
            entities.ComputeProfile(self.cfg),
            entities.ConfigGroup(self.cfg),
            entities.DiscoveryRule(self.cfg),
            entities.Domain(self.cfg),
            entities.Environment(self.cfg),
            entities.GPGKey(self.cfg),
            entities.Host(self.cfg),
            entities.HostCollection(self.cfg),
            entities.HostGroup(self.cfg),
            entities.LifecycleEnvironment(self.cfg),
            entities.Location(self.cfg),
            entities.Media(self.cfg),
            entities.Organization(self.cfg),
            entities.SmartProxy(self.cfg),
            entities.Registry(self.cfg),
            entities.User(self.cfg),
            entities.UserGroup(self.cfg),
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


class SearchPayloadTestCase(TestCase):
    """Tests for extensions of ``search_upload``. """

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')

    def test_generic(self):
        """Instantiate a variety of entities and call ``search_payload``."""
        entities_ = ([
            (entities.ContentViewFilterRule, {'content_view_filter': 1})
        ])

        for entity, params in entities_:
            with self.subTest():
                self.assertIsInstance(
                    entity(self.cfg, **params).search_payload(),
                    dict
                )

    def test_content_view_filter_rule(self):
        """errata_id field should be Errata ID when sent to the server,
           not DB ID.
        """
        errata_kwargs = {
            "id": 1,
            "uuid": "1a321570-cd30-4622-abff-2290b47ef814",
            "title": "Bird_Erratum",
            "errata_id": "RHEA-2012:0003",
            "issued": "2012-01-27",
            "updated": "2012-01-27",
            "severity": "",
            "description": "Bird_Erratum",
            "solution": "",
            "summary": "",
            "reboot_suggested": False,
            "name": "Bird_Erratum",
            "type": "security",
            "cves": [],
            "hosts_available_count": 0,
            "hosts_applicable_count": 0,
            "packages": ["stork-0.12-2.noarch"],
            "module_streams": [
                {
                    "name": "duck",
                    "stream": "0",
                    "version": "201809302113907",
                    "context": "deadbeef",
                    "arch": "noarch",
                    "id": 1,
                    "packages": [
                        "duck-0.8-1.noarch"
                    ]
                }
            ]

        }

        with mock.patch.object(entities.Errata, 'read_json') as read_json:
            read_json.return_value = errata_kwargs
            payload = entities.ContentViewFilterRule(
                self.cfg,
                content_view_filter=1,
                errata=1,
            ).search_payload()
            self.assertEqual("RHEA-2012:0003", payload['errata_id'])


class UpdatePayloadTestCase(TestCase):
    """Tests for extensions of ``update_payload``."""

    @classmethod
    def setUpClass(cls):
        """Set a server configuration at ``cls.cfg``."""
        cls.cfg = config.ServerConfig('http://example.com')
        cls.cfg_610 = config.ServerConfig(
            'http://example.com', version='6.1.0')

    def test_generic(self):
        """Instantiate a variety of entities and call ``update_payload``."""
        entities_payloads = [
            (entities.AbstractComputeResource, {'compute_resource': {}}),
            (entities.ConfigTemplate, {'config_template': {}}),
            (entities.Filter, {'filter': {}}),
            (entities.ProvisioningTemplate, {'provisioning_template': {}}),
            (entities.ReportTemplate, {'report_template': {}}),
            (entities.DiscoveredHost, {'discovered_host': {}}),
            (entities.DiscoveryRule, {'discovery_rule': {}}),
            (entities.Domain, {'domain': {}}),
            (entities.Environment, {'environment': {}}),
            (entities.Host, {'host': {}}),
            (entities.HostGroup, {'hostgroup': {}}),
            (entities.Location, {'location': {}}),
            (entities.Media, {'medium': {}}),
            (entities.OperatingSystem, {'operatingsystem': {}}),
            (entities.Organization, {'organization': {}}),
            (entities.Role, {'role': {}}),
            (entities.Setting, {'setting': {}}),
            (entities.SmartProxy, {'smart_proxy': {}}),
            (entities.SmartVariable, {'smart_variable': {}}),
            (entities.Subnet, {'subnet': {}}),
            (entities.Registry, {'registry': {}}),
            (entities.User, {'user': {}}),
            (entities.UserGroup, {'usergroup': {}}),
            (entities.VirtWhoConfig, {'foreman_virt_who_configure_config': {}}),
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

    def test_content_view_filter_rule(self):
        """errata_id field should be 'translated' from DB ID to Errata ID."""
        errata_kwargs = {
            "id": 1,
            "uuid": "1a321570-cd30-4622-abff-2290b47ef814",
            "title": "Bird_Erratum",
            "errata_id": "RHEA-2012:0003",
            "issued": "2012-01-27",
            "updated": "2012-01-27",
            "severity": "",
            "description": "Bird_Erratum",
            "solution": "",
            "summary": "",
            "reboot_suggested": False,
            "name": "Bird_Erratum",
            "type": "security",
            "cves": [],
            "hosts_available_count": 0,
            "hosts_applicable_count": 0,
            "packages": ["stork-0.12-2.noarch"],
            "module_streams": [
                {
                    "name": "duck",
                    "stream": "0",
                    "version": "201809302113907",
                    "context": "deadbeef",
                    "arch": "noarch",
                    "id": 1,
                    "packages": [
                        "duck-0.8-1.noarch"
                    ]
                }
            ]

        }

        with mock.patch.object(entities.Errata, 'read_json') as read_json:
            read_json.return_value = errata_kwargs
            payload = entities.ContentViewFilterRule(
                self.cfg,
                content_view_filter=1,
                errata=1,
            ).update_payload()
            self.assertEqual("RHEA-2012:0003", payload['errata_id'])

    def test_discovery_rule_search(self):
        """Check whether ``DiscoveryRule`` updates its ``search_`` field.

        The field should be renamed from ``search_`` to ``search`` when
        ``update_payload`` is called.

        """
        payload = entities.DiscoveryRule(
            self.cfg,
            search_='foo',
        ).update_payload()
        self.assertNotIn('search_', payload['discovery_rule'])
        self.assertIn('search', payload['discovery_rule'])

    def test_image(self):
        """Check whether ``Image`` updates its ``path_`` field.

        The field should be renamed from ``path_`` to ``path`` when
        ``update_payload`` is called.

        """
        payload = entities.Image(
            self.cfg,
            compute_resource=1,
        ).update_payload()
        self.assertEqual({'image': {'compute_resource_id': 1}}, payload)

    def test_media_path(self):
        """Check whether ``Media`` updates its ``path_`` field.

        The field should be renamed from ``path_`` to ``path`` when
        ``update_payload`` is called.

        """
        payload = entities.Media(self.cfg, path_='foo').update_payload()
        self.assertNotIn('path_', payload['medium'])
        self.assertIn('path', payload['medium'])

    def test_hostcollection_system_uuid(self):
        """Check whether ``HostCollection`` updates its ``system_ids`` field.

        The field should be renamed from ``system_ids`` to ``system_uuids``
        when ``update_payload`` is called.
        """
        payload = entities.HostCollection(
            self.cfg_610,
            system=[1],
        ).update_payload()
        self.assertNotIn('system_ids', payload)
        self.assertIn('system_uuids', payload)

    def test_job_template(self):
        """Create a :class:`nailgun.entities.JobTemplate`."""
        payload = entities.JobTemplate(
            self.cfg,
            effective_user={'value': 'foo'},
            name='brick system',
            template='rm -rf --no-preserve-root /',
        ).update_payload()
        self.assertNotIn('effective_user', payload)
        self.assertIn('effective_user', payload['job_template']['ssh'])

    def test_organization_rh_repo_url(self):
        """Check whether ``Organization`` updates its ``redhat_repository_url`` field.

        The field should be copied from
        ``p['organization']['redhat_repository_url']`` to
        ``p['redhat_repository_url']``
        when ``update_payload`` is called.
        """
        payload = entities.Organization(
            self.cfg,
            redhat_repository_url=["https://cdn.redhat.com"],
        ).update_payload()
        self.assertIn('redhat_repository_url', payload)

    def test_os_default_template(self):
        """Check, that ``os_default_template`` serves ``template_kind_id`` and
        ``provisioning_template_id`` only wrapped in sub dict
        See: `Redmine #21169`_.

        .. _Redmine #21169: http://projects.theforeman.org/issues/21169
        """
        payload = entities.OSDefaultTemplate(
            self.cfg,
            operatingsystem=entities.OperatingSystem(self.cfg, id=1),
            template_kind=entities.TemplateKind(self.cfg, id=2),
            provisioning_template=entities.ProvisioningTemplate(self.cfg,
                                                                id=3),
        ).update_payload()
        self.assertNotIn('template_kind_id', payload)
        self.assertNotIn('provisioning_template_id', payload)
        self.assertIn('template_kind_id', payload['os_default_template'])
        self.assertIn('provisioning_template_id',
                      payload['os_default_template'])

    def test_subnet_from(self):
        """Check whether ``Subnet`` updates its ``from_`` field.

        The field should be renamed from ``from_`` to ``from`` when
        ``update_payload`` is called.

        """
        payload = entities.Subnet(
            self.cfg,
            from_='foo',
        ).update_payload()
        self.assertNotIn('from_', payload['subnet'])
        self.assertIn('from', payload['subnet'])

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
        external_usergroup = {'server_config': cfg, 'id': 1, 'usergroup': 2}
        sync_plan = {'server_config': cfg, 'id': 1, 'organization': 2}
        hostsubscription = {'server_config': cfg, 'host': 1}
        cls.methods_requests = (
            (entities.AbstractDockerContainer(**generic).logs, 'get'),
            (entities.AbstractDockerContainer(**generic).power, 'put'),
            (entities.ActivationKey(**generic).add_host_collection, 'post'),
            (entities.ActivationKey(**generic).add_subscriptions, 'put'),
            (entities.ActivationKey(**generic).remove_subscriptions, 'put'),
            (entities.ActivationKey(**generic).subscriptions, 'get'),
            (entities.ActivationKey(**generic).content_override, 'put'),
            (entities.ActivationKey(**generic).product_content, 'get'),
            (entities.ActivationKey(**generic).remove_host_collection, 'put'),
            (
                entities.Capsule(**generic).content_add_lifecycle_environment,
                'post'
            ),
            (entities.ArfReport(**generic).download_html, 'get'),
            (entities.Capsule(**generic).content_get_sync, 'get'),
            (
                entities.Capsule(**generic).content_lifecycle_environments,
                'get'
            ),
            (entities.Capsule(**generic).content_sync, 'post'),
            (entities.ConfigTemplate(**generic).build_pxe_default, 'post'),
            (entities.ConfigTemplate(**generic).clone, 'post'),
            (entities.Role(**generic).clone, 'post'),
            (
                entities.ProvisioningTemplate(**generic).build_pxe_default,
                'post'
            ),
            (entities.ProvisioningTemplate(**generic).clone, 'post'),
            (entities.ReportTemplate(**generic).clone, 'post'),
            (entities.ContentView(**generic).available_puppet_modules, 'get'),
            (entities.ContentView(**generic).copy, 'post'),
            (entities.ContentView(**generic).publish, 'post'),
            (
                entities.ContentViewVersion(**generic).incremental_update,
                'post'
            ),
            (entities.ContentViewVersion(**generic).promote, 'post'),
            (entities.DiscoveredHost(cfg).facts, 'post'),
            (entities.Environment(**generic).list_scparams, 'get'),
            (entities.Errata(**generic).compare, 'get'),
            (entities.ExternalUserGroup(**external_usergroup).refresh, 'put'),
            (entities.ForemanTask(cfg).summary, 'get'),
            (
                entities.Organization(**generic).download_debug_certificate,
                'get'
            ),
            (entities.Host(**generic).add_puppetclass, 'post'),
            (entities.Host(**generic).enc, 'get'),
            (entities.Host(**generic).errata, 'get'),
            (entities.Host(**generic).errata_apply, 'put'),
            (entities.Host(**generic).get_facts, 'get'),
            (entities.Host(**generic).install_content, 'put'),
            (entities.Host(**generic).list_scparams, 'get'),
            (entities.Host(**generic).list_smart_variables, 'get'),
            (entities.Host(**generic).module_streams, 'get'),
            (entities.Host(**generic).packages, 'get'),
            (entities.Host(**generic).power, 'put'),
            (entities.Host(**generic).upload_facts, 'post'),
            (entities.HostGroup(**generic).add_puppetclass, 'post'),
            (entities.HostGroup(**generic).clone, 'post'),
            (entities.HostGroup(**generic).list_scparams, 'get'),
            (entities.HostGroup(**generic).list_smart_variables, 'get'),
            (entities.HostSubscription(**hostsubscription).add_subscriptions, 'put'),
            (entities.HostSubscription(**hostsubscription).remove_subscriptions, 'put'),
            (entities.Product(**generic).sync, 'post'),
            (entities.PuppetClass(**generic).list_scparams, 'get'),
            (entities.PuppetClass(**generic).list_smart_variables, 'get'),
            (entities.RHCIDeployment(**generic).deploy, 'put'),
            (entities.RecurringLogic(**generic).cancel, 'post'),
            (entities.Repository(**generic).errata, 'get'),
            (entities.Repository(**generic).packages, 'get'),
            (entities.Repository(**generic).module_streams, 'get'),
            (entities.Repository(**generic).puppet_modules, 'get'),
            (entities.Repository(**generic).remove_content, 'put'),
            (entities.Repository(**generic).sync, 'post'),
            (entities.SmartProxy(**generic).import_puppetclasses, 'post'),
            (entities.SmartProxy(**generic).refresh, 'put'),
            (entities.SyncPlan(**sync_plan).add_products, 'put'),
            (entities.SyncPlan(**sync_plan).remove_products, 'put'),
            (entities.Template(**generic).imports, 'post'),
            (entities.Template(**generic).exports, 'post'),
            (entities.VirtWhoConfig(**generic).deploy_script, 'get')
        )
        repo_set = {'server_config': cfg, 'id': 1, 'product': 2}
        snapshot = {'server_config': cfg, 'id': 'snapshot-1', 'host': 1}
        cls.intelligent_methods_requests = (
            (entities.RepositorySet(**repo_set).available_repositories, 'get', {'product_id': 2}),
            (entities.RepositorySet(**repo_set).disable, 'put', {'product_id': 2}),
            (entities.RepositorySet(**repo_set).enable, 'put', {'product_id': 2}),
            (entities.Snapshot(**snapshot).revert, 'put', {}),
        )

    def test_generic(self):
        """Check that a variety of helper methods are sane.

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

    def test_intelligent(self):
        """Check that intelligent methods that send additional data are sane.

        Assert that:

        * Each method calls `client.*` once.
        * Each method passes the right arguments to `client.*`.
        * Each method calls `entities._handle_response` once.
        * The result of `_handle_response(…)` is the return value.

        """
        for method, request, data in self.intelligent_methods_requests:
            with self.subTest((method, request)):
                kwargs = {'kwarg': gen_integer(), 'data': data}
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

        Assert that ``nailgun.entities.DockerHubContainer.get_fields`` and
        ``nailgun.entities.DockerRegistryContainer.get_fields`` return
        a dictionary of attributes that match what is returned by
        ``nailgun.entities.AbstractDockerContainer.get_fields`` but also
        returns extra attributes unique to them.

        """
        abstract_docker = entities.AbstractDockerContainer(
            self.cfg
        ).get_fields()
        docker_hub = entities.DockerHubContainer(self.cfg).get_fields()
        docker_registry = entities.DockerRegistryContainer(
            self.cfg).get_fields()
        # Attributes should not match
        self.assertNotEqual(abstract_docker, docker_hub)
        self.assertNotEqual(abstract_docker, docker_registry)
        # All attributes from a `entities.AbstractDockerContainer`
        # should be found in `entities.DockerHubContainer` and
        # `entities.DockerRegistyContainer`.
        for key in abstract_docker:
            self.assertIn(key, docker_hub)
            self.assertIn(key, docker_registry)
        # These fields should be present in a `entities.DockerHubContainer`
        # class but not in a `entities.AbstractDockerContainer` class.
        for attr in ['repository_name', 'tag']:
            self.assertIn(attr, docker_hub)
            self.assertNotIn(attr, abstract_docker)
        # These fields should be present in a
        # `entities.DockerRegistryContainer` class but not in a
        # `entities.AbstractDockerContainer` class.
        for attr in ['registry', 'repository_name', 'tag']:
            self.assertIn(attr, docker_registry)
            self.assertNotIn(attr, abstract_docker)


class ForemanStatusTestCase(TestCase):
    """Tests for :class:`nailgun.entities.ForemanStatus`."""

    def setUp(self):
        """Set a server configuration at ``self.cfg``."""
        self.cfg = config.ServerConfig('http://example.com')
        self.entity = entities.ForemanStatus(self.cfg)
        self.read_json_pacther = mock.patch.object(self.entity, 'read_json')

    def test_read(self):
        """Ensure ``read`` and ``read_json`` are called once."""
        read_json = self.read_json_pacther.start()
        read_json.return_value = {
            'result': 'ok',
            'status': 200,
            'version': '1.19.0',
            'api_version': 2,
        }
        self.entity.read()
        self.assertEqual(read_json.call_count, 1)
        self.read_json_pacther.stop()


class FileTestCase(TestCase):
    """Class with entity File tests"""
    def test_to_json(self):
        """Check json serialisation on nested entities"""
        file_kwargs = {
            'id': 1,
            'name': u'test_file.txt',
            'path': u'test_file.txt',
            'uuid': u'3a013738-e5b8-43b2-81f5-3732b6e42776',
            'checksum': (
                u'16c946e116072838b213f622298b74baa75c52c8fee50a6230b4680e3c1'
                u'36fb1'
            ),
        }
        cfg = config.ServerConfig(
            url='https://foo.bar', verify=False,
            auth=('foo', 'bar'))
        repo_kwargs = {'id': 3, 'content_type': 'file'}
        repo = entities.Repository(cfg, **repo_kwargs)
        file = entities.File(cfg, repository=repo, **file_kwargs)
        file_kwargs['repository'] = repo_kwargs
        self.assertDictEqual(file_kwargs, json.loads(file.to_json()))


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


class ConfigTemplateTestCase(TestCase):
    """Tests for :class:`nailgun.entities.ConfigTemplate`."""

    def test_creation_and_update(self):
        """Check template combinations as json or entity is set on correct
        attribute template_combinations_attributes ( check #333)
        """
        cfg = config.ServerConfig(url='foo')
        env = entities.Environment(cfg, id=2, name='env')
        hostgroup = entities.HostGroup(cfg, id=2, name='hgroup')
        combination = entities.TemplateCombination(
            cfg,
            hostgroup=hostgroup,
            environment=env)
        template_combinations = [
            {'hostgroup_id': 1, 'environment_id': 1},
            combination]
        cfg_template = entities.ConfigTemplate(
            cfg, name='cfg',
            snippet=False,
            template='cat',
            template_kind=8,
            template_combinations=template_combinations)
        expected_dct = {
            u'config_template': {
                'name': 'cfg', 'snippet': False, 'template': 'cat',
                'template_kind_id': 8, 'template_combinations_attributes': [
                    {'environment_id': 1, 'hostgroup_id': 1},
                    {'environment_id': 2, 'hostgroup_id': 2}]
            }
        }
        self.assertEqual(expected_dct, cfg_template.create_payload())
        # Testing update
        env3 = entities.Environment(cfg, id=3, name='env3')
        combination3 = entities.TemplateCombination(
            cfg,
            hostgroup=hostgroup,
            environment=env3)
        # pylint: disable=no-member
        cfg_template.template_combinations.append(combination3)
        attrs = expected_dct[u'config_template']
        attrs['template_combinations_attributes'].append(
            {'environment_id': 3, 'hostgroup_id': 2}
        )
        self.assertEqual(expected_dct, cfg_template.update_payload())


class ContentUploadTestCase(TestCase):
    """Tests for :class:`nailgun.entities.ContentUpload`."""

    def setUp(self):
        """Set ``self.repo``."""
        server_config = config.ServerConfig('http://example.com')
        repo = entities.Repository(
            server_config,
            id=gen_integer(min_value=1),
        )
        self.content_upload = entities.ContentUpload(
            server_config, repository=repo)

    def test_content_upload_create(self):
        """Test ``nailgun.entities.ContentUpload.create``.

        Make the (mock) server return a "success" status. Make the same
        assertions as for
        :meth:`tests.test_entities.GenericTestCase.test_generic`.

        """
        with mock.patch.object(client, 'post') as post:
            self.content_upload.create()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(post.call_args[0]), 2)

    def test_content_upload_delete(self):
        """Test ``nailgun.entities.ContentUpload.delete``.

        Make the (mock) server return a "success" status. Make the same
        assertions as for
        :meth:`tests.test_entities.GenericTestCase.test_generic`.

        """
        with mock.patch.object(client, 'delete') as delete:
            with mock.patch.object(client, 'post') as post:
                content_upload = self.content_upload.create()
                content_upload.delete()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(post.call_args[0]), 2)
        self.assertEqual(delete.call_count, 1)
        self.assertEqual(len(delete.call_args[0]), 1)

    def test_content_upload_update(self):
        """Test ``nailgun.entities.ContentUpload.update``.

        Make the (mock) server return a "success" status. Make the same
        assertions as for
        :meth:`tests.test_entities.GenericTestCase.test_generic`.

        """
        with mock.patch.object(client, 'post') as post:
            with mock.patch.object(client, 'put') as put:
                content_upload = self.content_upload.create()
                content_upload.update({'content': gen_string('alpha')})
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(post.call_args[0]), 2)
        self.assertEqual(put.call_count, 1)
        self.assertEqual(len(put.call_args[0]), 2)
        expected_args = {'headers': {'content-type': 'multipart/form-data'}}
        self.assertEqual(put.call_args[1], expected_args)

    def test_content_upload_upload(self):
        """Test ``nailgun.entities.ContentUpload.upload``.

        Make the (mock) server return a "success" status. Make the same
        assertions as for
        :meth:`tests.test_entities.GenericTestCase.test_generic`.

        """
        filename = gen_string('alpha')
        filepath = os.path.join(gen_string('alpha'), filename)
        with mock.patch.object(
            entities.ContentUpload, 'create',
        ) as create:
            with mock.patch.object(
                entities.Repository, 'import_uploads',
                return_value={'status': 'success'},
            ) as import_uploads:
                mock_open = mock.mock_open(
                    read_data=gen_string('alpha').encode('ascii'))
                with mock.patch(
                    _BUILTIN_OPEN, mock_open, create=True
                ):
                    response = self.content_upload.upload(
                        filepath, filename)
        self.assertEqual(import_uploads.call_count, 1)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(import_uploads.return_value, response)

    def test_content_upload_no_filename(self):
        """Test ``nailgun.entities.ContentUpload.upload`` without a filename.

        Make the (mock) server return a "success" status. Make the same
        assertions as for
        :meth:`tests.test_entities.GenericTestCase.test_generic`.

        """
        filename = gen_string('alpha')
        filepath = os.path.join(gen_string('alpha'), filename)
        with mock.patch.object(
            entities.ContentUpload, 'create',
        ) as create:
            with mock.patch.object(
                entities.Repository, 'import_uploads',
                return_value={'status': 'success'},
            ) as import_uploads:
                mock_open = mock.mock_open(
                    read_data=gen_string('alpha').encode('ascii'))
                with mock.patch(
                    _BUILTIN_OPEN, mock_open, create=True
                ):
                    response = self.content_upload.upload(
                        filepath)
        self.assertEqual(import_uploads.call_count, 1)
        self.assertEqual(create.call_count, 1)
        self.assertEqual(import_uploads.return_value, response)


class ContentViewTestCase(TestCase):
    """Tests for :class:`nailgun.entities.ContentView`."""
    def setUp(self):
        self.server_config = config.ServerConfig('http://example.com')
        self.cv = entities.ContentView(
            self.server_config,
            id=gen_integer(min_value=1),
        )
        self.single_entity = {
            "auto_publish": True,
            "composite": True,
            "components": [],
            "content_host_count": 0,
            "content_view_components": [{
                "composite_content_view": {
                    "id": 11,
                    "label": "My_CVC",
                    "name": "My CVC",
                },
                "content_view": {
                    "id": 10,
                    "label": "My_CV",
                    "name": "My CV",
                },
                "content_view_version": {
                    "content_view": {
                        "id": 10,
                        "label": "My_CV",
                        "name": "My CV"
                    },
                    "content_view_id": 10,
                    "environments": [
                        {
                            "id": 1,
                        }
                    ],
                    "id": 21,
                    "name": "My_CV 2.0",
                    "version": "6.0"
                },
                "id": 4,
                "latest": True,

            }],
            "description": None,
            "environments": [{
                "id": 1,
                "name": "Library",
                "label": "Library",
            }],
            "id": 5,
            "label": "my_CV",
            "last_published": '2018-11-23 11:51:30 UTC',
            "name": "my CV",
            "next_version": "3.0",
            "organization_id": 1,
            "puppet_modules": [{
                "name": "katello-katello",
                "id": 1,
            }],
            "repositories": [{
                "name": "my_tst_repo",
                "id": 3,
            }],
            "versions": [{
                "id": 4,
                "version": "2.0",
                "environment_ids": [1],
            }],
        }

    def test_read(self):
        """Check that helper method is sane.
        """
        with mock.patch.object(self.cv, 'read_json', return_value=self.single_entity) as handlr:
            response = self.cv.read()
        self.assertEqual(handlr.call_count, 1)
        self.assertEqual(type(response), entities.ContentView)
        self.assertEqual(type(response.content_view_component[0]),
                         entities.ContentViewComponent)

    def test_search(self):
        """Check that helper method is sane.

        """
        return_dict = {
            'results': [self.single_entity],
        }
        with mock.patch.object(self.cv, 'search_json', return_value=return_dict) as handlr:
            response = self.cv.search()
        self.assertEqual(handlr.call_count, 1)
        self.assertEqual(type(response[0]), entities.ContentView)
        self.assertEqual(type(response[0].content_view_component[0]),
                         entities.ContentViewComponent)


class ContentViewComponentTestCase(TestCase):
    """Tests for :class:`nailgun.entities.ContentViewComponent`."""

    def setUp(self):
        """Set a server configuration at ``self.cfg``."""

        self.server_config = config.ServerConfig('http://example.com')
        self.ccv = entities.ContentView(
            self.server_config,
            composite=True,
            id=gen_integer(min_value=1),
        )
        self.cv = entities.ContentView(
            self.server_config,
            id=gen_integer(min_value=1),
        )
        self.cvc = entities.ContentViewComponent(
            self.server_config,
            composite_content_view=self.ccv,
            content_view=self.cv,
            latest=True,
            id=gen_integer(min_value=1),
        )
        self.common_return_value = {
            'composite_content_view': {
                'label': 'mv_ccv',
                'id': 11,
            },
            'content_view': {
                'label': 'test',
                'id': 10,
            },
            'content_view_version': {
                'content_view_id': 10,
                'content_view': {
                    'label': 'test',
                    'id': 10,
                },
                'repositories': [{
                    'label': 'my_repo',
                    'id': 19,
                }],
                'environments': [{
                    'label': 'Library',
                    'id': 1,
                }],
                'id': 21,
            },
            'id': 2,
            'latest': True
        }

        self.read_json_pacther = mock.patch.object(self.cvc, 'read_json')

    def test_path(self):
        for which in ['add', 'remove']:
            path = self.cvc.path(which=which)
            self.assertIn('{}/content_view_components/{}'.format(
                self.cvc.composite_content_view.id,
                which), path)
            self.assertRegex(path, which + '$')

    def test_add(self):
        """Check that helper method is sane.

            Assert that:

            * Method has a correct signature.
            * Method calls `client.*` once.
            * Method calls `entities._handle_response` once.


        """
        self.assertEqual(
            inspect.getargspec(self.cvc.add),
            (['self', 'synchronous'], None, 'kwargs', (True,))
        )
        return_dict = {
            'results': [self.common_return_value]
        }
        with mock.patch.object(entities, '_handle_response', return_value=return_dict) as handlr:
            with mock.patch.object(client, 'put') as client_request:
                self.cvc.add()
        self.assertEqual(client_request.call_count, 1)
        self.assertEqual(len(client_request.call_args[0]), 1)
        self.assertEqual(handlr.call_count, 1)

    def test_remove(self):
        """Check that helper method is sane.

            Assert that:

            * Method has a correct signature.
            * Method calls `client.*` once.
            * Method calls `entities._handle_response` once.


        """
        self.assertEqual(
            inspect.getargspec(self.cvc.remove),
            (['self', 'synchronous'], None, 'kwargs', (True,))
        )
        return_dict = {
            'results': self.common_return_value
        }
        with mock.patch.object(entities, '_handle_response', return_value=return_dict) as handlr:
            with mock.patch.object(client, 'put') as client_request:
                self.cvc.remove()
        self.assertEqual(client_request.call_count, 1)
        self.assertEqual(len(client_request.call_args[0]), 1)
        self.assertEqual(handlr.call_count, 1)


class ReportTemplateTestCase(TestCase):
    """Tests for :class:`nailgun.entities.ReportTemplate`."""

    def test_creation_and_update(self):
        """Check template combinations as json or entity is set on correct
        attribute template_combinations_attributes ( check #333)
        """
        cfg = config.ServerConfig(url='foo')
        report_template = entities.ReportTemplate(
            cfg, name='cfg',
            default=False,
            template='cat')
        expected_dct = {
            u'report_template': {
                'name': 'cfg', 'default': False, 'template': 'cat',
            }
        }
        self.assertEqual(expected_dct, report_template.create_payload())
        # Testing update
        report_template.template = 'dog'
        expected_dct[u'report_template']['template'] = 'dog'
        self.assertEqual(expected_dct, report_template.update_payload())


class ProvisioningTemplateTestCase(TestCase):
    """Tests for :class:`nailgun.entities.ProvisioningTemplate`."""

    def test_creation_and_update(self):
        """Check template combinations as json or entity is set on correct
        attribute template_combinations_attributes ( check #333)
        """
        cfg = config.ServerConfig(url='foo')
        env = entities.Environment(cfg, id=2, name='env')
        hostgroup = entities.HostGroup(cfg, id=2, name='hgroup')
        combination = entities.TemplateCombination(
            cfg,
            hostgroup=hostgroup,
            environment=env)
        template_combinations = [
            {'hostgroup_id': 1, 'environment_id': 1},
            combination]
        cfg_template = entities.ProvisioningTemplate(
            cfg, name='cfg',
            snippet=False,
            template='cat',
            template_kind=8,
            template_combinations=template_combinations)
        expected_dct = {
            u'provisioning_template': {
                'name': 'cfg', 'snippet': False, 'template': 'cat',
                'template_kind_id': 8, 'template_combinations_attributes': [
                    {'environment_id': 1, 'hostgroup_id': 1},
                    {'environment_id': 2, 'hostgroup_id': 2}]
            }
        }
        self.assertEqual(expected_dct, cfg_template.create_payload())
        # Testing update
        env3 = entities.Environment(cfg, id=3, name='env3')
        combination3 = entities.TemplateCombination(
            cfg,
            hostgroup=hostgroup,
            environment=env3)
        # pylint: disable=no-member
        cfg_template.template_combinations.append(combination3)
        attrs = expected_dct[u'provisioning_template']
        attrs['template_combinations_attributes'].append(
            {'environment_id': 3, 'hostgroup_id': 2}
        )
        self.assertEqual(expected_dct, cfg_template.update_payload())


class TemplateInputTestCase(TestCase):
    """Tests for :class:`nailgun.entities.TemplateInput`."""
    def setUp(self):
        self.cfg = config.ServerConfig('some url')
        self.job_template = entities.JobTemplate(self.cfg, id=2)
        self.entity = entities.TemplateInput(
            self.cfg,
            id=1,
            template=self.job_template)
        self.data = dict(
            id=1,
            description=None,
            fact_name=None,
            input_type='user',
            name='my new template input',
            options=None,
            puppet_class_name=None,
            puppet_parameter_name=None,
            required=False,
            template_id=self.job_template.id,
            variable_name=None,
        )
        self.read_json_patcher = mock.patch.object(
            EntityReadMixin,
            'read_json')
        self.read_json = self.read_json_patcher.start()
        self.read_json.return_value = self.data.copy()
        del self.data['template_id']

    def tearDown(self):
        self.read_json_patcher.stop()

    def test_read(self):
        entity = self.entity.read()
        self.read_json.assert_called_once()
        self.assertEqual(
            self.data,
            {key: getattr(entity, key) for key in self.data.keys()}
        )
        self.assertIsInstance(entity.template, entities.JobTemplate)
        self.assertEqual(entity.template.id, self.job_template.id)


class JobTemplateTestCase(TestCase):
    """Tests for :class:`nailgun.entities.JobTemplate`."""
    def setUp(self):
        self.cfg = config.ServerConfig('some url')
        self.entity = entities.JobTemplate(self.cfg, id=1)
        self.read_json_patcher = mock.patch.object(
            EntityReadMixin,
            'read_json')
        self.read_json = self.read_json_patcher.start()
        self.template_input_data = dict(id=1, template=1)
        self.data = dict(
            id=1,
            audit_comment=None,
            description_format=None,
            effective_user=None,
            job_category='Commands',
            location=[],
            locked=False,
            name='my new job template',
            organization=[],
            provider_type=None,
            snippet=False,
            template='rm -rf /',
            template_inputs=[self.template_input_data],
        )
        self.read_json.return_value = self.data.copy()
        del self.data['template_inputs']

    def tearDown(self):
        self.read_json_patcher.stop()

    def test_read(self):
        entity = self.entity.read()
        self.read_json.assert_called_once()
        self.assertEqual(
            self.data,
            {key: getattr(entity, key) for key in self.data.keys()}
        )
        self.assertEqual(len(entity.template_inputs), 1)
        template_input = entity.template_inputs[0]
        self.assertIsInstance(template_input, entities.TemplateInput)
        self.assertIsInstance(
            template_input.template,
            entities.JobTemplate)
        self.assertEqual(
            template_input.id,
            self.template_input_data['id'])
        self.assertEqual(
            template_input.template.id,
            self.template_input_data['template'])


class HostGroupTestCase(TestCase):
    """Tests for :class:`nailgun.entities.HostGroup`."""
    def setUp(self):
        self.entity = entities.HostGroup(config.ServerConfig('some url'))
        self.read_json_pacther = mock.patch.object(self.entity, 'read_json')
        self.read_pacther = mock.patch.object(EntityReadMixin, 'read')
        self.update_json_patcher = mock.patch.object(
            entities.HostGroup, 'update_json')

    def test_read_sat61z(self):
        """Ensure ``read``, ``read_json`` and ``update_json`` are called once.

        This test is only appropriate for entities that override the ``read``
        method in order to fiddle with the ``attrs`` argument.
        """
        for version in ('6.1', '6.1.0', '6.1.8'):
            read_json = self.read_json_pacther.start()
            read = self.read_pacther.start()
            update_json = self.update_json_patcher.start()
            with self.subTest(version=version):
                # pylint:disable=protected-access
                self.entity._server_config.version = entities.Version(version)
                read_json.return_value = {
                    'ancestry': None,
                    'id': 641212,  # random
                }
                update_json.return_value = {
                    'content_source_id': None,
                    'content_view_id': None,
                    'lifecycle_environment_id': None,
                }
                self.entity.read()
                for meth in (read_json, update_json, read):
                    self.assertEqual(meth.call_count, 1)
                self.assertEqual(
                    read.call_args[0][1],
                    {
                        'content_source_id': None,
                        'content_view_id': None,
                        'id': 641212,
                        'lifecycle_environment_id': None,
                        'parent_id': None,
                    },
                )
            self.read_json_pacther.stop()
            self.read_pacther.stop()
            self.update_json_patcher.stop()

    def test_read_sat62z(self):
        """Ensure ``read`` and ``read_json`` are called once. And
        ``update_json`` are not called.

        This test is only appropriate for entities that override the ``read``
        method in order to fiddle with the ``attrs`` argument.
        """
        for version in ('6.2', '6.2.0', '6.2.8'):
            read_json = self.read_json_pacther.start()
            read = self.read_pacther.start()
            update_json = self.update_json_patcher.start()
            read_json.return_value = {
                'ancestry': None, 'id': 641212,  # random
                'content_source_id': None,
                'content_view_id': None,
                'lifecycle_environment_id': None,
            }
            with self.subTest(version=version):
                # pylint:disable=protected-access
                self.entity._server_config.version = entities.Version(version)
                self.entity.read()
                for meth in (read_json, read):
                    self.assertEqual(meth.call_count, 1)
                self.assertEqual(update_json.call_count, 0)
                self.assertEqual(
                    read.call_args[0][1],
                    {
                        'content_source_id': None,
                        'content_view_id': None,
                        'id': 641212,
                        'lifecycle_environment_id': None,
                        'parent_id': None,
                    },
                )
            self.read_json_pacther.stop()
            self.read_pacther.stop()
            self.update_json_patcher.stop()

    def test_delete_puppetclass(self):
        """Check that helper method is sane.

            Assert that:

            * Method has a correct signature.
            * Method calls `client.*` once.
            * Method passes the right arguments to `client.*` and special
                argument 'puppetclass_id' removed from data dict.
            * Method calls `entities._handle_response` once.
            * The result of `_handle_response(…)` is the return value.


        """
        entity = self.entity
        entity.id = 1
        self.assertEqual(
            inspect.getargspec(entity.delete_puppetclass),
            (['self', 'synchronous'], None, 'kwargs', (True,))
        )
        kwargs = {
            'kwarg': gen_integer(),
            'data': {'puppetclass_id': gen_integer()}
        }
        with mock.patch.object(entities, '_handle_response') as handlr:
            with mock.patch.object(client, 'delete') as client_request:
                response = entity.delete_puppetclass(**kwargs)
        self.assertEqual(client_request.call_count, 1)
        self.assertEqual(len(client_request.call_args[0]), 1)
        self.assertNotIn('puppetclass_id', client_request.call_args[1]['data'])
        self.assertEqual(client_request.call_args[1], kwargs)
        self.assertEqual(handlr.call_count, 1)
        self.assertEqual(handlr.return_value, response)

    def test_clone_hostgroup(self):
        """"Test for :meth:`nailgun.entities.HostGroup.clone`
        Assert that the method is called one with correct argumets
        """
        entity = self.entity
        entity.id = 1
        self.assertEqual(
            inspect.getargspec(entity.clone),
            (['self', 'synchronous'], None, 'kwargs', (True,))
        )
        kwargs = {
            'kwarg': gen_integer(),
            'data': {'name': gen_string('utf8', 5)}
        }
        with mock.patch.object(entities, '_handle_response') as handler:
            with mock.patch.object(client, 'post') as post:
                response = entity.clone(**kwargs)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(post.call_args[0]), 1)
        self.assertEqual(post.call_args[1], kwargs)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

    def test_rebuild_config(self):
        """"Test for :meth:`nailgun.entities.HostGroup.rebuild_config`
        Assert that the method is called one with correct arguments
        """
        entity = self.entity
        entity.id = 1
        self.assertEqual(
            inspect.getargspec(entity.rebuild_config),
            (['self', 'synchronous'], None, 'kwargs', (True,))
        )
        kwargs = {
            'kwarg': gen_integer(),
            'data': {'only': 'TFTP'}
        }
        with mock.patch.object(entities, '_handle_response') as handler:
            with mock.patch.object(client, 'put') as put:
                response = entity.rebuild_config(**kwargs)
        self.assertEqual(put.call_count, 1)
        self.assertEqual(len(put.call_args[0]), 1)
        self.assertEqual(put.call_args[1], kwargs)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)


class HostTestCase(TestCase):
    """Tests for :class:`nailgun.entities.Host`."""

    def setUp(self):
        """Set a server configuration at ``self.cfg``."""
        self.cfg = config.ServerConfig('http://example.com')

    def test_init_with_owner_type(self):
        """Assert ``owner`` attribute is an entity of correct type, according
        to ``owner_type`` field value"""
        for owner_type, entity in (
                ('User', entities.User),
                ('Usergroup', entities.UserGroup)):
            host = entities.Host(
                self.cfg,
                id=gen_integer(min_value=1),
                owner=gen_integer(min_value=1),
                owner_type=owner_type,
            )
            self.assertTrue(isinstance(host.owner, entity))

    def test_update_owner_type(self):
        """Ensure that in case ``owner_type`` value changes, ``owner`` changes
        it's type accordingly.
        """
        host = entities.Host(
            self.cfg,
            id=gen_integer(min_value=1),
            owner=gen_integer(min_value=1),
            owner_type='User',
        )
        host.owner_type = 'Usergroup'
        self.assertTrue(isinstance(host.owner, entities.UserGroup))
        host.owner_type = 'User'
        self.assertTrue(isinstance(host.owner, entities.User))

    def test_owner_type_property(self):
        """Verify ``owner_type`` property works as expected.

        Assert that:

        * ``owner_type`` property reflects ``_owner_type`` attribute value
        * ``owner_type`` property is included in attributes list,
          ``_owner_type`` attribute - is not
        """
        host = entities.Host(
            self.cfg,
            owner_type='User',
            id=gen_integer(min_value=1),
            owner=gen_integer(min_value=1),
        )
        # pylint:disable=protected-access
        self.assertEqual(host._owner_type, host.owner_type)
        result = host.get_values()
        self.assertTrue('owner_type' in result)
        self.assertFalse('_owner_type' in result)

    def test_init_with_owner(self):
        """Assert that both ``id`` or ``entity`` can be passed as a value for
        ``owner`` attribute.
        """
        owner_id = gen_integer(min_value=1)
        owner_entity = entities.UserGroup(
            self.cfg,
            id=owner_id,
        )
        for owner in (owner_id, owner_entity):
            host = entities.Host(
                self.cfg,
                owner=owner,
                owner_type='Usergroup',
                id=gen_integer(min_value=1),
            )
            self.assertTrue(isinstance(host.owner, entities.UserGroup))
            # pylint:disable=no-member
            self.assertEqual(owner_id, host.owner.id)

    def test_no_facet_attributes(self):
        """Assert that ``content_facet_attributes`` attribute is ignored when
        ``content_facet_attributes`` attribute is not returned for host
        """
        with mock.patch.object(EntityReadMixin, 'read') as read:
            entities.Host(self.cfg).read(attrs={
                'parameters': None,
                'puppetclasses': None,
            })
            self.assertNotIn('content_facet_attributes', read.call_args[0][1])
            self.assertIn('content_facet_attributes', read.call_args[0][2])

    def test_delete_puppetclass(self):
        """Check that helper method is sane.

            Assert that:

            * Method has a correct signature.
            * Method calls `client.*` once.
            * Method passes the right arguments to `client.*` and special
                argument 'puppetclass_id' removed from data dict.
            * Method calls `entities._handle_response` once.
            * The result of `_handle_response(…)` is the return value.

        """
        entity = entities.Host(self.cfg, id=1)
        self.assertEqual(
            inspect.getargspec(entity.delete_puppetclass),
            (['self', 'synchronous'], None, 'kwargs', (True,))
        )
        kwargs = {
            'kwarg': gen_integer(),
            'data': {'puppetclass_id': gen_integer()}
        }
        with mock.patch.object(entities, '_handle_response') as handlr:
            with mock.patch.object(client, 'delete') as client_request:
                response = entity.delete_puppetclass(**kwargs)
        self.assertEqual(client_request.call_count, 1)
        self.assertEqual(len(client_request.call_args[0]), 1)
        self.assertNotIn('puppetclass_id', client_request.call_args[1]['data'])
        self.assertEqual(client_request.call_args[1], kwargs)
        self.assertEqual(handlr.call_count, 1)
        self.assertEqual(handlr.return_value, response)


class PuppetClassTestCase(TestCase):
    """Tests for :class:`nailgun.entities.PuppetClass`."""

    def setUp(self):
        """Set ``self.puppet_class``."""
        self.puppet_class = entities.PuppetClass(
            config.ServerConfig('http://example.com'),
            id=gen_integer(min_value=1),
        )

    def test_search_normalize(self):
        """Call :meth:`nailgun.entities.PuppetClass.search_normalize`.
        Assert that returned value is a list and contains all subdictionaries.
        """
        with mock.patch.object(EntitySearchMixin, 'search_normalize') as s_n:
            self.puppet_class.search_normalize({
                'class1': [
                    {'name': 'subclass1'},
                    {'name': 'subclass2'}],
                'class2': [
                    {'name': 'subclass1'},
                    {'name': 'subclass2'}]
            })
        self.assertEqual(s_n.call_count, 1)
        self.assertIsInstance(s_n.call_args[0][0], list)
        self.assertEqual(len(s_n.call_args[0][0]), 4)


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

    def test_import_uploads_uploads(self):
        """Call :meth:`nailgun.entities.Repository.import_uploads` with
        the `uploads` parameter.

        Make the (mock) server return a "success" status. Make the same
        assertions as for
        :meth:`tests.test_entities.GenericTestCase.test_generic`.

        """
        kwargs = {'kwarg': gen_integer()}
        uploads = [{'id': gen_string('numeric'), 'name': gen_string('alpha'),
                    'size': gen_integer(), 'checksum': gen_string('numeric')}]
        with mock.patch.object(client, 'put') as put:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value={'status': 'success'},
            ) as handler:
                response = self.repo.import_uploads(uploads=uploads, **kwargs)
        self.assertEqual(put.call_count, 1)
        self.assertEqual(len(put.call_args[0]), 2)
        self.assertEqual(put.call_args[1], kwargs)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

    def test_import_uploads_upload_ids(self):
        """Call :meth:`nailgun.entities.Repository.import_uploads` with
        the `upload_ids` parameter.

        Make the (mock) server return a "success" status. Make the same
        assertions as for
        :meth:`tests.test_entities.GenericTestCase.test_generic`.

        """
        kwargs = {'kwarg': gen_integer()}
        upload_ids = [gen_string('numeric')]
        with mock.patch.object(client, 'put') as put:
            with mock.patch.object(
                entities,
                '_handle_response',
                return_value={'status': 'success'},
            ) as handler:
                response = self.repo.import_uploads(upload_ids=upload_ids,
                                                    **kwargs)
        self.assertEqual(put.call_count, 1)
        self.assertEqual(len(put.call_args[0]), 2)
        self.assertEqual(put.call_args[1], kwargs)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)

    def test_files(self):
        """"Test for :meth:`nailgun.entities.Repository.files`
        Assert that the method is called one with correct arguments
        """
        self.assertEqual(
            inspect.getargspec(self.repo.files),
            (['self', 'synchronous'], None, 'kwargs', (True,))
        )
        kwargs = {
            'kwarg': gen_integer(),
            'data': {'name': gen_string('utf8', 5)}
        }
        with mock.patch.object(entities, '_handle_response') as handler:
            with mock.patch.object(client, 'get') as get:
                response = self.repo.files(**kwargs)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(len(get.call_args[0]), 1)
        self.assertEqual(get.call_args[1], kwargs)
        self.assertEqual(handler.call_count, 1)
        self.assertEqual(handler.return_value, response)


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


class SmartProxyTestCase(TestCase):
    """Tests for :class:`nailgun.entities.SmartProxy`."""

    def setUp(self):
        """Set ``self.smart_proxy``."""
        self.cfg = config.ServerConfig('http://example.com')
        self.smart_proxy = entities.SmartProxy(self.cfg)
        self.env = entities.Environment(self.cfg, id='2')

    def test_import_puppetclasses(self):
        """Call :meth:`nailgun.entities.SmartProxy.import_puppetclasses`.
        Assert that
        * ``environment`` parameter is not sent to requests,
        * proper path is built
        """
        params = [
            {},
            {'environment': 2},
            {'environment': self.env}
        ]
        for param in params:
            with self.subTest(param):
                with mock.patch.object(client, 'post') as post:
                    self.smart_proxy.import_puppetclasses(**param)
                self.assertEqual(post.call_count, 1)
                self.assertNotIn('environment', post.call_args[1])
                self.assertIn('/import_puppetclasses', post.call_args[0][0])
                if 'environment' in param:
                    self.assertIn('/environments', post.call_args[0][0])


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

    def test_methods(self):
        """Check that several helper methods are sane.

        This method is just like
        :meth:`tests.test_entities.GenericTestCase.test_generic`, but with a
        slightly different set of mocks. Test the following:

        * :meth:`nailgun.entities.Subscription.delete_manifest`
        * :meth:`nailgun.entities.Subscription.manifest_history`
        * :meth:`nailgun.entities.Subscription.refresh_manifest`
        * :meth:`nailgun.entities.Subscription.upload`

        It would be ideal if these method could be refactored such that this
        unit test could be dropped.

        """
        cfg = config.ServerConfig('http://example.com')
        generic = {'server_config': cfg, 'id': 1}
        methods_requests = (
            (entities.Subscription(**generic).delete_manifest, 'post'),
            (entities.Subscription(**generic).manifest_history, 'get'),
            (entities.Subscription(**generic).refresh_manifest, 'put'),
            (entities.Subscription(**generic).upload, 'post'),
        )
        for method, request in methods_requests:
            with self.subTest((method, request)):
                self.assertEqual(
                    inspect.getargspec(method),
                    (['self', 'synchronous'], None, 'kwargs', (True,))
                )
                kwargs = {'data': gen_integer()}
                with mock.patch.object(entities, '_handle_response') as handlr:
                    with mock.patch.object(client, request) as client_request:
                        with mock.patch.object(
                            entities.Subscription,
                            '_org_path'
                        ) as org_path:
                            response = method(**kwargs)
                self.assertEqual(client_request.call_count, 1)
                self.assertEqual(len(client_request.call_args[0]), 1)
                self.assertEqual(client_request.call_args[1], kwargs)
                self.assertEqual(handlr.call_count, 1)
                self.assertEqual(handlr.return_value, response)
                self.assertEqual(org_path.call_count, 1)
                self.assertEqual(org_path.call_args[0][1], kwargs['data'])


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

    def test_to_json(self):
        """json serialization"""
        kwargs = {
            'id': 1,
            'description': 'some description',
            'label': 'some label',
            'name': 'Nailgun Org',
            'title': 'some title',
        }
        org = entities.Organization(config.ServerConfig('foo'), **kwargs)
        self.assertEqual(kwargs, json.loads(org.to_json()))


class PackageTestCase(TestCase):
    """Class with entity Package tests"""
    def test_to_json(self):
        """Check json serialisation on nested entities"""
        package_kwargs = {
            'nvrea': u'sclo-git25-1.0-2.el7.x86_64',
            'checksum': (
                u'751e639a0b8add0adc0c5cf0bf77693b3197b17533037ce2e7b9daa6188'
                u'98b99'
            ),
            'summary': u'Package that installs sclo-git25',
            'filename': u'sclo-git25-1.0-2.el7.x86_64.rpm',
            'epoch': u'0', 'version': u'1.0',
            'nvra': u'sclo-git25-1.0-2.el7.x86_64',
            'release': u'2.el7',
            'sourcerpm': u'sclo-git25-1.0-2.el7.src.rpm',
            'arch': u'x86_64',
            'id': 64529,
            'name': u'sclo-git25'
        }
        cfg = config.ServerConfig(
            url='https://foo.bar', verify=False,
            auth=('foo', 'bar'))
        repo_kwargs = {'id': 3, 'content_type': 'rpm'}
        repo = entities.Repository(cfg, **repo_kwargs)
        package = entities.Package(cfg, repository=repo, **package_kwargs)
        package_kwargs['repository'] = repo_kwargs
        self.assertDictEqual(package_kwargs, json.loads(package.to_json()))


class PackageGroupTestCase(TestCase):
    """Class with entity Package Group tests"""
    def test_to_json(self):
        """Check json serialisation on nested entities"""
        pkg_group_kwargs = {
            'description': None,
            'id': 3,
            'name': 'birds',
            'uuid': 'a12c62a5-b452-4dfb-987c-86c8b287460a'
        }

        cfg = config.ServerConfig(
            url='https://foo.bar', verify=False,
            auth=('foo', 'bar'))
        pkg_group = entities.PackageGroup(cfg, **pkg_group_kwargs)
        self.assertDictEqual(pkg_group_kwargs, json.loads(pkg_group.to_json()))


class ModuleStreamTestCase(TestCase):
    """Class with entity Module Stream tests"""
    def test_to_json(self):
        """Check json serialisation on nested entities"""
        module_stream_kwargs = {
            "id": 3,
            "name": "walrus",
            "uuid": "3b65bae5-8b4a-4984-a06e-b2ef9dfeb584",
            "version": "20180707144203",
            "context": "c0ffee42",
            "stream": "0.71",
            "arch": "x86_64",
            "description": "A module for the walrus 0.71 package",
            "summary": "Walrus 0.71 module",
            "module_spec": "walrus:0.71:20180707144203:c0ffee42:x86_64"
        }

        cfg = config.ServerConfig(
            url='https://foo.bar', verify=False,
            auth=('foo', 'bar'))
        module_stream_group = entities.ModuleStream(cfg, **module_stream_kwargs)
        self.assertDictEqual(module_stream_kwargs,
                             json.loads(module_stream_group.to_json()))


class HandleResponseTestCase(TestCase):
    """Test ``nailgun.entities._handle_response``."""

    def test_default(self):
        """Don't give the response any special status code."""
        response = mock.Mock()
        response.headers = {'content-type': 'application/json'}
        self.assertEqual(
            entities._handle_response(response, 'foo'),  # pylint:disable=W0212
            response.json.return_value,
        )
        self.assertEqual(
            response.mock_calls,
            [mock.call.raise_for_status(), mock.call.json()],
        )

    def test_json_content(self):
        """Give the response JSON content type"""
        response = mock.Mock()
        response.headers = {'content-type': 'application/json; charset=utf-8'}
        self.assertEqual(
            entities._handle_response(response, 'foo'),  # pylint:disable=W0212
            response.json.return_value,
        )
        self.assertEqual(
            response.mock_calls,
            [mock.call.raise_for_status(), mock.call.json()],
        )

    def test_no_json_content(self):
        """Check if no JSON content type response return response.content."""
        response = mock.Mock()
        response.headers = {'content-type': 'not_application_json'}
        self.assertEqual(
            entities._handle_response(response, 'foo'),  # pylint:disable=W0212
            response.content,
        )
        self.assertEqual(
            response.mock_calls,
            [mock.call.raise_for_status()],
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
        response.headers = {'content-type': 'application/json'}
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
        cls.cfg_620 = config.ServerConfig('bogus url', version='6.2.0')

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
            with mock.patch.object(EntityReadMixin, 'read_json'):
                with mock.patch.object(EntityReadMixin, 'read') as read:
                    entity(self.cfg_610).read()
            self.assertTrue(
                read.call_args[0][2] is None or
                'organization' not in read.call_args[0][2]
            )

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

    def test_hostpackage(self):
        """Attempt to create a :class:`nailgun.entities.HostPackage` for the
        Satellite 6.1.

        Assert that ``HostPackage`` raises ``NotImplementedError`` exception.
        """
        with self.assertRaises(NotImplementedError):
            entities.HostPackage(self.cfg_610, host=1)

    def test_hostsubscription(self):
        """Attempt to create a :class:`nailgun.entities.HostSubscription` for
        the Satellite 6.1.

        Assert that ``HostSubscription`` raises ``NotImplementedError``
        exception.
        """
        with self.assertRaises(NotImplementedError):
            entities.HostSubscription(self.cfg_610, host=1)

    def test_system(self):
        """Attempt to create a :class:`nailgun.entities.System` for the
        Satellite 6.2.

        Assert that ``System`` raises ``DeprecationWarning`` exception.
        """
        with self.assertRaises(DeprecationWarning):
            entities.System(self.cfg_620)

    def test_systempackage(self):
        """Attempt to create a :class:`nailgun.entities.SystemPackage` for the
        Satellite 6.1.

        Assert that ``SystemPackage`` raises ``DeprecationWarning`` exception.
        """
        with self.assertRaises(DeprecationWarning):
            entities.SystemPackage(self.cfg_620)


class JsonSerializableTestCase(TestCase):
    """Test regarding Json serializable on different object"""

    def test_regular_objects(self):
        """Checking regular objects transformation"""
        lst = [[1, 0.3], {'name': 'foo'}]
        self.assertEqual(lst, entities.to_json_serializable(lst))

    def test_entities(self):
        """Testing nested entities serialization"""
        package_kwargs = {
            'nvrea': u'sclo-git25-1.0-2.el7.x86_64',
            'checksum': (
                u'751e639a0b8add0adc0c5cf0bf77693b3197b17533037ce2e7b9daa6188'
                u'98b99'
            ),
            'summary': u'Package that installs sclo-git25',
            'filename': u'sclo-git25-1.0-2.el7.x86_64.rpm',
            'epoch': u'0', 'version': u'1.0',
            'nvra': u'sclo-git25-1.0-2.el7.x86_64',
            'release': u'2.el7',
            'sourcerpm': u'sclo-git25-1.0-2.el7.src.rpm',
            'arch': u'x86_64',
            'id': 64529,
            'name': u'sclo-git25'
        }

        repo_kwargs = {'id': 3, 'content_type': 'file'}
        repo = make_entity(entities.Repository, **repo_kwargs)
        package = make_entity(entities.Package,
                              repository=repo,
                              **package_kwargs)
        package_kwargs['repository'] = repo_kwargs

        org_kwargs = {
            'id': 1,
            'description': 'some description',
            'label': 'some label',
            'name': 'Nailgun Org',
            'title': 'some title',
        }
        org = make_entity(entities.Organization, **org_kwargs)

        to_be_transformed = [{'packages': [package]}, {'org': org}]
        expected = [{'packages': [package_kwargs]}, {'org': org_kwargs}]
        self.assertListEqual(
            expected,
            entities.to_json_serializable(to_be_transformed)
        )

    def test_nested_entities(self):
        """Check nested entities serialization"""
        env_kwargs = {'id': 1, 'name': 'env'}
        env = make_entity(entities.Environment, **env_kwargs)

        location_kwargs = {'name': 'loc'}
        locations = [make_entity(entities.Location, **location_kwargs)]

        hostgroup_kwargs = {'id': 2, 'name': 'hgroup'}
        hostgroup = make_entity(
            entities.HostGroup,
            location=locations,
            **hostgroup_kwargs)

        hostgroup_kwargs['location'] = [location_kwargs]

        combinations = [
            {'environment_id': 3, 'hostgroup_id': 4},
            make_entity(entities.TemplateCombination,
                        hostgroup=hostgroup,
                        environment=env)
        ]

        expected_combinations = [
            {'environment_id': 3, 'hostgroup_id': 4},
            {'environment': env_kwargs, 'hostgroup': hostgroup_kwargs}
        ]

        cfg_kwargs = {'id': 5, 'snippet': False, 'template': 'cat'}
        cfg_template = make_entity(
            entities.ProvisioningTemplate,
            template_combinations=combinations,
            **cfg_kwargs)

        cfg_kwargs['template_combinations'] = expected_combinations
        self.assertDictEqual(cfg_kwargs,
                             entities.to_json_serializable(cfg_template))

    def test_date_field(self):
        """Check date field serialization"""

        errata = make_entity(entities.Errata, issued=date(2016, 9, 20))
        self.assertDictEqual(
            {'issued': '2016-09-20'},
            entities.to_json_serializable(errata)
        )

    def test_boolean_datetime_float(self):
        """Check serialization for boolean, datetime and float fields"""
        kwargs = {
            'pending': True,
            'progress': 0.25,
            'started_at': datetime(2016, 11, 20, 1, 2, 3)
        }
        task = make_entity(
            entities.ForemanTask, **kwargs)
        kwargs['started_at'] = '2016-11-20 01:02:03'
        self.assertDictEqual(kwargs, entities.to_json_serializable(task))


class VirtWhoConfigTestCase(TestCase):
    """
    Tests for :class:`nailgun.entities.VirtWhoConfig`
    """
    @classmethod
    def setUpClass(cls):
        cls.server = 'sat.example.com'
        cls.cfg = config.ServerConfig('http://{}/'.format(cls.server))

    def test_create(self):
        org = entities.Organization(self.cfg, name='vhorg', id=2)
        vh = entities.VirtWhoConfig(server_config=self.cfg, name='vhtest1',
                                    organization_id=org.id,
                                    filtering_mode=1,
                                    whitelist='*.example.com',
                                    proxy='proxy.example.com',
                                    no_proxy='*.proxy-bypass.example.com',
                                    satellite_url=self.server,
                                    hypervisor_type='libvirt',
                                    hypervisor_username='root',
                                    hypervisor_server='libvirt.example.com',
                                    hypervisor_id='hostname',
                                    hypervisor_password='',
                                    debug=True)

        expected_dict = {
            'foreman_virt_who_configure_config':
                {
                    'debug': True,
                    'filtering_mode': 1,
                    'hypervisor_id': 'hostname',
                    'hypervisor_server': 'libvirt.example.com',
                    'hypervisor_type': 'libvirt',
                    'hypervisor_username': 'root',
                    'hypervisor_password': '',
                    'name': 'vhtest1',
                    'no_proxy': '*.proxy-bypass.example.com',
                    'organization_id': 2,
                    'proxy': 'proxy.example.com',
                    'satellite_url': self.server,
                    'whitelist': '*.example.com'
                }
        }
        self.assertDictEqual(expected_dict, vh.create_payload())

    def test_update(self):
        org = entities.Organization(self.cfg, name='vhorg', id=2)
        vh = entities.VirtWhoConfig(server_config=self.cfg, name='vhtest1',
                                    organization_id=org.id,
                                    filtering_mode=1,
                                    whitelist='*.example.com',
                                    proxy='proxy.example.com',
                                    no_proxy='*.proxy-bypass.example.com',
                                    satellite_url=self.server,
                                    hypervisor_type='libvirt',
                                    hypervisor_username='root',
                                    hypervisor_server='libvirt.example.com',
                                    hypervisor_id='hostname',
                                    hypervisor_password='',
                                    debug=True)

        vh.name = 'newname'
        vh.hypervisor_username = 'admin'

        expected_dict = {
            'foreman_virt_who_configure_config':
                {
                    'hypervisor_username': 'admin',
                    'name': 'newname',
                }
        }
        self.assertDictEqual(expected_dict,
                             vh.update_payload(['name', 'hypervisor_username']))


class JobInvocationTestCase(TestCase):
    """Tests for :class:`nailgun.entities.JobInvocation`."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = config.ServerConfig('http://example.com')

    def test_required_param(self):
        """Check required parameters"""
        data_list = [
            {'inputs': 'ls', 'search_query': 'foo'},
            {'feature': 'foo', 'inputs': 'ls'},
            {'job_template_id': 1, 'search_query': 'foo'},
            {'feature': 'foo', 'bookmark_id': 1, 'inputs': 'ls'},
            {'feature': 'foo', 'bookmark_id': 1, 'targeting_type': 'foo'},
        ]
        for data in data_list:
            with self.assertRaises(KeyError):
                entities.JobInvocation(self.cfg).run(data=data)

    def test_non_sync_run(self):
        """Run job asynchronously with valid parameters and check that correct
        post request is sent
        """
        with mock.patch.object(client, 'post') as post:
            entities.JobInvocation(self.cfg).run(synchronous=False, data={
                'job_template_id': 1,
                'search_query': 'foo',
                'inputs': 'ls',
                'targeting_type': 'foo'
            })
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(post.call_args[0]), 1)

    def test_sync_run(self):
        """Check that sync run will result in ForemanTask poll"""
        with mock.patch.object(entities, '_poll_task') as poll_task:
            with mock.patch.object(client, 'post'):
                entities.JobInvocation(self.cfg).run(synchronous=True, data={
                    'job_template_id': 1,
                    'search_query': 'foo',
                    'inputs': 'ls',
                    'targeting_type': 'foo'
                })
        self.assertEqual(poll_task.call_count, 1)
