#!/usr/bin/env python3
"""Create an organization, print out its attributes and delete it."""
from pprint import pprint

from nailgun.entities import Organization


def main():
    """Create an organization, print out its attributes and delete it."""
    org = Organization(name='junk org').create()
    pprint(org.get_values())  # e.g. {'name': 'junk org', …}
    org.delete()


if __name__ == '__main__':
    main()
