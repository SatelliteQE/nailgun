# -*- coding: utf-8 -*-
"""Defines a set of named signals for entities operations"""
# pylint: disable-all

import blinker_herald

emit = blinker_herald.emit
SENDER_CLASS = blinker_herald.SENDER_CLASS
SIGNALS_AVAILABLE = blinker_herald.SIGNALS_AVAILABLE

pre_create = blinker_herald.signals_namespace.signal('pre_create')
post_create = blinker_herald.signals_namespace.signal('post_create')

pre_update = blinker_herald.signals_namespace.signal('pre_update')
post_update = blinker_herald.signals_namespace.signal('post_update')

pre_delete = blinker_herald.signals_namespace.signal('pre_delete')
post_delete = blinker_herald.signals_namespace.signal('post_delete')

pre_search = blinker_herald.signals_namespace.signal('pre_search')
post_search = blinker_herald.signals_namespace.signal('post_search')
