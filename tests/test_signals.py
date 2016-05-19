# coding: utf-8
"""Tests for :mod:`nailgun.signals`."""
# pylint: disable-all
from sys import version_info
from mock import patch
from nailgun import entities, config, signals, client

if version_info < (3, 4):
    from unittest2 import TestCase
else:
    from unittest import TestCase

ORG_DATA = {'id': 1, 'domain': 'http://example.com'}


class FakeResponse(object):
    """Faking here cause we only need to test signals"""
    status_code = 200

    def __init__(self, data=None):
        self.data = data or ORG_DATA

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class Organization(entities.Organization):
    """Faking Organization as example to ensure nothing will be performed
    except the signals"""

    def read(self, *args, **kwargs):
        return self

    def create_json(self, create_missing=None):
        return self.__dict__

    def update_json(self, fields=None):
        pass

    def delete_raw(self):
        return FakeResponse()

    def _get_entity_ids(self):
        return {}

    def search_json(self, fields=None, query=None):
        return {"results": [ORG_DATA]}

    def search_normalize(self, results):
        return [ORG_DATA]

    @staticmethod
    def search_filter(entities, filters):
        return entities


cfg = config.ServerConfig(ORG_DATA['domain'])
org = Organization(cfg, **ORG_DATA)


@patch('nailgun.entities.Organization.read', return_value=org)
@patch('nailgun.client.get', return_value=FakeResponse())
class SignalsTestCase(TestCase):
    """This test case tests only if all signals are emitted
    and if the arguments were passed and catch by connected listeners
    """

    def test_patching(self, client_get, organization_read):
        '''Make sure patching works'''
        self.assertIsInstance(client.get('http://example.com'), FakeResponse)
        self.assertEqual(entities.Organization(cfg).read(), org)

    def test_pre_create_signal(self, client_get, Organization_read):
        self.assertIsNone(getattr(org, 'pre_create_emitted', None))

        @signals.pre_create.connect
        def pre_create(sender, create_missing):
            sender.pre_create_emitted = True

        org.create()
        self.assertTrue(org.pre_create_emitted)

    def test_post_create_signal(self, client_get, Organization_read):
        self.assertIsNone(getattr(org, 'post_create_emitted', None))

        @signals.post_create.connect
        def post_create(sender, entity):
            entity.post_create_emitted = True

        org.create()
        self.assertTrue(org.post_create_emitted)

    def test_pre_update_signal(self, client_get, Organization_read):
        self.assertIsNone(getattr(org, 'pre_update_emitted', None))

        @signals.pre_update.connect
        def pre_update(sender, fields):
            sender.pre_update_emitted = True

        org.update()
        self.assertTrue(org.pre_update_emitted)

    def test_post_update_signal(self, client_get, Organization_read):
        self.assertIsNone(getattr(org, 'post_update_emitted', None))

        @signals.post_update.connect
        def post_update(sender, entity, fields):
            entity.post_update_emitted = True

        org.update()
        self.assertTrue(org.post_update_emitted)

    def test_pre_delete_signal(self, client_get, Organization_read):
        self.assertIsNone(getattr(org, 'pre_delete_emitted', None))

        @signals.pre_delete.connect
        def pre_delete(sender, synchronous):
            sender.pre_delete_emitted = True

        org.delete()
        self.assertTrue(org.pre_delete_emitted)

    def test_post_delete_signal(self, client_get, Organization_read):
        self.assertIsNone(getattr(org, 'post_delete_emitted', None))

        @signals.post_delete.connect
        def post_delete(sender, synchronous, result):
            sender.post_delete_emitted = True

        deletion_result = org.delete()
        self.assertTrue(org.post_delete_emitted)
        self.assertEqual(deletion_result, ORG_DATA)

    def test_pre_search_signal(self, client_get, Organization_read):
        self.assertIsNone(getattr(org, 'pre_search_emitted', None))

        @signals.pre_search.connect
        def pre_search(sender, fields, query, filters):
            sender.pre_search_emitted = True

        org.search()
        self.assertTrue(org.pre_search_emitted)

    def test_post_search_signal(self, client_get, Organization_read):
        self.assertIsNone(getattr(org, 'post_search_emitted', None))

        @signals.post_search.connect
        def post_search(sender, entities, fields, query, filters):
            sender.post_search_emitted = True

        org.search()
        self.assertTrue(org.post_search_emitted)
