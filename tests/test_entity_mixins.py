# -*- coding: utf-8 -*-
"""Tests for :mod:`nailgun.entity_mixins`."""
# Python 3.3 and later includes module `ipaddress` in the standard library. If
# NailGun ever moves past Python 2.x, that module should be used instead of
# `socket`.
from fauxfactory import gen_integer
from nailgun import client, config, entity_mixins
from nailgun.entity_fields import (
    IntegerField,
    OneToManyField,
    OneToOneField,
    StringField,
)
from requests.exceptions import HTTPError
import mock

from sys import version_info
if version_info.major == 2:
    import httplib as http_client  # pylint:disable=import-error
else:
    import http.client as http_client  # pylint:disable=import-error
if version_info < (3, 4):
    from unittest2 import TestCase  # pylint:disable=import-error
else:
    from unittest import TestCase

# pylint:disable=too-many-lines
# The size of this module is a direct reflection of the size of module
# `nailgun.entity_mixins`. It would be good to split that module up, then split
# this module up similarly.

# This module is divided in to the following sections:
#
# 1. Entity defintions.
# 2. Tests for private methods.
# 3. Tests for public methods.
#
# 1. Entity definitions. ------------------------------------------------- {{{1


class SampleEntity(entity_mixins.Entity):
    """Sample entity to be used in the tests"""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {'name': StringField(), 'number': IntegerField()}
        self._meta = {'api_path': 'foo'}
        super(SampleEntity, self).__init__(server_config, **kwargs)


class SampleEntityTwo(entity_mixins.Entity):
    """An entity with foreign key fields.

    This class has a :class:`nailgun.entity_fields.OneToManyField` called
    "one_to_many" pointing to :class:`tests.test_entity_mixins.SampleEntity`.

    """

    def __init__(self, server_config=None, **kwargs):
        self._fields = {'one_to_many': OneToManyField(SampleEntity)}
        super(SampleEntityTwo, self).__init__(server_config, **kwargs)


class EntityWithCreate(entity_mixins.Entity, entity_mixins.EntityCreateMixin):
    """Inherits from :class:`nailgun.entity_mixins.EntityCreateMixin`."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {'api_path': ''}
        super(EntityWithCreate, self).__init__(server_config, **kwargs)


class EntityWithRead(entity_mixins.Entity, entity_mixins.EntityReadMixin):
    """Inherits from :class:`nailgun.entity_mixins.EntityReadMixin`."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {'api_path': ''}
        super(EntityWithRead, self).__init__(server_config, **kwargs)


class EntityWithUpdate(entity_mixins.Entity, entity_mixins.EntityUpdateMixin):
    """Inherits from :class:`nailgun.entity_mixins.EntityUpdateMixin`."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {'api_path': ''}
        super(EntityWithUpdate, self).__init__(server_config, **kwargs)


class EntityWithDelete(entity_mixins.Entity, entity_mixins.EntityDeleteMixin):
    """Inherits from :class:`nailgun.entity_mixins.EntityDeleteMixin`."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {'api_path': ''}
        super(EntityWithDelete, self).__init__(server_config, **kwargs)


class EntityWithSearch(entity_mixins.Entity, entity_mixins.EntitySearchMixin):
    """Inherits from :class:`nailgun.entity_mixins.EntitySearchMixin`."""

    def __init__(self, server_config=None, **kwargs):
        self._meta = {'api_path': ''}
        super(EntityWithSearch, self).__init__(server_config, **kwargs)


class EntityWithSearch2(EntityWithSearch):
    """An entity with integer, one to one and one to many fields."""

    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'one': OneToOneField(SampleEntity),
            'many': OneToManyField(SampleEntity),
        }
        super(EntityWithSearch2, self).__init__(server_config, **kwargs)


# 2. Tests for private methods. ------------------------------------------ {{{1


class MakeEntityFromIdTestCase(TestCase):
    """Tests for :func:`nailgun.entity_mixins._make_entity_from_id`."""
    # pylint:disable=protected-access

    def setUp(self):
        """Set ``self.cfg``."""
        self.cfg = config.ServerConfig('example.com')

    def test_pass_in_entity_obj(self):
        """Let the ``entity_obj_or_id`` argument be an entity object."""
        self.assertIsInstance(
            entity_mixins._make_entity_from_id(
                SampleEntity,
                SampleEntity(self.cfg),
                self.cfg
            ),
            SampleEntity
        )

    def test_pass_in_entity_id(self):
        """Let the ``entity_obj_or_id`` argument be an integer."""
        entity_id = gen_integer(min_value=1)
        entity_obj = entity_mixins._make_entity_from_id(
            SampleEntity,
            entity_id,
            self.cfg
        )
        self.assertIsInstance(entity_obj, SampleEntity)
        self.assertEqual(entity_obj.id, entity_id)  # pylint:disable=no-member


