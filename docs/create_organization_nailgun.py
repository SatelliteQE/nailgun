#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Create an organization, print out its attributes and delete it.

Use NailGun to accomplish this task.

"""
from nailgun.config import ServerConfig
from nailgun.entities import Organization
from pprint import PrettyPrinter


def main():
    """Create an organization, print out its attributes and delete it."""
    server_config = ServerConfig(
        auth=('admin', 'changeme'),      # Use these credentials…
        url='https://sat1.example.com',  # …to talk to this server.
    )
    org = Organization(server_config, name='junk org').create()
    PrettyPrinter().pprint(org.get_values())
    org.delete()


if __name__ == '__main__':
    main()
