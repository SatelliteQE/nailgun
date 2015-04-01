#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Create an identical user account on a pair of satellites."""
from __future__ import print_function
from nailgun import client
from nailgun.config import ServerConfig
from pprint import PrettyPrinter
from robottelo import entities  # pylint:disable=import-error


def main():
    """Create an identical user account on a pair of satellites."""
    server_configs = (
        ServerConfig(url=url, auth=('admin', 'changeme'), verify=False)
        for url
        in ('https://sat1.example.com', 'https://sat2.example.com')
    )
    for server_config in server_configs:
        # The LDAP authentication source with an ID of 1 is internal. It is
        # nearly guaranteed to exist and be functioning.
        PrettyPrinter().pprint(entities.User(
            server_config,
            auth_source=1,  # or: entities.AuthSourceLDAP(server_config, id=1),
            login='Alice',
            mail='alice@example.com',
            organization=[
                get_organization(server_config, 'Default_Organization')
            ],
            password='hackme',
        ).create_json())  # create_json returns a dict of attributes


def get_organization(server_config, label):
    """Return the organization object with label ``label``.

    This function is necessary because NailGun does not yet have a mixin
    facilitating entity searches.

    :param nailgun.config.ServerConfig server_config: This object defines which
        server will be searched, what credentials will be used when searching
        and so on.
    :param label: A string label that will be used when searching. Every
        organization should have a unique label.
    :returns: An ``Organization`` object.

    """
    response = client.get(
        entities.Organization(server_config).path(),
        auth=server_config.auth,
        data={'search': 'label={}'.format(label)},
        verify=server_config.verify,
    )
    response.raise_for_status()
    decoded = response.json()
    if decoded['subtotal'] != 1:
        print(
            'Expected to find one organization, but instead found {0}. Search '
            'results: {1}'.format(decoded['subtotal'], decoded['results'])
        )
        exit(1)
    return entities.Organization(
        server_config,
        id=decoded['results'][0]['id']
    ).read()


if __name__ == '__main__':
    main()