class MakeEntitiesFromIdsTestCase(TestCase):
    """Tests for :func:`nailgun.entity_mixins._make_entities_from_ids`."""
    # pylint:disable=protected-access

    def setUp(self):
        """Set ``self.cfg``."""
        self.cfg = config.ServerConfig('example.com')

    def test_pass_in_emtpy_iterable(self):
        """Let the ``entity_objs_and_ids`` argument be an empty iterable."""
        for iterable in ([], tuple()):
            self.assertEqual(
                entity_mixins._make_entities_from_ids(
                    SampleEntity,
                    iterable,
                    self.cfg
                ),
                [],
            )

    def test_pass_in_entity_obj(self):
        """Let the ``entity_objs_and_ids`` arg be an iterable of entities."""
        for num_entities in range(4):
            input_entities = [
                SampleEntity(self.cfg) for _ in range(num_entities)
            ]
            output_entities = entity_mixins._make_entities_from_ids(
                SampleEntity,
                input_entities,
                self.cfg
            )
            self.assertEqual(num_entities, len(output_entities))
            for output_entity in output_entities:
                self.assertIsInstance(output_entity, SampleEntity)

    def test_pass_in_entity_ids(self):
        """Let the ``entity_objs_and_ids`` arg be an iterable of integers."""
        for num_entities in range(4):
            entity_ids = [
                gen_integer(min_value=1) for _ in range(num_entities)
            ]
            entities = entity_mixins._make_entities_from_ids(
                SampleEntity,
                entity_ids,
                self.cfg
            )
            self.assertEqual(len(entities), len(entity_ids))
            for i in range(len(entity_ids)):
                self.assertIsInstance(entities[i], SampleEntity)
                self.assertEqual(entities[i].id, entity_ids[i])

    def test_pass_in_both(self):
        """Let ``entity_objs_and_ids`` be an iterable of integers and IDs."""
        entities = entity_mixins._make_entities_from_ids(
            SampleEntity,
            [SampleEntity(self.cfg), 5],
            self.cfg
        )
        self.assertEqual(len(entities), 2)
        for entity in entities:
            self.assertIsInstance(entity, SampleEntity)


class PollTaskTestCase(TestCase):
    """Tests for :func:`nailgun.entity_mixins._poll_task`."""

    def setUp(self):
        """Create a bogus server configuration object."""
        self.cfg = config.ServerConfig('bogus url')

    def test__poll_task_failure(self):
        """What happens when a foreman task completes but does not succeed?

        Assert that a :class:`nailgun.entity_mixins.TaskFailedError` exception
        is raised.

        """
        for state in ('paused', 'stopped'):
            with self.subTest(state):
                with mock.patch.object(client, 'get') as get:
                    get.return_value.json.return_value = {
                        'state': state,
                        'result': 'not success'
                    }
                    with self.assertRaises(entity_mixins.TaskFailedError):
                        # pylint:disable=protected-access
                        entity_mixins._poll_task(gen_integer(), self.cfg)

    def test__poll_task_success(self):
        """What happens when a foreman task completes and does succeed?

        Assert that the server's response is returned.

        """
        for state in ('paused', 'stopped'):
            with self.subTest(state):
                with mock.patch.object(client, 'get') as get:
                    get.return_value.json.return_value = {
                        'state': state,
                        'result': 'success'
                    }
                    self.assertEqual(
                        get.return_value.json.return_value,
                        # pylint:disable=protected-access
                        entity_mixins._poll_task(gen_integer(), self.cfg),
                    )


# 3. Tests for public methods. ------------------------------------------- {{{1


