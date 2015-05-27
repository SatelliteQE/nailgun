"""Sphinx documentation generator configuration file.

The full set of configuration options is listed on the Sphinx website:
http://sphinx-doc.org/config.html

"""
import sys
import os
# pylint:disable=invalid-name


# Add the NailGun root directory to the system path. This allows references
# such as :mod:`nailgun.client` to be processed correctly.
sys.path.insert(
    0,
    os.path.abspath(os.path.join(
        os.path.dirname(__file__),
        os.path.pardir
    ))
)

# Project Information ---------------------------------------------------------

project = 'NailGun'
copyright = '2014, Jeremy Audet'  # pylint:disable=redefined-builtin
version = '0.15.1'
release = version

# General Configuration -------------------------------------------------------

extensions = [
    'sphinx.ext.autodoc',
]
source_suffix = '.rst'
master_doc = 'index'
exclude_patterns = ['_build']
nitpicky = True
autodoc_default_flags = ['members']

# Format-Specific Options -----------------------------------------------------

htmlhelp_basename = 'NailGundoc'
latex_documents = [(
    master_doc,
    project + '.tex',
    project + ' Documentation',
    'Jeremy Audet',
    'manual'
)]
man_pages = [(
    master_doc,
    project.lower(),
    project + ' Documentation',
    ['Jeremy Audet'],
    1  # man pages section
)]
texinfo_documents = [(
    master_doc,
    project,
    project + ' Documentation',
    'Jeremy Audet',
    project,
    ('NailGun is a GPL-licensed Python library that facilitates easy usage of '
     'the Satellite 6 API.'),
    'Miscellaneous'
)]
