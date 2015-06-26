#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Create an organization, print out its attributes and delete it.

Use Requests and standard library modules to accomplish this task.

"""
from pprint import PrettyPrinter
import json
import requests


def main():
    """Create an organization, print out its attributes and delete it."""
    auth = ('admin', 'changeme')
    base_url = 'https://sat1.example.com'
    organization_name = 'junk org'
    args = {'auth': auth, 'headers': {'content-type': 'application/json'}}

    response = requests.post(
        base_url + '/katello/api/v2/organizations',
        json.dumps({
            'name': organization_name,
            'organization': {'name': organization_name},
        }),
        **args
    )
    response.raise_for_status()
    PrettyPrinter().pprint(response.json())
    response = requests.delete(
        '{0}/katello/api/v2/organizations/{1}'.format(
            base_url,
            response.json()['id'],
        ),
        **args
    )
    response.raise_for_status()


if __name__ == '__main__':
    main()
