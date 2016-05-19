# -*- coding: utf-8 -*-
"""Defines a set of named signals for entities operations"""
# pylint: disable-all
__all__ = ['pre_create', 'post_create',
           'pre_delete', 'post_delete',
           'pre_update', 'post_update',
           'pre_search', 'post_search']

SIGNALS_AVAILABLE = False
try:
    from blinker import Namespace
    SIGNALS_AVAILABLE = True
except ImportError:  # pragma: no cover
    class Namespace(object):
        """A fake namespace in case of blinker is not installed"""

        def signal(self, name, doc=None):
            """A fake signal when blinker is not installed"""
            return _FakeSignal(name, doc)

    class _FakeSignal(object):
        """If blinker is unavailable, create a fake class with the same
        interface that allows sending of signals but will fail with an
        error on anything else.  Instead of doing anything on send, it
        will just ignore the arguments and do nothing instead.
        """

        def __init__(self, name, doc=None):
            self.name = name
            self.__doc__ = doc

        def _fail(self, *args, **kwargs):
            """To raise if blinker is not installed"""
            raise RuntimeError('signalling support is unavailable '
                               'because the blinker library is '
                               'not installed.')

        def send(self, *sender, **kwargs):
            """A fake send does nothing"""
            pass

        connect = disconnect = has_receivers_for = _fail
        receivers_for = temporarily_connected_to = _fail
        del _fail

# the namespace for code signals.  If you are not nailgun code, do
# not put signals in here.  Create your own namespace instead.
_signals = Namespace()

pre_create = _signals.signal('pre_create')
post_create = _signals.signal('post_create')

pre_update = _signals.signal('pre_update')
post_update = _signals.signal('post_update')

pre_delete = _signals.signal('pre_delete')
post_delete = _signals.signal('post_delete')

pre_search = _signals.signal('pre_search')
post_search = _signals.signal('post_search')
