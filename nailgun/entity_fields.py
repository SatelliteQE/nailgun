"""The basic components of the NailGun ORM.

Each of the fields in this module corresponds to some type of information that
Satellite tracks. When paired the classes in ``nailgun.entity_mixins``, it is
possible to represent the entities that Satellite manages. For example,
consider this abbreviated class definition::

    class User(
            entity_mixins.Entity,
            entity_mixins.EntityCreateMixin,
            entity_mixins.EntityDeleteMixin,
            entity_mixins.EntityReadMixin):
        entity_fields.login = StringField(
            length=(1, 100),
            required=True,
            str_type=('alpha', 'alphanumeric', 'cjk', 'latin1'),
        )
        entity_fields.admin = BooleanField(null=True)
        entity_fields.firstname = StringField(null=True, length=(1, 50))
        entity_fields.lastname = StringField(null=True, length=(1, 50))
        entity_fields.mail = EmailField(required=True)
        entity_fields.password = StringField(required=True)

The class represents a user account on a Satellite server. Each of the fields
represents some piece of information that is associated with a user account,
and the mixins provide useful methods.

Fields are intended to be used declaratively. You probably should not be
interacting with the field classes or their methods directly. Instead, they are
used by the various mixins. For example, method ``EntityReadMixin.read`` can be
used like this::

    user = User(id=5).read()

``EntityReadMixin.read`` creates a new ``User`` object and populates it. The
method knows how to deal with the data returned by the server because of the
fields on the ``User`` class.

A secondary use of fields is to generate random data. For example, you could
call ``User.login.gen_value()`` (implemented at :meth:`StringField.gen_value`)
to generate a random login. Beware that these methods strive to produce the
most outrageous values that are still legal, so they will often return nonsense
UTF-8 values, which is unpleasant to work with.

"""
from fauxfactory import (
    gen_boolean,
    gen_choice,
    gen_email,
    gen_integer,
    gen_ipaddr,
    gen_mac,
    gen_netmask,
    gen_string,
    gen_url,
)
from importlib import import_module
from inspect import isclass
import random
# pylint:disable=too-few-public-methods
# The classes in this module serve a declarative role. It is OK that they don't
# do much.
#
# Pylint warns that several of the `gen_value` methods do not make use of
# `self`. That warning is disabled where appropriate. The reason is that the
# `gen_value` methods are intended to be easily overridden in the entity
# classes that use them. Giving all `gen_value` methods the same signature
# makes this easier to do. A consistent method signature does no harm, and it
# reduces the cognitive load on other programmers.


# A sentinel object, used when `None` does not suffice.
_SENTINEL = object()

#: The default module that will be searched when an entity class needs to be
#: found. Used by at least :class:`OneToOneField` and `OneToManyField`.
ENTITIES_MODULE = 'nailgun.entities'


class Field(object):
    """Base class to implement other fields

    Record this field's attributes.

    :param bool required: Determines whether a value must be submitted to the
        server when creating or updating an entity.
    :param tuple choices: Legal values that this field may be populated with.
    :param default: Entity classes that inherit from ``EntityCreateMixin`` make
        use of this field.
    :param bool null: Determines whether a null value can be submitted to the
        server when creating or updating an entity.

    """

    def __init__(
            self,
            required=False,
            choices=None,
            default=_SENTINEL,
            null=False):
        self.required = required
        if choices is not None:
            self.choices = choices
        if default is not _SENTINEL:
            self.default = default
        self.null = null


class BooleanField(Field):
    """Field that represents a boolean"""

    def gen_value(self):
        """Return a value suitable for a :class:`BooleanField`."""
        # pylint:disable=no-self-use
        # See comment near top of module.
        return gen_boolean()


class EmailField(Field):
    """Field that represents an email"""

    def gen_value(self):
        """Return a value suitable for a :class:`EmailField`."""
        # pylint:disable=no-self-use
        # See comment near top of module.
        return gen_email()


class FloatField(Field):
    """Field that represents a float"""

    def gen_value(self):
        """Return a value suitable for a :class:`FloatField`."""
        # pylint:disable=no-self-use
        # See comment near top of module.
        return random.random() * 10000


class IntegerField(Field):
    """Field that represents an integer."""

    def __init__(self, min_val=None, max_val=None, *args, **kwargs):
        self.min_val = min_val
        self.max_val = max_val
        super(IntegerField, self).__init__(*args, **kwargs)

    def gen_value(self):
        """Return a value suitable for a :class:`IntegerField`."""
        return gen_integer(self.min_val, self.max_val)


