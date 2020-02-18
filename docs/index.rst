NailGun
=======

NailGun is a GPL-licensed Python library that facilitates easy usage of the
Satellite 6 API. It lets you write code like this::

    >>> org = Organization(id=1).read()

This page provides a summary of information about NailGun.

.. contents::

More in-depth coverage is provided in other sections.

.. toctree::
    :maxdepth: 1

    examples
    api/index

Quick Start
-----------

This script demonstrates how to create and delete an organization, and how to
save some of our work for later re-use::

    >>> from nailgun.config import ServerConfig
    >>> from nailgun.entities import Organization
    >>> server_config = ServerConfig(
    ...     auth=('admin', 'changeme'),      # Use these credentials…
    ...     url='https://sat1.example.com',  # …to talk to this server.
    ... )  # More options are available, e.g. disabling SSL verification.
    >>> org = Organization(server_config, name='junk org').create()
    >>> org.name == 'junk org'  # Access all attrs likewise, e.g. `org.label`
    True
    >>> org.delete()
    >>> server_config.save()  # Save to disk w/label 'default'. Read with get()

This example glosses over *many* features. The :doc:`examples` and :doc:`API
documentation </api/index>` sections provide more in-depth documentation.

Why NailGun?
------------

NailGun exists to make working with the Satellite 6 API easier. Here are some of
the challenges developers face:

* Existing libraries, such as the Python `Requests`_ library, are general
  purpose tools. As a result, client code can easily become excessively
  verbose. See the :doc:`examples` document for an example.
* The Satellite 6 API is not RESTful in its design. As a result, even
  experienced developers may find the API hard to work with.
* The Satellite 6 API is not consistent in its implementation. For example, see
  the "Payload Generation" section of `this blog post`_.

All of the above issues are compounded by the size of the Satellite 6 API. As of
this writing, there are 405 paths. This makes it tough to design compact and
elegant client code.

NailGun addresses these issues. NailGun is specialized, it has a consistent
design, it abstracts away many painful implementation details and it contains
workarounds for certain bugs. Why use a hammer when you can use a nail gun?

Scope and Limitations
---------------------

NailGun is not an officially supported product. NailGun is a Python-only
library, and integration with other languages such as Java or Ruby is not
currently a consideration. Although NailGun is developed with a broad audience
in mind, it targets `Robottelo`_ first and foremost.

NailGun was originally conceived as a set of helper routines internal to
`Robottelo`_. It has since been extracted from that code base and turned in to
an independently useful library.

.. WARNING:: Until version 1.0 is released, functionality will be incomplete,
    and breaking changes may be introduced. Users are advised to read the
    release notes closely.

Resources
---------

The :doc:`examples` and :doc:`API documentation </api/index>` sections provide
more in-depth documentation.

Join the #robottelo channel on the `freenode`_ IRC network to chat with a
human. The `Robottelo source code`_ contains many real-world examples how
NailGun is used, especially the `tests/foreman/api/
<https://github.com/SatelliteQE/robottelo/tree/master/tests/foreman/api>`_
directory. `This blog post`_ provides a glimpse in to the challenges that
NailGun is designed to overcome.

Contributing
------------

Contributions are encouraged. The easiest way to contribute is to submit a pull
request on GitHub, but patches are welcome no matter how they arrive.

You can use pip and make to quickly set up a development environment::

    pip install -r requirements.txt -r requirements-dev.txt
    pre-commit install-hooks
    make test
    make docs-html

Please adhere to the following guidelines:

* All PR’s should follow the predetermined pull request template and explain the problem that is addressed. Issues should follow template and explain what the problem is.
* Maintain Coding Standards
    * Keep pep8 rules
    * Follow the same stylistic and logical patterns used in the code
        * All entity class names and class attributes have to be in the singular format
        * All required entity attributes have to have `required=True` parameter
        * It is preferable to use `alpha` data type for default string values for easier debug procedure
        * In case any workaround is introduced, it is necessary to provide corresponding BZ ID directly into the code docstring
        * All linting (flake8) and formatting/style checks would be enforced by Travis-CI and PR would be considered broken until checks are passed successfully.
        * Use of pre-commit configuration included with repo will ensure style compliance locally before commit, helping reduce travis failures.
