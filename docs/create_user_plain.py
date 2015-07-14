#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Create an identical user account on a pair of satellites.

If you'd like to test out this script, you can quickly set up an environment
like so::

    virtualenv env
    source env/bin/activate
    pip install requests
    ./create_user_plain.py  # copy this script to the current directory

"""
from __future__ import print_function
from pprint import pprint
import requests
import json


def main():
    """Create an identical user account on a pair of satellites."""
    server_configs = (
        {'url': url, 'auth': ('admin', 'changeme'), 'verify': False}
        for url
        in ('https://sat1.example.com', 'https://sat2.example.com')
    )
    for server_config in server_configs:
        response = requests.post(
            server_config['url'] + '/api/v2/users',
            json.dumps({
                'user': {
                    'auth_source_id': 1,
                    'login': 'Alice',
                    'mail': 'alice@example.com',
                    'organization_ids': [get_organization_id(
                        server_config,
                        'Default_Organization'
                    )],
                    'password': 'hackme',
                }
            }),
            auth=server_config['auth'],
            headers={'content-type': 'application/json'},
            verify=server_config['verify'],
        )
        response.raise_for_status()
        pprint(response.json())


def get_organization_id(server_config, label):
    """Return the ID of the organization with label ``label``.

    :param server_config: A dict of information about the server being talked
        to. The dict should include the keys "url", "auth" and "verify".
    :param label: A string label that will be used when searching. Every
        organization should have a unique label.
    :returns: An organization ID. (Typically an integer.)

    """
    response = requests.get(
        server_config['url'] + '/katello/api/v2/organizations',
        data=json.dumps({'search': 'label={}'.format(label)}),
        auth=server_config['auth'],
        headers={'content-type': 'application/json'},
        verify=server_config['verify'],
    )
    response.raise_for_status()
    decoded = response.json()
    if decoded['subtotal'] != 1:
        print(
            'Expected to find one organization, but instead found {0}. Search '
            'results: {1}'.format(decoded['subtotal'], decoded['results'])
        )
        exit(1)
    return decoded['results'][0]['id']


if __name__ == '__main__':
    main()
