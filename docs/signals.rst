.. _signals:

=======
Signals
=======

.. versionadded:: 0.27.0

.. note::

  Signal support is provided by the excellent `blinker`_ library. If you wish
  to enable signal support this library must be installed, though it is not
  required for nailgun to function.

Overview
--------

The nailgun signals are provided by `blinker_herald`_ module and offers the same
features as `blinker`_.

Signals are found within the `nailgun.signals` module.
The first positional argument of a signal handler is always `sender` which is a
reference to the caller object (self).
Each kind of signal receives a different set of arguments but the recommendation
is to implement the handlers in form of: `def listener(sender, **kwargs)` as
all the arguments will be named depending on the signal.

.. note::

  Post-signals are only called if there were no exceptions
  raised during the processing of their related function.

Available signals include:


`pre_create`
  Called within :meth:`~nailgun.entity_mixins.EntityCreateMixin.create` prior to performing
  any actions.
  Handler named arguments: `create_missing`

`post_create`
  Called within :meth:`~nailgun.entity_mixins.EntityCreateMixin.create` after all actions
  have completed successfully.
  Handler named arguments: `entity`

`pre_delete`
  Called within :meth:`~nailgun.entity_mixins.EntityDeleteMixin.delete` prior to
  attempting the delete operation.
  Handler named arguments: `synchronous`

`post_delete`
  Called within :meth:`~nailgun.entity_mixins.EntityDeleteMixin.delete` upon successful
  deletion of the record.
  Handler named arguments: `synchronous` and `result`

`pre_update`
  Called within :meth:`~nailgun.entity_mixins.EntityUpdateMixin.update` prior to
  attempting the update operation.
  Handler named arguments: `fields`

`post_update`
  Called within :meth:`~nailgun.entity_mixins.EntityUpdateMixin.update` upon successful
  update of the record.
  Handler named arguments: `fields` and `entity`

`pre_search`
  Called within :meth:`~nailgun.entity_mixins.EntitySearchMixin.search` prior to
  attempting the search operation.
  Handler named arguments: `fields`, `query` and `filters`

`post_search`
  Called within :meth:`~nailgun.entity_mixins.EntitySearchMixin.search` upon successful
  search and before returning the results.
  Handler named arguments: `fields`, `query` and `filters` and `entities`

Attaching Events
----------------

A handler (also called listener) is a function like the following::

    def set_domain_to_all_entities(sender, **kwargs):
        sender.domain = "http://example.com"


The first argument is always the **sender** which defaults to the **self** or **cls**
of the caller. Note that handlers can accept only one positional argument,
all the others arguments must be named or captured by the ``**kwargs``
also note that **signal_emitter** argument will always be passed to handlers
to keep a reference to caller object in the cases where **sender** argument
is explicitly specified in the caller.

.. note::
  NOTE: Always end your handler signature with
  ``**kwargs`` to capture all possible arguments
  otherwise signals will fail if new arguments added to emitter function.


You attach the event handler to a signal that will be emitted to all entities in general::

    from nailgun import signals
    signals.pre_create.connect(set_domain_to_all_entities)


Everytime the `.create` method is called the all the connected handlers will be called
by signaling and any kind of manipulation can be performed.

.. note::
  If your handler meant to deal only with a specific type of entity you'll need
  to inspect its instance type. :code:`if isinstance(sender, entities.Organization)` otherwise
  the action will be performed for all types of entities. Or use a specific
  sender and connect using :code:`.connect_via()` decorator os specifying **sender** while connecting.

Finally, you can also use signals as decorators to quickly create a number of
signals handlers and attach them::

    from nailgun import entities, signals

    @signals.post_create.connect
    def post_create_handler(sender, entity):
        if isinstance(entity, entities.Organization):
            # do something in post create only for Organizations

.. _blinker: http://pypi.python.org/pypi/blinker
.. _blinker_herald: http://pypi.python.org/pypi/blinker_herald