class EntityTestCase(TestCase):
    """Tests for :class:`nailgun.entity_mixins.Entity`."""

    def setUp(self):
        """Set ``self.cfg``."""
        self.cfg = config.ServerConfig('http://example.com')

    def test_init_v1(self):
        """Provide no value for the ``server_config`` argument."""
        with mock.patch.object(config.ServerConfig, 'get') as sc_get:
            self.assertEqual(
                SampleEntity()._server_config,  # pylint:disable=W0212
                sc_get.return_value,
            )
        self.assertEqual(sc_get.call_count, 1)

    def test_init_v2(self):
        """Provide a server config object via ``DEFAULT_SERVER_CONFIG``."""
        backup = entity_mixins.DEFAULT_SERVER_CONFIG
        try:
            entity_mixins.DEFAULT_SERVER_CONFIG = config.ServerConfig('url')
            self.assertEqual(
                SampleEntity()._server_config,  # pylint:disable=W0212
                entity_mixins.DEFAULT_SERVER_CONFIG,
            )
        finally:
            entity_mixins.DEFAULT_SERVER_CONFIG = backup

    def test_entity_get_fields(self):
        """Test :meth:`nailgun.entity_mixins.Entity.get_fields`."""
        fields = SampleEntity(self.cfg).get_fields()
        self.assertEqual(len(fields), 3)
        self.assertEqual(set(fields.keys()), {'id', 'name', 'number'})
        self.assertIsInstance(fields['name'], StringField)
        self.assertIsInstance(fields['number'], IntegerField)

    def test_entity_get_values(self):
        """Test :meth:`nailgun.entity_mixins.Entity.get_values`."""
        for values in (
                {},
                {'id': gen_integer()},
                {'name': gen_integer()},
                {'number': gen_integer()},
                {'name': gen_integer(), 'number': gen_integer()},
                {
                    'id': gen_integer(),
                    'name': gen_integer(),
                    'number': gen_integer(),
                },
        ):
            self.assertEqual(
                SampleEntity(self.cfg, **values).get_values(),
                values,
            )

    def test_path(self):
        """Test :meth:`nailgun.entity_mixins.Entity.path`."""
        # e.g. 'https://sat.example.com/katello/api/v2'
        path = '{0}/{1}'.format(
            self.cfg.url,
            # pylint:disable=protected-access
            SampleEntity(self.cfg)._meta['api_path']
        )

        # Call `path()` on an entity with no ID.
        self.assertEqual(SampleEntity(self.cfg).path(), path)
        self.assertEqual(SampleEntity(self.cfg).path('base'), path)
        with self.assertRaises(entity_mixins.NoSuchPathError):
            SampleEntity(self.cfg).path('self')

        # Call `path()` on an entity with an ID.
        self.assertEqual(SampleEntity(self.cfg, id=5).path(), path + '/5')
        self.assertEqual(SampleEntity(self.cfg, id=5).path('base'), path)
        self.assertEqual(SampleEntity(self.cfg, id=5).path('self'), path+'/5')

    def test_no_such_field_error(self):
        """Try to raise a :class:`nailgun.entity_mixins.NoSuchFieldError`."""
        SampleEntity(self.cfg, name='Alice')
        with self.assertRaises(entity_mixins.NoSuchFieldError):
            SampleEntity(self.cfg, namee='Alice')

    def test_bad_value_error(self):
        """Try to raise a :class:`nailgun.entity_mixins.BadValueError`."""
        SampleEntityTwo(self.cfg, one_to_many=[1])
        with self.assertRaises(entity_mixins.BadValueError):
            SampleEntityTwo(self.cfg, one_to_many=1)

    def test_repr_v1(self):
        """Test method ``nailgun.entity_mixins.Entity.__repr__``.

        Assert that ``__repr__`` works correctly when no arguments are passed
        to an entity.

        """
        entity = SampleEntityTwo(self.cfg)
        target = 'tests.test_entity_mixins.SampleEntityTwo({0})'.format(
            repr(self.cfg)
        )
        self.assertEqual(repr(entity), target)
        import nailgun  # noqa pylint:disable=unused-variable
        import tests  # noqa pylint:disable=unused-variable
        # pylint:disable=eval-used
        self.assertEqual(repr(eval(repr(entity))), target)

    def test_repr_v2(self):
        """Test method ``nailgun.entity_mixins.Entity.__repr__``.

        Assert that ``__repr__`` works correctly when an ID is passed to an
        entity.

        """
        entity = SampleEntityTwo(self.cfg, id=gen_integer())
        target = (
            'tests.test_entity_mixins.SampleEntityTwo({0}, id={1})'
            .format(repr(self.cfg), entity.id)  # pylint:disable=no-member
        )
        self.assertEqual(repr(entity), target)
        import nailgun  # noqa pylint:disable=unused-variable
        import tests  # noqa pylint:disable=unused-variable
        # pylint:disable=eval-used
        self.assertEqual(repr(eval(repr(entity))), target)

    def test_repr_v3(self):
        """Test method ``nailgun.entity_mixins.Entity.__repr__``.

        Assert that ``__repr__`` works correctly when one entity has a foreign
        key relationship to a second entity.

        """
        entity_id = gen_integer()
        target = (
            'tests.test_entity_mixins.SampleEntityTwo('
            '{0}, '
            'one_to_many=[tests.test_entity_mixins.SampleEntity({0}, id={1})]'
            ')'
            .format(self.cfg, entity_id)
        )
        entity = SampleEntityTwo(
            self.cfg,
            one_to_many=[SampleEntity(self.cfg, id=entity_id)]
        )
        self.assertEqual(repr(entity), target)
        import nailgun  # noqa pylint:disable=unused-variable
        import tests  # noqa pylint:disable=unused-variable
        # pylint:disable=eval-used
        self.assertEqual(repr(eval(repr(entity))), target)


