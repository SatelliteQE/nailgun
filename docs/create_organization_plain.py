#!/usr/bin/env python3
"""Create an organization, print out its attributes and delete it.

Use Requests and standard library modules to accomplish this task.

"""
import json
from pprint import pprint

import requests


def main():
    """Create an organization, print out its attributes and delete it."""
    auth = ('admin', 'changeme')
    base_url = 'https://sat1.example.com'
    organization_name = 'junk org'
    args = {'auth': auth, 'headers': {'content-type': 'application/json'}}

    response = requests.post(
        f'{base_url}/katello/api/v2/organizations',
        json.dumps(
            {
                'name': organization_name,
                'organization': {'name': organization_name},
            }
        ),
        **args,
    )
    response.raise_for_status()
    pprint(response.json())
    response = requests.delete(
        f"{base_url}/katello/api/v2/organizations/{response.json()['id']}", **args
    )
    response.raise_for_status()


if __name__ == '__main__':
    main()
