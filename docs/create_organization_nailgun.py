#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Create an organization, print out its attributes and delete it.

Use NailGun to accomplish this task.

"""
from nailgun.config import ServerConfig
from pprint import PrettyPrinter
from robottelo import entities  # pylint:disable=import-error


def main():
    """Create an organization, print out its attributes and delete it."""
    server_config = ServerConfig(
        url='https://sat1.example.com',  # Talk to this server…
        auth=('admin', 'changeme'),      # using these credentials.
    )
    attrs = entities.Organization(server_config, name='junk org').create_json()
    PrettyPrinter().pprint(attrs)  # create_json returns a dict of attributes
    entities.Organization(server_config, id=attrs['id']).delete()


if __name__ == '__main__':
    main()
