#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Discover which environments belong to several named organizations.

This script talks to the server listed in ``BASE_URL``. ``BASE_URL`` should
*not* have a trailing slash. In other words, ".com" is good, but ".com/" is
bad.

"""
import json
import pprint
import requests


BASE_URL = 'https://example.com'
ORG_NAMES = ('TestOrg1', 'TestOrg2')


def main():
    """Search for organizations, then print out the environments in each.

    Organizations are searched for by name. Exit if more or less than one
    organization is returned when searching for a given organization name.

    """
    # Get the IDs of several organizations.
    organizations = {}  # ID → name
    for org_name in ORG_NAMES:
        response = requests.get(
            BASE_URL + '/katello/api/v2/organizations',
            data=json.dumps({'search': 'name={}'.format(org_name)}),
            auth=('admin', 'changeme'),
            headers={'content-type': 'application/json'},
            verify=False,
        )
        response.raise_for_status()
        results = response.json()['results']
        if len(results) != 1:
            print(
                'Expected to find one organization, but instead found {0}'
                .format(results)
            )
            exit(1)
        organizations[results[0]['id']] = org_name

    # Discover which environments belong to those organizations.
    for org_id, org_name in organizations.items():
        response = requests.get(
            BASE_URL + '/katello/api/v2/environments',
            data=json.dumps({'organization_id': org_id}),
            auth=('admin', 'changeme'),
            headers={'content-type': 'application/json'},
            verify=False,
        )
        response.raise_for_status()
        results = response.json()['results']
        print(
            'There are {} environments in organization {} (ID {}): '
            .format(len(results), org_name, org_id)
        )
        pprint.PrettyPrinter(indent=4).pprint(results)
        print()


if __name__ == '__main__':
    main()