class StringField(Field):
    """Field that represents a string.

    The default ``length`` of string fields is short for two reasons:

    1. Foreman's database backend limits many fields to 255 bytes in length. As
       a result, ``length`` should be no longer than 85 characters long, as 85
       unicode characters may be up to 255 bytes long.
    2. Humans have to read through the error messages produced by Robottelo.
       Long error messages are hard to read through, and that hurts
       productivity. Thus, a ``length`` even shorter than 85 chars is
       desirable.

    :param length: Either a ``(min_len, max_len)`` tuple or an ``exact_len``
        integer.
    :param str_type: The types of characters to generate when
        :meth:`StringField.gen_value` is called. May be a single string type
        (e.g. ``'utf8'``) or a tuple of string types. This argument is passed
        through to FauxFactory's ``gen_string`` method, so this method accepts
        all string types which that method does.

    """

    def __init__(self, length=(1, 30), str_type=('utf8',), *args, **kwargs):
        # length may be a two-tuple or an integer. Set {min,max}_len carefully.
        if isinstance(length, tuple):
            self.min_len, self.max_len = length
        else:
            self.min_len = self.max_len = length

        # str_type may be a tuple or a string, but self.str_type is a tuple.
        if isinstance(str_type, tuple):
            self.str_type = str_type
        else:
            self.str_type = (str_type,)

        super(StringField, self).__init__(*args, **kwargs)

    def gen_value(self):
        """Return a value suitable for a :class:`StringField`."""
        return gen_string(
            gen_choice(self.str_type),
            gen_integer(self.min_len, self.max_len)
        )


class DateField(Field):
    """Field that represents a date"""


class DateTimeField(Field):
    """Field that represents a datetime"""


class DictField(Field):
    """Field that represents a set of key-value pairs."""

    def gen_value(self):
        """Return a value suitable for a :class:`DictField`."""
        # pylint:disable=no-self-use
        # See comment near top of module.
        return {}


class IPAddressField(StringField):
    """Field that represents an IP adrress"""

    def gen_value(self):
        """Return a value suitable for a :class:`IPAddressField`."""
        return gen_ipaddr()


class NetmaskField(StringField):
    """Field that represents an netmask"""

    def gen_value(self):
        """Return a value suitable for a :class:`NetmaskField`."""
        return gen_netmask()


class ListField(Field):
    """Field that represents a list of strings"""


class MACAddressField(StringField):
    """Field that represents a MAC adrress"""

    def gen_value(self):
        """Return a value suitable for a :class:`MACAddressField`."""
        return gen_mac()


class OneToOneField(Field):
    """Field that represents a reference to another entity.

    All parameters not documented here are passed to :class:`Field`.

    :param entity: Either a class or the name of a class.
    :param str module: A dotted module name. Used by
        :meth:`OneToOneField.gen_value`. See that method for more details.

    """

    def __init__(self, entity, module=None, *args, **kwargs):
        self.entity = entity
        self.module = module
        super(OneToOneField, self).__init__(*args, **kwargs)

    def gen_value(self):
        """Return an instance of the class that this field references.

        If ``self.entity`` is a class, return an instance of that class.

        If ``self.entity`` is a string, find a class by that name and return an
        instance of it:

        * By default, search :data:`ENTITIES_MODULE` for the class.
        * If ``self.module`` is a string (e.g. ``'robottelo.entities'``), then
          search that module instead.

        """
        return _get_class(self.entity, self.module)()


class OneToManyField(Field):
    """Field that represents a reference to zero or more other entities.

    The parameters for this class are exactly the same as for
    :class:`OneToOneField`.

    """

    def __init__(self, entity, module=None, *args, **kwargs):
        self.entity = entity
        self.module = module
        super(OneToManyField, self).__init__(*args, **kwargs)

    def gen_value(self):
        """Return an instance of the class that this field references.

        This method behaves exactly like :meth:`OneToOneField.gen_value`.

        """
        return _get_class(self.entity, self.module)()


class URLField(StringField):
    """Field that represents an URL"""

    def gen_value(self):
        """Return a value suitable for a :class:`URLField`."""
        return gen_url()


def _get_class(class_or_name, module=None):
    """Return a class object.

    If ``class_or_name`` is a class, it is returned untouched. Otherwise,
    ``class_or_name`` is assumed to be a string. In this case, ``module`` is
    searched for a class by that name and returned.

    :param class_or_name: Either a class or the name of a class.
    :param str module: A dotted module name.
    :return: Either the class passed in or a class from ``module``.

    """
    if isclass(class_or_name):
        return class_or_name
    if module is None:
        module = ENTITIES_MODULE
    return getattr(import_module(module), class_or_name)