class EntityCreateMixinTestCase(TestCase):
    """Tests for :class:`nailgun.entity_mixins.EntityCreateMixin`."""

    def setUp(self):
        """Set ``self.entity = EntityWithCreate(…)``."""
        self.entity = EntityWithCreate(
            config.ServerConfig('example.com'),
            id=gen_integer(min_value=1),
        )

    def test_create_missing(self):
        """Call method ``create_missing``."""

        class FKEntityWithCreate(
                entity_mixins.Entity,
                entity_mixins.EntityCreateMixin):
            """An entity that can be created and has foreign key fields."""

            def __init__(self, server_config=None, **kwargs):
                self._fields = {
                    'int': IntegerField(required=True),
                    'int_choices': IntegerField(choices=(1, 2), required=True),
                    'int_default': IntegerField(default=5, required=True),
                    'many': OneToManyField(SampleEntity, required=True),
                    'one': OneToOneField(SampleEntity, required=True),
                }
                super(FKEntityWithCreate, self).__init__(
                    server_config,
                    **kwargs
                )

        cfg = config.ServerConfig('example.com')
        entity = FKEntityWithCreate(cfg)
        with mock.patch.object(entity._fields['many'], 'gen_value') as gen1:
            with mock.patch.object(entity._fields['one'], 'gen_value') as gen2:
                self.assertEqual(entity.create_missing(), None)
        for gen_value in gen1, gen2:
            self.assertEqual(
                gen_value.mock_calls,
                [
                    mock.call(),  # gen_value() returns a class. The returned
                    mock.call()(cfg),  # class is instantiated, and
                    mock.call()().create(True),  # create(True) is called.
                ]
            )
        self.assertEqual(
            set(entity.get_fields().keys()) - {'id'},
            set(entity.get_values().keys()),
        )
        self.assertIn(entity.int_choices, (1, 2))  # pylint:disable=no-member
        self.assertEqual(entity.int_default, 5)  # pylint:disable=no-member

    def test_create_raw_v1(self):
        """What happens if the ``create_missing`` arg is not specified?

        :meth:`nailgun.entity_mixins.EntityCreateMixin.create_raw` should
        default to :data:`nailgun.entity_mixins.CREATE_MISSING`. We do not set
        ``CREATE_MISSING`` in this test. It is a process-wide variable, and
        setting it may prevent tests from being run in parallel.

        """
        with mock.patch.object(self.entity, 'create_missing') as c_missing:
            with mock.patch.object(self.entity, 'create_payload') as c_payload:
                with mock.patch.object(client, 'post') as post:
                    self.entity.create_raw()
        self.assertEqual(
            c_missing.call_count,
            1 if entity_mixins.CREATE_MISSING else 0
        )
        self.assertEqual(c_payload.call_count, 1)
        self.assertEqual(post.call_count, 1)

    def test_create_raw_v2(self):
        """What happens if the ``create_missing`` arg is ``True``?"""
        with mock.patch.object(self.entity, 'create_missing') as c_missing:
            with mock.patch.object(self.entity, 'create_payload') as c_payload:
                with mock.patch.object(client, 'post') as post:
                    self.entity.create_raw(True)
        self.assertEqual(c_missing.call_count, 1)
        self.assertEqual(c_payload.call_count, 1)
        self.assertEqual(post.call_count, 1)

    def test_create_raw_v3(self):
        """What happens if the ``create_missing`` arg is ``False``?"""
        with mock.patch.object(self.entity, 'create_missing') as c_missing:
            with mock.patch.object(self.entity, 'create_payload') as c_payload:
                with mock.patch.object(client, 'post') as post:
                    self.entity.create_raw(False)
        self.assertEqual(c_missing.call_count, 0)
        self.assertEqual(c_payload.call_count, 1)
        self.assertEqual(post.call_count, 1)

    def test_create_json(self):
        """Test :meth:`nailgun.entity_mixins.EntityCreateMixin.create_json`."""
        for create_missing in (None, True, False):
            response = mock.Mock()
            response.json.return_value = gen_integer()
            with mock.patch.object(self.entity, 'create_raw') as create_raw:
                create_raw.return_value = response
                self.entity.create_json(create_missing)
            self.assertEqual(create_raw.call_count, 1)
            self.assertEqual(create_raw.call_args[0][0], create_missing)
            self.assertEqual(response.raise_for_status.call_count, 1)
            self.assertEqual(response.json.call_count, 1)

    def test_create(self):
        """Test :meth:`nailgun.entity_mixins.EntityCreateMixin.create`."""

        class EntityWithCreateRead(
                EntityWithCreate,
                entity_mixins.EntityReadMixin):
            """An entity that can be created and read."""

        readable = EntityWithCreateRead(
            config.ServerConfig('example.com'),
            id=gen_integer(),
        )
        for create_missing in (None, True, False):
            with mock.patch.object(readable, 'create_json') as create_json:
                create_json.return_value = gen_integer()
                with mock.patch.object(readable, 'read') as read:
                    readable.create(create_missing)
            self.assertEqual(create_json.call_count, 1)
            self.assertEqual(create_json.call_args[0][0], create_missing)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(
                read.call_args[1]['attrs'],
                create_json.return_value,
            )


