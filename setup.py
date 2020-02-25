#!/usr/bin/env python
"""A setuptools-based script for installing NailGun.

For more information, see:

* https://packaging.python.org/en/latest/index.html
* https://docs.python.org/distutils/sourcedist.html

"""
import sys

from setuptools import find_packages
from setuptools import setup


with open('README.rst') as handle:
    LONG_DESCRIPTION = handle.read()


with open('VERSION') as handle:
    VERSION = handle.read().strip()


REQUIREMENTS = [
    'inflection',
    'packaging',
    'pyxdg',
    'requests>=2.7',
    'blinker_herald'
]


if sys.version_info >= (3, 0):
    REQUIREMENTS.append('fauxfactory')
else:
    # Fauxfactory 3.0+ dropped support for Python 2.x
    REQUIREMENTS.append('fauxfactory<3.0')


setup(
    name='nailgun',
    version=VERSION,
    description='A library that facilitates easy usage of the Satellite 6 API',
    long_description=LONG_DESCRIPTION,
    url='https://github.com/SatelliteQE/nailgun',
    author='Jeremy Audet',
    author_email='ichimonji10@gmail.com',
    license='GPLv3',
    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        ('License :: OSI Approved :: GNU General Public License v3 or later '
         '(GPLv3+)'),
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
    ],
    packages=find_packages(exclude=['docs', 'tests']),
    install_requires=REQUIREMENTS,
)
