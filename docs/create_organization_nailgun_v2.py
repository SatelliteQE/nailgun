#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Create an organization, print out its attributes and delete it."""
from nailgun.entities import Organization
from pprint import pprint


def main():
    """Create an organization, print out its attributes and delete it."""
    org = Organization(name='junk org').create()
    pprint(org.get_values())  # e.g. {'name': 'junk org', …}
    org.delete()


if __name__ == '__main__':
    main()