* Adhere to typical commit guidelines:
    * Commits should not cause NailGun’s unit test to fail. If it does, it will the responsibility of contributor to review those failures and fix them in the same PR's or raise another. The tracking of failures would be responsibility of contributor.
    * Commits should be small and coherent. One commit should address one issue.
    * Commits should have `good commit messages`_.
    * `Rebasing`_ is encouraged. Rebasing produces a much nicer commit history
      than merging.
* To make the review process easy for all reviewers and anyone else interested in the new functionality, please provide some output making use of your changes. Having example of usage in docstring along with your code could really help others to build up on your code. You can add log from Python interactive shell or some tests results (from Robottelo / Foreman Ansible Modules) in PR message, or you can do something completely different - as long as it runs your code, it's fine!
* If PR is applicable for many branches (e.g. master and one of '6.X.z' branches), specify that information in PR message
* Unit tests
    * Unit tests are compulsory
    * Unit tests should cover all available actions, for the entity. For eg: Repository Sets, have enable, disable, list_available there should be unit tests exercising these actions.
* When in doubt, ask on IRC. Join #robottelo on `freenode`_

**Important to Note :**

* Define Foreman Version labels in Nailgun
    if possible, the contributor should set the right version.

* All PRs should be raised along with Unit tests
    The unit tests should be added while adding a new entity or modifying the existing entity or modifying and adding to the core of Nailgun.

* Test results from upstream devel or from upstream nightly
    The API call results are required from PR author to make the review process more firm. Author can provide results from any library that uses the contributed code by running the changes on upstream nightly or from his/her devel box. The interactive python shell output would be acceptable as well.

Nailgun Review Process
______________________

* Travis CI is run, and any issues are resolved by contributor.
* If deemed necessary by contributors/reviewers, an automation run is triggered.
* At least two ACKs are required to merge a pull request.
* At least one ACK must be from a Tier 2 reviewer.
* If a PR requires changes to the CI environment, the “CI Owner” must also provide an ACK.
* Pull request can be merged only when all comments are in resolved state (Resolve conversation button is pressed)

**Reviewers & Responsibilities :**

* Both Tiers
    * Consistently check your projects for new pull requests.
    * Check code for consistency with project guidelines.
    * Pin code dependencies (external libraries), against the version it was tested.
    * Determine if CI and/or test infrastructure changes are required.
    * Provide helpful feedback.
    * Follow-up with any pending feedback, to ensure the PR is resolved quickly.
* Tier 1 Reviewer
    * Check the scenarios are valid for the feature or components
    * Suggestions on the feature that can be covered with minimal code additions/changes.
* Tier 2 Reviewer
    * Check for logical errors.
    * Guide the contributor on how to fix mistakes and any other improvements.
    * Ideally if not done by contributor, identify code that may impact third-party projects (e.g Nailgun -> Robottelo , FAM), file issues if PR causes breakages in relevant projects


Nailgun Release Process
_______________________


Projects that require nailgun, would often rely on the released Nailgun from Pypi.
We intended to make the release process more formal and standard to deliver timely and stable code base to consumer projects.

* Nailgun Releases should be performed against stable branches.
* No historical release support.
* Nailgun will follow request based minor releases.




.. _freenode: https://freenode.net/
.. _good commit messages: http://tbaggery.com/2008/04/19/a-note-about-git-commit-messages.html
.. _Rebasing: http://www.git-scm.com/book/en/v2/Git-Branching-Rebasing
.. _Requests: http://docs.python-requests.org/en/latest/
.. _Robottelo: http://robottelo.readthedocs.io/en/latest/
.. _Robottelo source code: https://github.com/SatelliteQE/robottelo
.. _this blog post: http://www.ichimonji10.name/blog/4/
