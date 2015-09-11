#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Create an identical user account on a pair of satellites."""
from __future__ import print_function
from nailgun.config import ServerConfig
from nailgun.entities import Organization, User
from pprint import pprint


def main():
    """Create an identical user account on a pair of satellites."""
    server_configs = ServerConfig.get('sat1'), ServerConfig.get('sat2')
    for server_config in server_configs:
        org = Organization(server_config).search(
            query={'search': 'name="Default_Organization"'}
        )[0]
        # The LDAP authentication source with an ID of 1 is internal. It is
        # nearly guaranteed to exist and be functioning.
        user = User(
            server_config,
            auth_source=1,  # or: AuthSourceLDAP(server_config, id=1),
            login='Alice',
            mail='alice@example.com',
            organization=[org],
            password='hackme',
        ).create()
        pprint(user.get_values())  # e.g. {'login': 'Alice', …}


if __name__ == '__main__':
    main()