class EntityReadMixinTestCase(TestCase):
    """Tests for :class:`nailgun.entity_mixins.EntityReadMixin`."""

    @classmethod
    def setUpClass(cls):
        """Set ``cls.test_entity``.

        ``test_entity`` is a class having one to one and one to many fields.

        """
        class TestEntity(entity_mixins.Entity, entity_mixins.EntityReadMixin):
            """An entity with several different types of fields."""

            def __init__(self, server_config=None, **kwargs):
                self._fields = {
                    'ignore_me': IntegerField(),
                    'many': OneToManyField(SampleEntity),
                    'none': OneToOneField(SampleEntity),
                    'one': OneToOneField(SampleEntity),
                }
                self._meta = {'api_path': ''}
                super(TestEntity, self).__init__(server_config, **kwargs)

        cls.test_entity = TestEntity

    def setUp(self):
        """Set ``self.entity = EntityWithRead(…)``."""
        self.cfg = config.ServerConfig('example.com')
        self.entity = EntityWithRead(self.cfg, id=gen_integer(min_value=1))

    def test_read_raw(self):
        """Call :meth:`nailgun.entity_mixins.EntityReadMixin.read_raw`."""
        with mock.patch.object(client, 'get') as get:
            self.entity.read_raw()
        self.assertEqual(get.call_count, 1)
        self.assertEqual(len(get.call_args[0]), 1)  # path='…'
        self.assertEqual(get.call_args[0][0], self.entity.path())
        self.assertEqual(
            get.call_args[1],
            # pylint:disable=protected-access
            self.entity._server_config.get_client_kwargs(),
        )

    def test_read_json(self):
        """Call :meth:`nailgun.entity_mixins.EntityReadMixin.read_json`."""
        response = mock.Mock()
        response.json.return_value = gen_integer()
        with mock.patch.object(self.entity, 'read_raw') as read_raw:
            read_raw.return_value = response
            self.entity.read_json()
        self.assertEqual(read_raw.call_count, 1)
        self.assertEqual(response.raise_for_status.call_count, 1)
        self.assertEqual(response.json.call_count, 1)

    def test_read_v1(self):
        """Make ``read_json`` return hashes."""
        # Generate some bogus values and call `read`.
        entity_1 = self.test_entity(self.cfg)
        attrs = {
            'id': gen_integer(min_value=1),
            'manies': [{'id': gen_integer(min_value=1)}],
            'none': None,
            'one': {'id': gen_integer(min_value=1)},
        }
        with mock.patch.object(entity_1, 'read_json') as read_json:
            read_json.return_value = attrs
            entity_2 = entity_1.read(ignore={'ignore_me'})

        # Make assertions about the call and the returned entity.
        self.assertEqual(
            entity_2._server_config,  # pylint:disable=protected-access
            self.cfg,
        )
        self.assertEqual(read_json.call_count, 1)
        self.assertEqual(
            set(entity_1.get_fields().keys()),
            set(entity_2.get_fields().keys()),
        )
        self.assertEqual(entity_2.id, attrs['id'])
        self.assertEqual(entity_2.many[0].id, attrs['manies'][0]['id'])
        self.assertEqual(entity_2.one.id, attrs['one']['id'])

    def test_read_v2(self):
        """Make ``read_json`` return hashes, but with different field names."""
        # Generate some bogus values and call `read`.
        entity_1 = self.test_entity(self.cfg)
        attrs = {'many': [{'id': gen_integer(min_value=1)}]}
        with mock.patch.object(entity_1, 'read_json') as read_json:
            read_json.return_value = attrs
            entity_2 = entity_1.read(ignore={'id', 'none', 'one', 'ignore_me'})

        # Make assertions about the call and the returned entity.
        self.assertEqual(
            entity_2._server_config,  # pylint:disable=protected-access
            self.cfg,
        )
        self.assertEqual(read_json.call_count, 1)
        self.assertEqual(
            set(entity_1.get_fields().keys()),
            set(entity_2.get_fields().keys()),
        )
        self.assertEqual(entity_2.many[0].id, attrs['many'][0]['id'])

    def test_read_v3(self):
        """Make ``read_json`` return IDs."""
        # Generate some bogus values and call `read`.
        entity_1 = self.test_entity(self.cfg)
        attrs = {
            'id': gen_integer(min_value=1),
            'many_ids': [gen_integer(min_value=1)],
            'none': None,
            'one_id': gen_integer(min_value=1),
        }
        with mock.patch.object(entity_1, 'read_json') as read_json:
            read_json.return_value = attrs
            entity_2 = entity_1.read(ignore={'ignore_me'})

        # Make assertions about the call and the returned entity.
        self.assertEqual(
            entity_2._server_config,  # pylint:disable=protected-access
            self.cfg,
        )
        self.assertEqual(read_json.call_count, 1)
        self.assertEqual(
            set(entity_1.get_fields().keys()),
            set(entity_2.get_fields().keys()),
        )
        self.assertEqual(entity_2.id, attrs['id'])
        self.assertEqual(entity_2.many[0].id, attrs['many_ids'][0])
        self.assertEqual(entity_2.one.id, attrs['one_id'])

    def test_read_v4(self):
        """Do not ignore any fields."""
        with mock.patch.object(
            entity_mixins.EntityReadMixin,
            'read_json',
            return_value={'id': gen_integer()},
        ) as read_json:
            entity = EntityWithRead(self.cfg).read()
        self.assertEqual(entity.get_values(), read_json.return_value)

    def test_missing_value_error(self):
        """Raise a :class:`nailgun.entity_mixins.MissingValueError`."""
        entity = self.test_entity(config.ServerConfig('example.com'))
        for attrs in (
                {
                    'id': gen_integer(min_value=1),
                    'none': None,
                    'one_id': gen_integer(min_value=1),
                },
                {
                    'id': gen_integer(min_value=1),
                    'many_ids': [gen_integer(min_value=1)],
                    'none': None,
                },
        ):
            with self.subTest(attrs):
                with mock.patch.object(entity, 'read_json') as read_json:
                    read_json.return_value = attrs
                    with self.assertRaises(entity_mixins.MissingValueError):
                        entity.read(ignore={'ignore_me'})


