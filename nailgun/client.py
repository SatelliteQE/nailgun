"""Wrappers for methods in the `Requests`_ module.

The functions in this module wrap `functions from`_ the `Requests`_ module.
Each function is modified with the following behaviours:

1. It sets the 'content-type' header to 'application/json', so long as no
   content-type is already set.
2. It encodes its ``data`` argument as JSON (using the ``json`` module) if the
   'content-type' header is 'application/json'.
3. It logs information about the request before it is sent.
4. It logs information about the response when it is received.

.. _Requests: http://docs.python-requests.org/en/latest/
.. _functions from:
    http://docs.python-requests.org/en/latest/api/#main-interface

"""
from json import dumps
import logging
import requests


logger = logging.getLogger(__name__)  # pylint:disable=invalid-name


def _content_type_is_json(kwargs):
    """Check whether the content-type in ``kwargs`` is 'application/json'.

    :param kwargs: A ``dict``. The keyword args supplied to :func:`request` or
        one of the convenience functions like it.
    :returns: ``True`` or ``False``

    """
    if 'headers' in kwargs and 'content-type' in kwargs['headers']:
        return kwargs['headers']['content-type'].lower() == 'application/json'
    else:
        return False


def _set_content_type(kwargs):
    """If the 'content-type' header is unset, set it to 'applcation/json'.

    The 'content-type' will not be set if doing a file upload as requests will
    automatically set it.

    :param kwargs: A ``dict``. The keyword args supplied to :func:`request` or
        one of the convenience functions like it.
    :return: Nothing. ``kwargs`` is modified in-place.

    """
    if 'files' in kwargs:
        return  # requests will automatically set content-type

    headers = kwargs.pop('headers', {})
    headers.setdefault('content-type', 'application/json')
    kwargs['headers'] = headers


def _log_request(method, url, kwargs, data=None):
    """Log out information about the arguments given.

    The arguments provided to this function correspond to the arguments that
    one can pass to ``requests.request``.

    :return: Nothing is returned.

    """
    logger.debug(
        'Making HTTP %s request to %s with %s and %s.',
        method,
        url,
        'options {0}'.format(kwargs) if len(kwargs) > 0 else 'no options',
        'data {0}'.format(data) if data is not None else 'no data',
    )


def _log_response(response):
    """Log out information about a ``Request`` object.

    After calling ``requests.request`` or one of its convenience methods, the
    object returned can be passed to this method. If done, information about
    the object returned is logged.

    :return: Nothing is returned.

    """
    message = u'Received HTTP {0} response: {1}'.format(
        response.status_code,
        response.text
    )
    if response.status_code >= 400:
        logger.warn(message)
    else:
        logger.debug(message)


def request(method, url, **kwargs):
    """A wrapper for ``requests.request``."""
    _set_content_type(kwargs)
    if _content_type_is_json(kwargs) and kwargs.get('data') is not None:
        kwargs['data'] = dumps(kwargs['data'])
    _log_request(method, url, kwargs)
    response = requests.request(method, url, **kwargs)
    _log_response(response)
    return response


def head(url, **kwargs):
    """A wrapper for ``requests.head``."""
    _set_content_type(kwargs)
    if _content_type_is_json(kwargs) and kwargs.get('data') is not None:
        kwargs['data'] = dumps(kwargs['data'])
    _log_request('HEAD', url, kwargs)
    response = requests.head(url, **kwargs)
    _log_response(response)
    return response


def get(url, **kwargs):
    """A wrapper for ``requests.get``."""
    _set_content_type(kwargs)
    if _content_type_is_json(kwargs) and kwargs.get('data') is not None:
        kwargs['data'] = dumps(kwargs['data'])
    _log_request('GET', url, kwargs)
    response = requests.get(url, **kwargs)
    _log_response(response)
    return response


def post(url, data=None, json=None, **kwargs):
    """A wrapper for ``requests.post``."""
    _set_content_type(kwargs)
    if _content_type_is_json(kwargs) and data is not None:
        data = dumps(data)
    _log_request('POST', url, kwargs, data)
    response = requests.post(url, data, json, **kwargs)
    _log_response(response)
    return response


def put(url, data=None, **kwargs):
    """A wrapper for ``requests.put``. Sends a PUT request."""
    _set_content_type(kwargs)
    if _content_type_is_json(kwargs) and data is not None:
        data = dumps(data)
    _log_request('PUT', url, kwargs, data)
    response = requests.put(url, data, **kwargs)
    _log_response(response)
    return response


def patch(url, data=None, **kwargs):
    """A wrapper for ``requests.patch``. Sends a PATCH request."""
    _set_content_type(kwargs)
    if _content_type_is_json(kwargs) and data is not None:
        data = dumps(data)
    _log_request('PATCH', url, kwargs, data)
    response = requests.patch(url, data, **kwargs)
    _log_response(response)
    return response


def delete(url, **kwargs):
    """A wrapper for ``requests.delete``. Sends a DELETE request."""
    _set_content_type(kwargs)
    if _content_type_is_json(kwargs) and kwargs.get('data') is not None:
        kwargs['data'] = dumps(kwargs['data'])
    _log_request('DELETE', url, kwargs)
    response = requests.delete(url, **kwargs)
    _log_response(response)
    return response
