# -*- coding: utf-8 -*-
"""Unit tests for :mod:`nailgun.client`."""
from fauxfactory import gen_alpha
from nailgun import client
from unittest import TestCase
import inspect
import mock
import requests

from sys import version_info
if version_info[0] == 2:
    # pylint:disable=no-name-in-module
    from urllib import urlencode
else:
    from urllib.parse import urlencode  # pylint:disable=E0611,F0401
# pylint:disable=protected-access,too-many-public-methods


class ContentTypeIsJsonTestCase(TestCase):
    """Tests for function ``_content_type_is_json``."""

    def test_true(self):
        """Assert ``True`` is returned when content-type is JSON."""
        for kwargs in (
                {'headers': {'content-type': 'application/json'}},
                {'headers': {'content-type': 'appLICatiON/JSoN'}},
                {'headers': {'content-type': 'APPLICATION/JSON'}}):
            self.assertTrue(client._content_type_is_json(kwargs))

    def test_false(self):
        """Assert ``True`` is returned when content-type is not JSON."""
        for kwargs in (
                {'headers': {'content-type': ''}},
                {'headers': {'content-type': 'application-json'}},
                {'headers': {'content-type': 'application/pson'}}):
            self.assertFalse(client._content_type_is_json(kwargs))


class SetContentTypeTestCase(TestCase):
    """Tests for function ``_set_content_type``."""

    def test_no_value(self):
        """Assert that a content-type is provided if none is set."""
        kwargs = {'headers': {}}
        client._set_content_type(kwargs)
        self.assertEqual(
            kwargs,
            {'headers': {'content-type': 'application/json'}},
        )

    def test_existing_value(self):
        """Assert that an existing content-type is not overridden."""
        kwargs = {'headers': {'content-type': ''}}
        client._set_content_type(kwargs)
        self.assertEqual(kwargs, {'headers': {'content-type': ''}})


class CurlArgUserTestCase(TestCase):
    """Tests for function ``_curl_arg_user``."""

    def test_null(self):
        """Do not provide any authentication information."""
        self.assertEqual(client._curl_arg_user({}), '')

    def test_non_null(self):
        """Provide authentication information."""
        self.assertEqual(
            client._curl_arg_user({
                'auth': ('alice', 'hackme')
            }),
            '--user alice:hackme ',  # there should be trailing whitespace
        )


class CurlArgInsecureTestCase(TestCase):
    """Tests for function ``_curl_arg_insecure``."""

    def test_null(self):
        """Do not specify whether SSL connections should be verified."""
        self.assertEqual(client._curl_arg_insecure({}), '')

    def test_positive(self):
        """Ask for SSL connections to be verified."""
        self.assertEqual(
            client._curl_arg_insecure({'verify': True}),
            '',
        )

    def test_negative(self):
        """Ask for SSL connections to not be verified."""
        self.assertEqual(
            client._curl_arg_insecure({'verify': False}),
            '--insecure ',  # there should be trailing whitespace
        )


class CurlArgDataTestCase(TestCase):
    """Tests for function ``_curl_arg_data``."""

    def setUp(self):
        """Provide test data for use by other methods in this class.

        Dictionary ordering is not guaranteed. It follows that
        ``urlencode({…})`` is only guaranteed if ``{…}`` has a single item. To
        deal with this issue, two separate encodable dicts are provided, rather
        than a single large encodable dict with multiple items.

        """
        self.to_encode = ({'bar': '!@#$% ^&*()'}, {'foo': 9001})
        self.to_ignore = {'auth': ('alice', 'password'), 'verify': True}

    def test_null(self):
        """Provide no URL parameters."""
        self.assertEqual(urlencode({}), client._curl_arg_data({}))

    def test_ignored_opts(self):
        """Provide URL parameters which should not be encoded."""
        self.assertEqual(urlencode({}), client._curl_arg_data(self.to_ignore))

    def test_valid_opts(self):
        """Provide URL parameters which should be encoded."""
        for params in self.to_encode:
            self.assertEqual(urlencode(params), client._curl_arg_data(params))

    def test_both_opts(self):
        """Provide data which should be ignored and which should be encoded."""
        for target in self.to_encode:
            source = target.copy()
            source.update(self.to_ignore)
            self.assertEqual(urlencode(target), client._curl_arg_data(source))


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
                if meth in ('delete', 'get', 'head'):
                    requests_meth.assert_called_once_with(
                        self.bogus_url,
                        headers={'content-type': 'application/json'}
                    )
                elif meth in ('patch', 'put'):
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