class EntityUpdateMixinTestCase(TestCase):
    """Tests for :class:`nailgun.entity_mixins.EntityUpdateMixin`."""

    def setUp(self):
        """Set ``self.entity = EntityWithUpdate(…)``."""
        self.entity = EntityWithUpdate(
            config.ServerConfig('example.com'),
            id=gen_integer(min_value=1),
        )

    def test_update_payload_v1(self):
        """Call :meth:`nailgun.entity_mixins.EntityUpdateMixin.update_payload`.

        Assert that the method behaves correctly given various values for the
        ``field`` argument.

        """

        class TestEntity(EntityWithUpdate):
            """Just like its parent class, but with fields."""

            def __init__(self, server_config=None, **kwargs):
                self._fields = {'one': IntegerField(), 'two': IntegerField()}
                super(TestEntity, self).__init__(server_config, **kwargs)

        cfg = config.ServerConfig('url')
        args_list = (
            {},
            {'one': gen_integer()},
            {'two': gen_integer()},
            {'one': gen_integer(), 'two': gen_integer()},
        )

        # Make `update_payload` return all or no values.
        for args in args_list:
            entity = TestEntity(cfg, **args)
            self.assertEqual(entity.update_payload(), args)
            self.assertEqual(entity.update_payload(list(args.keys())), args)
            self.assertEqual(entity.update_payload([]), {})

        # Make `update_payload` return only some values.
        entity = TestEntity(cfg, **args_list[-1])
        self.assertEqual(
            entity.update_payload(['one']),
            {'one': args_list[-1]['one']},
        )
        self.assertEqual(
            entity.update_payload(['two']),
            {'two': args_list[-1]['two']},
        )

        # Ask `update_payload` to return unavailable values.
        entity = TestEntity(cfg)
        for field_names in (['one'], ['two'], ['one', 'two']):
            with self.assertRaises(KeyError):
                entity.update_payload(field_names)

    def test_update_payload_v2(self):
        """Call :meth:`nailgun.entity_mixins.EntityUpdateMixin.update_payload`.

        Assign ``None`` to a ``OneToOneField`` and call ``update_payload``.

        """

        class TestEntity(EntityWithUpdate):
            """Just like its parent class, but with fields."""

            def __init__(self, server_config=None, **kwargs):
                self._fields = {'other': OneToOneField(SampleEntity)}
                super(TestEntity, self).__init__(server_config, **kwargs)

        cfg = config.ServerConfig('url')
        entities = [TestEntity(cfg, other=None), TestEntity(cfg)]
        entities[1].other = None  # pylint:disable=W0201
        for entity in entities:
            with self.subTest(entity):
                self.assertEqual(entity.update_payload(), {'other_id': None})

    def test_update_raw(self):
        """Call :meth:`nailgun.entity_mixins.EntityUpdateMixin.update_raw`."""
        with mock.patch.object(self.entity, 'update_payload') as u_payload:
            with mock.patch.object(client, 'put') as put:
                self.entity.update_raw()
        self.assertEqual(u_payload.call_count, 1)
        self.assertEqual(put.call_count, 1)
        self.assertEqual(len(put.call_args[0]), 2)  # path='…' and data={…}
        self.assertEqual(put.call_args[0][0], self.entity.path())
        self.assertEqual(
            put.call_args[1],
            # pylint:disable=protected-access
            self.entity._server_config.get_client_kwargs(),
        )

    def test_update_json(self):
        """Call :meth:`nailgun.entity_mixins.EntityUpdateMixin.update_json`."""
        response = mock.Mock()
        response.json.return_value = gen_integer()
        with mock.patch.object(self.entity, 'update_raw') as update_raw:
            update_raw.return_value = response
            self.entity.update_json()
        self.assertEqual(update_raw.call_count, 1)
        self.assertEqual(response.raise_for_status.call_count, 1)
        self.assertEqual(response.json.call_count, 1)

    def test_update(self):
        """Test :meth:`nailgun.entity_mixins.EntityUpdateMixin.update`."""

        class EntityWithUpdateRead(
                EntityWithUpdate,
                entity_mixins.EntityReadMixin):
            """An entity that can be updated and read."""

        readable = EntityWithUpdateRead(
            config.ServerConfig('example.com'),
            id=gen_integer(),
        )
        with mock.patch.object(readable, 'update_json') as update_json:
            update_json.return_value = gen_integer()
            with mock.patch.object(readable, 'read') as read:
                readable.update()
        self.assertEqual(update_json.call_count, 1)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(
            read.call_args[1]['attrs'],
            update_json.return_value,
        )


