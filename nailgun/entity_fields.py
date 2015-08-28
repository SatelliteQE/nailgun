"""The basic components of the NailGun ORM.

Each of the fields in this module corresponds to some type of information that
Satellite tracks. When paired the classes in :class:`nailgun.entity_mixins`, it
is possible to represent the entities that Satellite manages. For a concrete
example of how this works, see :class:`nailgun.entity_mixins.Entity`.

Fields are typically used declaratively in an entity's ``__init__`` function
and are otherwise left untouched, except by the mixin methods. For example,
:meth:`nailgun.entity_mixins.EntityReadMixin.read` looks at the fields on an
entity to determine what information it should expect the server to return.

A secondary use of fields is to generate random data. For example, you could
call ``User.get_fields()['login'].gen_value()`` to generate a random login.
(``gen_value`` is implemented at :meth:`StringField.gen_value`) Beware that the
``gen_value`` methods strive to produce the most outrageous values that are
still legal, so they will often return nonsense UTF-8 values, which is
unpleasant to work with manually.

"""
from fauxfactory import (
    gen_alpha,
    gen_boolean,
    gen_choice,
    gen_date,
    gen_datetime,
    gen_email,
    gen_integer,
    gen_ipaddr,
    gen_mac,
    gen_netmask,
    gen_string,
    gen_url,
)
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


class Field(object):
    """Base class to implement other fields

    Record this field's attributes.

    :param required: A boolean. Determines whether a value must be submitted to
        the server when creating or updating an entity.
    :param choices: A tuple of values that this field may be populated with.
    :param default: Entity classes that inherit from
        :class:`nailgun.entity_mixins.EntityCreateMixin` use this field.

    """

    def __init__(self, required=False, choices=None, default=_SENTINEL):
        self.required = required
        if choices is not None:
            self.choices = choices
        if default is not _SENTINEL:
            self.default = default


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
    2. Humans have to read through the error messages produced by this library.
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

    def __init__(self, min_date=None, max_date=None, *args, **kwargs):
        # If ``None`` is passed then ``FauxFactory`` will deal with it.
        self.min_date = min_date
        self.max_date = max_date
        super(DateField, self).__init__(*args, **kwargs)

    def gen_value(self):
        """Return a value suitable for a :class:`DateField`."""
        return gen_date(self.min_date, self.max_date)


class DateTimeField(Field):
    """Field that represents a datetime"""

    def __init__(self, min_date=None, max_date=None, *args, **kwargs):
        # If ``None`` is passed then ``FauxFactory`` will deal with it.
        self.min_date = min_date
        self.max_date = max_date
        super(DateTimeField, self).__init__(*args, **kwargs)

    def gen_value(self):
        """Return a value suitable for a :class:`DateTimeField`."""
        return gen_datetime(self.min_date, self.max_date)


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

    :param nailgun.entity_mixins.Entity entity: The entity to which this field
        points.

    """

    def __init__(self, entity, *args, **kwargs):
        self.entity = entity
        super(OneToOneField, self).__init__(*args, **kwargs)

    def gen_value(self):
        """Return the class that this field references."""
        return self.entity


class OneToManyField(Field):
    """Field that represents a reference to zero or more other entities.

    :param nailgun.entity_mixins.Entity entity: The entities to which this
        field points.

    """

    def __init__(self, entity, *args, **kwargs):
        self.entity = entity
        super(OneToManyField, self).__init__(*args, **kwargs)

    def gen_value(self):
        """Return the class that this field references."""
        return self.entity


class URLField(StringField):
    """Field that represents an URL"""

    def gen_value(self):
        """Return a value suitable for a :class:`URLField`."""
        return gen_url(subdomain=gen_alpha())
