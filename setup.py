"""A setuptools-based script for installing NailGun."""
from setuptools import find_packages, setup  # prefer setuptools over distutils


with open('README.rst') as handle:
    LONG_DESCRIPTION = handle.read()


setup(
    name='nailgun',
    version='0.3.0',  # Should be identical to the version in docs/conf.py!
    description='A library that facilitates easy usage of the Satellite 6 API',
    long_description=LONG_DESCRIPTION,
    url='https://github.com/SatelliteQE/nailgun',
    author='Jeremy Audet',
    author_email='ichimonji10@gmail.com',
    license='GPLv3',
    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        ('License :: OSI Approved :: GNU General Public License v3 or later '
         '(GPLv3+)'),
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
    ],
    packages=find_packages(),
    install_requires=['requests', 'pyxdg'],
)
