Examples
========

This page contains several examples of how to use NailGun. The examples progress
from simple to more advanced.

You can run any of the scripts presented in this document. For example scripts
that use NailGun, this is the set-up procedure::

    virtualenv env
    source env/bin/activate
    pip install nailgun
    ./some_script.py  # some script of your choice

For example scripts that do not use NailGun, this is the set-up procedure::

    virtualenv env
    source env/bin/activate
    pip install requests
    ./some_script.py  # some script of your choice

Additionally, a video demonstration entitled `NailGun Hands On
<https://www.youtube.com/watch?v=_FNjAQdNoRc>`_ is available.

.. raw:: html

    <iframe
        width="560"
        height="315"
        src="https://www.youtube.com/embed/_FNjAQdNoRc"
        allowfullscreen
    ></iframe>

.. _label-simple:

Getting Started
---------------

This script demonstrates how to create an organization, print out its
attributes and delete it using NailGun:

.. literalinclude:: create_organization_nailgun.py

This script demonstrates how to do the same *without* NailGun:

.. literalinclude:: create_organization_plain.py

Managing Server Configurations
------------------------------

In the example shown above, a :class:`nailgun.config.ServerConfig` object was
created in the body of the script. However, inter-mixing configuration data and
program logic in this manner is problematic:

* Placing sensitive information in to a code-base puts that information at risk
  of becoming public, especially when the code-base is version-controlled.
* Server-specific configuration information is likely to change frequently.
  Placing that information in to a code-base means subjecting that code-base to
  unnecessary churn, making it harder for developers to find useful information
  in a repository's change log.

NailGun addresses this issue by providing full support for configuration files.
Here's a simple example of how to create a pair of configuration objects, save
them to disk, and read them back again::

    >>> from nailgun.config import ServerConfig
    >>> ServerConfig('http://sat1.example.com').save('sat1')
    >>> ServerConfig('http://sat2.example.com').save('sat2')
    >>> set(ServerConfig.get_labels()) == set(('sat1', 'sat2'))
    True
    >>> sat1_cfg = ServerConfig.get('sat1')
    >>> sat2_cfg = ServerConfig.get('sat2')

A label of "default" is used when saving or reading configuration objects if no
explicit label is given. As a result, this is valid::

    >>> from nailgun.config import ServerConfig
    >>> ServerConfig('bogus url').save()
    >>> ServerConfig.get().url == 'bogus url'
    True

The use of "default" is especially useful if you have created numerous server
configurations, but only want to work with one at a time::

    >>> from nailgun.config import ServerConfig
    >>> ServerConfig.get('sat1').save()  # same as .save(label='default')

In addition, if no server configuration object is specified when instantiating
an :class:`nailgun.entity_mixins.Entity` object, the server configuration
labeled "default" is used. With this in mind, here's a revised version of the
first script in section :ref:`label-simple`:

.. literalinclude:: create_organization_nailgun_v2.py

This works just fine in many use cases. But what if you do not want to save
your server configuration to disk? This might be the case if multiple processes
are using NailGun and each process should default to communicating with a
different default server, or if you are working with a read-only file system.
In this case, you can use :data:`nailgun.entity_mixins.DEFAULT_SERVER_CONFIG`.

NailGun handles other use cases, too. For example, the XDG base directory
specification is obeyed, meaning that you can do things like provide a
system-wide configuration file or place user configuration data in an alternate
location. Read :mod:`nailgun.config` for full details.

Using More Methods
------------------

The examples so far have only made use of a small set of classes and methods:

* The ``ServerConfig`` class and several of its methods.
* The ``Organization`` class and its ``create``, ``get_values`` and ``delete``
  methods.

However, there are several more very useful high-level methods that you should
be aware of:

* ``get_fields``
* ``read``
* ``update``


``get_fields``
~~~~~~~~~~~~~~

The ``get_fields`` method is closely related to the ``get_values`` method. The
former tells you which values *may* be assigned to an entity, and the latter
tells you what values *are* assigned to an entity. For example:

    >>> from nailgun.entities import Product
    >>> product = Product(name='junk product')
    >>> product.get_values()
    {'name': 'junk product'}
    >>> product.get_fields()
    {
        'description': <nailgun.entity_fields.StringField object at 0x7fb5bf25ee10>,
        'gpg_key': <nailgun.entity_fields.OneToOneField object at 0x7fb5bf1f1128>,
        'id': <nailgun.entity_fields.IntegerField object at 0x7fb5bd4bd748>,
        'label': <nailgun.entity_fields.StringField object at 0x7fb5bd48b7f0>,
        'name': <nailgun.entity_fields.StringField object at 0x7fb5bd48b828>,
        'organization': <nailgun.entity_fields.OneToOneField object at 0x7fb5bd498f60>,
        'sync_plan': <nailgun.entity_fields.OneToOneField object at 0x7fb5bd49eac8>,
    }

Fields serve two purposes. First, they provide typing information mixins. For
example, a server expects this JSON payload when creating a product::

    {
        "name": "junk product",
        "organization_id": 5,
        …
    }

And a server will return this JSON payload when reading a product::


    {
        "name": "junk product",
        "organization": {
            'id': 3,
            'label': 'c5f2646f-5975-48c4-b2a3-bf8398b44510',
            'name': 'junk org',
        },
        …
    }