class EntityDeleteMixinTestCase(TestCase):
    """Tests for :class:`nailgun.entity_mixins.EntityDeleteMixin`."""

    def setUp(self):
        """Set ``self.entity = EntityWithDelete(…)``."""
        self.entity = EntityWithDelete(
            config.ServerConfig('example.com'),
            id=gen_integer(min_value=1),
        )

    def test_delete_raw(self):
        """Call :meth:`nailgun.entity_mixins.EntityDeleteMixin.delete_raw`."""
        with mock.patch.object(client, 'delete') as delete:
            self.entity.delete_raw()
        self.assertEqual(delete.call_count, 1)
        self.assertEqual(len(delete.call_args[0]), 1)
        self.assertEqual(delete.call_args[0][0], self.entity.path())
        self.assertEqual(
            delete.call_args[1],
            # pylint:disable=protected-access
            self.entity._server_config.get_client_kwargs(),
        )

    def test_delete_v1(self):
        """What happens if the server returns an error HTTP status code?"""
        response = mock.Mock()
        response.raise_for_status.side_effect = HTTPError('oh no!')
        with mock.patch.object(
            entity_mixins.EntityDeleteMixin,
            'delete_raw',
            return_value=response,
        ):
            with self.assertRaises(HTTPError):
                self.entity.delete()

    def test_delete_v2(self):
        """What happens if the server returns an HTTP ACCEPTED status code?"""
        response = mock.Mock()
        response.status_code = http_client.ACCEPTED
        response.json.return_value = {'id': gen_integer()}
        with mock.patch.object(
            entity_mixins.EntityDeleteMixin,
            'delete_raw',
            return_value=response,
        ) as delete_raw:
            with mock.patch.object(entity_mixins, '_poll_task') as poll_task:
                self.entity.delete()
        self.assertEqual(delete_raw.call_count, 1)
        self.assertEqual(poll_task.call_count, 1)
        self.assertEqual(
            poll_task.call_args[0],  # a tuple of (positional, keyword) args
            # pylint:disable=protected-access
            (response.json.return_value['id'], self.entity._server_config)
        )

    def test_delete_v3(self):
        """What happens if the server returns an HTTP NO_CONTENT status?"""
        response = mock.Mock()
        response.status_code = http_client.NO_CONTENT
        with mock.patch.object(
            entity_mixins.EntityDeleteMixin,
            'delete_raw',
            return_value=response,
        ):
            with mock.patch.object(entity_mixins, '_poll_task') as poll_task:
                self.assertEqual(self.entity.delete(), None)
        self.assertEqual(poll_task.call_count, 0)

    def test_delete_v4(self):
        """What happens if the server returns some other stuccess status?"""
        response = mock.Mock()
        response.json.return_value = gen_integer()
        with mock.patch.object(
            entity_mixins.EntityDeleteMixin,
            'delete_raw',
            return_value=response,
        ):
            self.assertEqual(self.entity.delete(), response.json.return_value)


