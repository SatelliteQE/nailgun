#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Create an organization, print out its attributes and delete it."""
from nailgun.entities import Organization
from pprint import PrettyPrinter


def main():
    """Create an organization, print out its attributes and delete it."""
    org = Organization(name='junk org').create()
    PrettyPrinter().pprint(org.get_values())
    org.delete()


if __name__ == '__main__':
    main()
