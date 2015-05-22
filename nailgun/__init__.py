# -*- coding: utf-8 -*-
"""The root of the NailGun namespace.

NailGun's modules are organized in to a tree of dependencies, where each module
only knows about the modules below it in the tree and no module knows about
others at the same level in the tree. The modules can be visualized like this::

    nailgun.entities
    └── nailgun.entity_mixins
        ├── nailgun.entity_fields
        ├── nailgun.config
        └── nailgun.client

If this is your first time working with NailGun, please read several of the
:doc:`/examples` before the documentation here.

"""
from logging import basicConfig


basicConfig()