class EntitySearchMixinTestCase(TestCase):
    """Tests for :class:`nailgun.entity_mixins.EntitySearchMixin`."""

    def setUp(self):
        """Set ``self.cfg`` and ``self.entity``."""
        self.cfg = config.ServerConfig('example.com')
        self.entity = EntityWithSearch(self.cfg)

    def test_search_payload_v1(self):
        """Call ``search_payload``. Generate an empty query."""
        for kwargs in (
                {'fields': set()},
                {'query': {}, 'fields': set()},
                {'query': {}},
                {},
        ):
            with self.subTest(kwargs):
                self.assertEqual(self.entity.search_payload(**kwargs), {})

    def test_search_payload_v2(self):
        """Call ``search_payload``. Pass in a query."""
        query = {'foo': 'bar'}
        self.assertEqual(self.entity.search_payload([], query), query)

    def test_search_payload_v3(self):
        """Call ``search_payload``. Include a variety of fields in a search."""
        inputs_outputs = (
            ({'id': 1}, {'id': 1}),
            ({'one': 2}, {'one_id': 2}),
            ({'many': [3, 4]}, {'many_ids': [3, 4]}),
        )
        entity = EntityWithSearch2(self.cfg, id=1, one=2, many=[3, 4])

        # Implicitly and explicitly select one field for the payload.
        for input_, output in inputs_outputs:
            self.assertEqual(
                EntityWithSearch2(self.cfg, **input_).search_payload(),
                output,
            )
        for input_, output in inputs_outputs:
            self.assertEqual(
                entity.search_payload(set(input_.keys())),
                output,
            )

        # Implicitly and explicitly include all fields in the payload.
        self.assertEqual(
            entity.search_payload(),
            {'id': 1, 'one_id': 2, 'many_ids': [3, 4]},
        )
        self.assertEqual(
            entity.search_payload({'id', 'one', 'many'}),
            {'id': 1, 'one_id': 2, 'many_ids': [3, 4]},
        )

    def test_search_raw(self):
        """Call :meth:`nailgun.entity_mixins.EntitySearchMixin.search_raw`."""
        with mock.patch.object(self.entity, 'search_payload') as s_payload:
            with mock.patch.object(client, 'get') as get:
                self.entity.search_raw()
        self.assertEqual(s_payload.call_count, 1)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(len(get.call_args[0]), 1)  # path='…'
        self.assertEqual(get.call_args[0][0], self.entity.path())
        self.assertEqual(get.call_args[1]['data'], s_payload.return_value)

    def test_search_json(self):
        """Call :meth:`nailgun.entity_mixins.EntitySearchMixin.search_json`."""
        response = mock.Mock()
        response.json.return_value = gen_integer()
        with mock.patch.object(self.entity, 'search_raw') as search_raw:
            search_raw.return_value = response
            self.entity.search_json()
        self.assertEqual(search_raw.call_count, 1)
        self.assertEqual(response.raise_for_status.call_count, 1)
        self.assertEqual(response.json.call_count, 1)

    def test_search_normalize_v1(self):
        """Call ``search_normalize``.

        Pretend the server returns values for all fields, and an extra value.

        """
        with mock.patch.object(entity_mixins, '_get_entity_ids') as get_ids:
            with mock.patch.object(entity_mixins, '_get_entity_id') as get_id:
                attrs_list = EntityWithSearch2(self.cfg).search_normalize([{
                    'extra': 'foo',  # simulate extra value returned by server
                    'id': 'bar',
                    'many_ids': [gen_integer()],
                    'one_id': gen_integer(),
                }])
        self.assertEqual(get_ids.call_count, 1)
        self.assertEqual(get_id.call_count, 1)
        self.assertEqual(len(attrs_list), 1)
        self.assertEqual(
            attrs_list[0],
            {
                'id': 'bar',
                'many': get_ids.return_value,
                'one': get_id.return_value,
            }
        )

    def test_search_normalize_v2(self):
        """Call ``search_normalize``.

        Pretend the server returns no values for any fields.

        """
        attrs_list = EntityWithSearch2(self.cfg).search_normalize([{}])
        self.assertEqual(len(attrs_list), 1)
        self.assertEqual(attrs_list[0], {})

    def test_search_v1(self):
        """Test :meth:`nailgun.entity_mixins.EntitySearchMixin.search`.

        Pass no arguments.

        """
        with mock.patch.object(self.entity, 'search_normalize') as s_normalize:
            with mock.patch.object(self.entity, 'search_filter') as s_filter:
                with mock.patch.object(self.entity, 'search_json') as s_json:
                    results = self.entity.search()
        self.assertEqual(s_json.call_count, 1)
        self.assertEqual(s_normalize.call_count, 1)
        self.assertEqual(s_filter.call_count, 0)
        self.assertEqual(results, [])

    def test_search_v2(self):
        """Test :meth:`nailgun.entity_mixins.EntitySearchMixin.search`.

        Provide each possible argument.

        """
        with mock.patch.object(self.entity, 'search_normalize') as s_normalize:
            with mock.patch.object(self.entity, 'search_filter') as s_filter:
                with mock.patch.object(self.entity, 'search_json') as s_json:
                    s_normalize.return_value = [{'id': 'foo'}]
                    s_filter.return_value = [gen_integer()]  # not realistic
                    results = self.entity.search('fields', 'query', 'filters')
        self.assertEqual(s_json.call_count, 1)
        self.assertEqual(s_normalize.call_count, 1)
        self.assertEqual(s_filter.call_count, 1)
        self.assertEqual(results, s_filter.return_value)

        # Check search_json
        self.assertEqual(len(s_json.call_args[0]), 2)  # fields, query
        self.assertEqual(len(s_json.call_args[1]), 0)
        self.assertEqual(s_json.call_args[0][0], 'fields')
        self.assertEqual(s_json.call_args[0][1], 'query')

        # Check search_normalize
        self.assertEqual(len(s_normalize.call_args[0]), 1)  # results
        self.assertEqual(len(s_normalize.call_args[1]), 0)
        self.assertEqual(
            s_normalize.call_args[0][0],
            s_json.return_value['results'],
        )

        # Check search_filter
        self.assertEqual(len(s_filter.call_args[0]), 2)  # entities, filters
        self.assertEqual(len(s_filter.call_args[1]), 0)
        self.assertEqual(len(s_filter.call_args[0][0]), 1)
        self.assertEqual(s_filter.call_args[0][0][0].id, 'foo')  # from mock ↑
        self.assertEqual(s_filter.call_args[0][1], 'filters')

    def test_search_filter_v1(self):
        """Test :meth:`nailgun.entity_mixins.EntitySearchMixin.search_filter`.

        Pass a zero-length list of entities.

        """
        self.assertEqual(
            [],
            entity_mixins.EntitySearchMixin.search_filter([], {}),
        )

    def test_search_filter_v2(self):
        """Test :meth:`nailgun.entity_mixins.EntitySearchMixin.search_filter`.

        Try to filter on a foreign key field.

        """
        for filter_ in ({'one': 'foo'}, {'many': 'bar'}):
            with self.subTest(filter_):
                with self.assertRaises(NotImplementedError):
                    entity_mixins.EntitySearchMixin.search_filter(
                        [EntityWithSearch2(self.cfg)],
                        filter_,
                    )

    def test_search_filter_v3(self):
        """Test :meth:`nailgun.entity_mixins.EntitySearchMixin.search_filter`.

        Pass an invalid filter.

        """
        with self.assertRaises(entity_mixins.NoSuchFieldError):
            entity_mixins.EntitySearchMixin.search_filter(
                [EntityWithSearch2(self.cfg)],
                {'field name': 'field value'},
            )

    def test_search_filter_v4(self):
        """Test :meth:`nailgun.entity_mixins.EntitySearchMixin.search_filter`.

        Pass in valid entities and filters.

        """

        class EntityWithSearch3(
                EntityWithSearch, entity_mixins.EntityReadMixin):
            """An entity inheriting from the search and read mixins."""

        with mock.patch.object(EntityWithSearch3, 'read') as read:
            read.return_value = EntityWithSearch3(self.cfg, id=15)
            results = entity_mixins.EntitySearchMixin.search_filter(
                [EntityWithSearch3(self.cfg)],
                {'id': 15},
            )
        self.assertEqual(read.call_count, 1)
        self.assertEqual(results, [read.return_value])