Notice how the "organization" field is named and structured differently in the
above two cases. NailGun can deal with this irregularity due to the presence of
the ``StringField`` and ``OneToOneField``. If you are ever fiddling with an
entity's definition, be careful to use the right field types. Otherwise, you may
get some strange and hard-to-troubleshoot bugs.

Secondly, fields can generate random values for unit testing purposes. (This
does *not* normally happen!) See the ``create_missing`` method for more
information.

``read``
~~~~~~~~

Rather unsurprisingly, the ``read`` method fetches information about an entity.
Importantly, the ``read`` method does not have side-effects:

    >>> from nailgun import entities
    >>> org = entities.Organization(id=418)
    >>> response = org.read()
    >>> for obj in (org, response):
    ...     type(obj)
    ...
    <class 'nailgun.entities.Organization'>
    <class 'nailgun.entities.Organization'>
    >>> for obj in (org, response):
    ...     obj.get_values()
    ...
    {'id': 418}
    {
        'description': None,
        'id': 418,
        'label': 'junk_org',
        'name': 'junk org',
        'title': 'junk org',
    }

As demonstrated above, the ``read`` method does not alter the object it is
called on. Instead, it creates a new object, populates that object with
attributes, and returns that new object. As a result, idioms like ``org =
org.read()`` are advisable.

``update``
~~~~~~~~~~

The ``update`` method updates an entity's values. For example:

    >>> from nailgun.entities import Organization
    >>> org = Organization(id=418).read()
    >>> org.get_values()
    {
        'description': None,
        'id': 418,
        'label': 'junk_org',
        'name': 'junk org',
        'title': 'junk org',
    }
    >>> org.name = 'junkier org'
    >>> org.description = 'supercalifragilisticexpialidocious'
    >>> org = org.update()  # update all fields by default
    >>> org.get_values()
    {
        'description': 'supercalifragilisticexpialidocious',
        'id': 418,
        'label': 'junk_org',
        'name': 'junkier org',
        'title': 'junkier org',
    }
    >>> org.description = None
    >>> org = org.update(['description'])  # update only named fields
    >>> org.get_values()
    {
        'description': None,
        'id': 418,
        'label': 'junk_org',
        'name': 'junkier org',
        'title': 'junkier org',
    }

Some notes on the above:

* By default, the ``update`` method updates all fields. However, it is also
  possible to update a subset of fields.
* The ``update`` method is side-effect free. As a result, idioms like ``org =
  org.update()`` are advisable.

Using Lower Layers
------------------

This section demonstrates how to create a user account. To make things
interesting, there are some extra considerations:

* The user account must belong to the organization labeled
  "Default_Organization".
* The user account must be named "Alice" and have the password "hackme".
* The user account must be created on a pair of satellites.

Two sets of code that accomplish this task are listed. The first body of code
shows how to accomplish the task with NailGun. The second body of code does not
make use of NailGun, and instead relies entirely on `Requests`_ and standard
library modules.

.. literalinclude:: create_user_nailgun.py

The code above makes use of NailGun. The code below makes use of `Requests`_ and
standard library modules.

.. literalinclude:: create_user_plain.py

It is easy to miss the differences between the two scripts, as they are
similarly structured. However, a closer look shows that the two scripts have
significant differences in robustness. Here's some highlights.

First, both scripts pass around ``server_config`` objects, and the values that
go in to those objects are hard-coded in to the scripts. However, NailGun's
:class:`nailgun.config.ServerConfig` objects provide a ``get`` method that allow
you to read a saved configuration from disk. The sans-NailGun script has no such
facility. Thus, NailGun allows for easy information re-use.

Second, the sans-NailGun script relies entirely on convention when placing
values in to and retrieving values from the ``server_config`` objects. This is
easy to get wrong. For example, one piece of code might place a value named
``'verify_ssl'`` in to a dictionary and a second piece of code might retrieve a
value named ``'verify'``. This is a mistake, but you won't know about it until
runtime. In contrast, the ``ServerConfig`` objects have an explicit set of
possible instance attributes, and tools such as Pylint can use this information
when linting code. (Similarly, NailGun's entity objects such as ``Organization``
and ``User`` have an explicit set of possible instance attributes.) Thus,
NailGun allows for more effective static analysis.

Third, NailGun automatically checks HTTP status codes for you when you call
methods such as ``create_json``. In contrast, the sans-NailGun script requires
that the user call ``raise_for_status`` or some equivalent every time a response
is received. Thus, NailGun makes it harder for undetected errors to creep in to
code and cause trouble.

Fourth, there are several hard-coded paths present in the sans-NailGun script:
``'/katello/api/v2/organizations'`` and ``'/api/v2/users'``. This is a hassle.
Developers need to look up a path every time they write an API call, and it's
easy to make a mistake and waste time troubleshooting the resultant error.
NailGun shields the developer from this issue by providing a ``path`` method.

Fifth, the NailGun script shields developers from idiosyncrasies in JSON request
formats. Notice how no nested has is necessary when issuing a GET request for
organizations, but a nested hash is necessary when issuing a POST request for
users. Differences like this abound.

Sixth, the NailGun script will get better in the future. For example, the
``get_organization`` method will be minified or obsoleted when an
``EntitySearchMixin`` class is written and made a parent of class
``Organization``.

.. _Requests: http://docs.python-requests.org/en/latest/
.. _Robottelo: http://robottelo.readthedocs.org/en/latest/
