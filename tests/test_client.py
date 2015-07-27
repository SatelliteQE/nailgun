# -*- coding: utf-8 -*-
"""Unit tests for :mod:`nailgun.client`."""
from fauxfactory import gen_alpha
from nailgun import client
import inspect
import mock
import requests

from sys import version_info
if version_info < (3, 4):
    from unittest2 import TestCase  # pylint:disable=import-error
else:
    from unittest import TestCase


class ContentTypeIsJsonTestCase(TestCase):
    """Tests for function ``_content_type_is_json``."""

    def test_true(self):
        """Assert ``True`` is returned when content-type is JSON."""
        for kwargs in (
                {'headers': {'content-type': 'application/json'}},
                {'headers': {'content-type': 'appLICatiON/JSoN'}},
                {'headers': {'content-type': 'APPLICATION/JSON'}}):
            # pylint:disable=protected-access
            self.assertTrue(client._content_type_is_json(kwargs))

    def test_false(self):
        """Assert ``True`` is returned when content-type is not JSON."""
        for kwargs in (
                {'headers': {'content-type': ''}},
                {'headers': {'content-type': 'application-json'}},
                {'headers': {'content-type': 'application/pson'}}):
            # pylint:disable=protected-access
            self.assertFalse(client._content_type_is_json(kwargs))


class SetContentTypeTestCase(TestCase):
    """Tests for function ``_set_content_type``."""

    def test_no_value(self):
        """Assert that a content-type is provided if none is set."""
        kwargs = {'headers': {}}
        client._set_content_type(kwargs)  # pylint:disable=protected-access
        self.assertEqual(
            kwargs,
            {'headers': {'content-type': 'application/json'}},
        )

    def test_existing_value(self):
        """Assert that no content-type is provided if one is set."""
        kwargs = {'headers': {'content-type': ''}}
        client._set_content_type(kwargs)  # pylint:disable=protected-access
        self.assertEqual(kwargs, {'headers': {'content-type': ''}})

    def test_files_in_kwargs(self):
        """Assert that no content-type is provided if files are given."""
        kwargs = {'files': None}
        client._set_content_type(kwargs)  # pylint:disable=protected-access
        self.assertEqual(kwargs, {'files': None})


class ClientTestCase(TestCase):
    """Tests for functions in :mod:`nailgun.client`."""

    def setUp(self):
        self.bogus_url = gen_alpha()
        self.mock_response = mock.Mock(status_code=200)

    def test_clients(self):
        """Test all the wrappers except :func:`nailgun.client.request`.

        The following functions are tested:

        * :func:`nailgun.client.delete`
        * :func:`nailgun.client.get`
        * :func:`nailgun.client.head`
        * :func:`nailgun.client.patch`
        * :func:`nailgun.client.post`
        * :func:`nailgun.client.put`

        Assert that:

        * The wrapper function passes the correct parameters to requests.
        * The wrapper function returns whatever requests returns.

        """
        for meth in ('delete', 'get', 'head', 'patch', 'post', 'put'):
            with mock.patch.object(requests, meth) as requests_meth:
                # Does the wrapper function return whatever requests returns?
                requests_meth.return_value = self.mock_response
                self.assertIs(
                    getattr(client, meth)(self.bogus_url),
                    self.mock_response
                )

                # Did the wrapper function pass the correct params to requests?
                if meth in ('delete', 'head'):
                    requests_meth.assert_called_once_with(
                        self.bogus_url,
                        headers={'content-type': 'application/json'}
                    )
                elif meth in ('get', 'patch', 'put'):
                    requests_meth.assert_called_once_with(
                        self.bogus_url,
                        None,
                        headers={'content-type': 'application/json'}
                    )
                else:  # meth is 'post'
                    requests_meth.assert_called_once_with(
                        self.bogus_url,
                        None,
                        None,
                        headers={'content-type': 'application/json'}
                    )

    def test_client_request(self):
        """Test :func:`nailgun.client.request`.

        Make the same assertions as
        :meth:`tests.test_client.ClientTestCase.test_clients`.

        """
        with mock.patch.object(requests, 'request') as requests_request:
            requests_request.return_value = self.mock_response
            self.assertIs(
                client.request('foo', self.bogus_url),
                self.mock_response,
            )
            requests_request.assert_called_once_with(
                'foo',
                self.bogus_url,
                headers={'content-type': 'application/json'}
            )

    def test_identical_args(self):
        """Check that the wrapper functions have the correct signatures.

        For example, :func:`nailgun.client.delete` should have the same
        signature as ``requests.delete``.

        """
        for meth in ('delete', 'get', 'head', 'patch', 'post', 'put'):
            self.assertEqual(
                inspect.getargspec(getattr(client, meth)),
                inspect.getargspec(getattr(requests, meth)),
            )
