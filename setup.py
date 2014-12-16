"""A setuptools-based script for installing NailGun."""
from setuptools import find_packages, setup  # prefer setuptools over distutils


setup(
    name='nailgun',
    version='0.0.1',
    description='A library that facilitates easy usage of the Satellite 6 API',
    url='https://github.com/SatelliteQE/nailgun',
    author='Jeremy Audet',
    author_email='ichimonji10@gmail.com',
    license='GPLv3',
    # See https://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        'Development Status :: 1 - Planning',
        'Intended Audience :: Developers',
        ('License :: OSI Approved :: GNU General Public License v3 or later '
         '(GPLv3+)'),
        'Programming Language :: Python :: 2.7',
    ],
    packages=find_packages(),
    install_requires=['requests'],
)
