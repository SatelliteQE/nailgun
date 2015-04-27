"""Unit tests for :mod:`nailgun.entity_fields`."""
from nailgun import entity_fields
from random import randint
from sys import version_info
from unittest import TestCase
import datetime
import socket


# It is OK that this class has no public methods. It just needs to exist for use
# by other tests, not be independently useful.
class TestClass(object):  # pylint:disable=too-few-public-methods
    """A class that is used when testing the OneTo{One,Many}Field classes."""


class GenValueTestCase(TestCase):
    """Tests for the ``gen_value`` method on various ``*Field`` classes.

    Classes with complex ``gen_value`` implementations are broken out into
    separate test cases.

    """

    def test_one_to_one_field(self):
        """Test :class:`nailgun.entity_fields.OneToOneField`."""
        self.assertEqual(
            entity_fields.OneToOneField(TestClass).gen_value(),
            TestClass
        )

    def test_one_to_many_field(self):
        """Test :class:`nailgun.entity_fields.OneToManyField`."""
        self.assertEqual(
            entity_fields.OneToManyField(TestClass).gen_value(),
            TestClass
        )

    def test_boolean_field(self):
        """Test :class:`nailgun.entity_fields.BooleanField`."""
        self.assertIn(entity_fields.BooleanField().gen_value(), (True, False))

    def test_date_field(self):
        """Test :class:`nailgun.entity_fields.DateField`."""
        self.assertIsInstance(
            entity_fields.DateField().gen_value(), datetime.date
        )

    def test_datetime_field(self):
        """Test :class:`nailgun.entity_fields.DateTimeField`."""
        self.assertIsInstance(
            entity_fields.DateTimeField().gen_value(), datetime.datetime
        )

    def test_email_field(self):
        """Test :class:`nailgun.entity_fields.EmailField`.

        Ensure :meth:`nailgun.entity_fields.EmailField.gen_value` returns a
        unicode string containing the character '@'.

        """
        email = entity_fields.EmailField().gen_value()
        if version_info.major == 2:
            self.assertIsInstance(email, unicode)  # flake8:noqa pylint:disable=undefined-variable
        else:
            self.assertIsInstance(email, str)
        self.assertIn('@', email)

    def test_float_field(self):
        """Test :class:`nailgun.entity_fields.FloatField`."""
        self.assertIsInstance(entity_fields.FloatField().gen_value(), float)

    def test_ip_address_field(self):
        """Test :class:`nailgun.entity_fields.IPAddressField`.

        Ensure the value returned is acceptable to ``socket.inet_aton``.

        """
        addr = entity_fields.IPAddressField().gen_value()
        try:
            socket.inet_aton(addr)
        except socket.error as err:
            self.fail('({0}) {1}'.format(addr, err))

    def test_mac_address_field(self):
        """Test :class:`nailgun.entity_fields.MACAddressField`.

        Ensure the value returned is a string containing 12 hex digits (either
        upper or lower case), grouped into pairs of digits and separated by
        colon characters. For example: ``'01:23:45:FE:dc:BA'``

        The regex used in this test is inspired by this Q&A:
        http://stackoverflow.com/questions/7629643/how-do-i-validate-the-format-of-a-mac-address

        """
        if version_info.major == 2:
            validator = self.assertRegexpMatches
        else:
            validator = self.assertRegex  # pylint:disable=no-member
        validator(
            entity_fields.MACAddressField().gen_value().upper(),
            '^([0-9A-F]{2}[:]){5}[0-9A-F]{2}$'
        )


class StringFieldTestCase(TestCase):
    """Tests for :class:`nailgun.entity_fields.StringField`."""

    def test_str_is_returned(self):
        """Ensure a unicode string at least 1 char long is returned."""
        string = entity_fields.StringField().gen_value()
        if version_info[0] == 2:
            self.assertIsInstance(string, unicode)  # flake8:noqa pylint:disable=undefined-variable
        else:
            self.assertIsInstance(string, str)
        self.assertGreater(len(string), 0)

    def test_length_arg(self):
        """Ensure that the ``length`` argument is respected."""
        # What happens when we pass in an exact length?
        string = entity_fields.StringField(length=5).gen_value()
        self.assertEqual(len(string), 5)

        # What happens when we pass in a range of lengths?
        string = entity_fields.StringField(length=(1, 20)).gen_value()
        self.assertGreaterEqual(len(string), 1)
        self.assertLessEqual(len(string), 20)

    def test_str_type_arg(self):
        """Ensure that the ``str_type`` argument is respected."""
        # This method uses single-use variables. But the code just looks
        # ridiculous if they are eliminated.
        for str_type in ('alpha', ('alpha',)):
            string = entity_fields.StringField(str_type=str_type).gen_value()
            self.assertTrue(string.isalpha())
        for str_type in ('numeric', ('numeric',)):
            string = entity_fields.StringField(str_type=str_type).gen_value()
            self.assertTrue(string.isnumeric())

        str_type = ('alpha', 'numeric')
        string = entity_fields.StringField(str_type=str_type).gen_value()
        self.assertTrue(string.isalpha() or string.isnumeric())


class IntegerFieldTestCase(TestCase):
    """Tests for :class:`nailgun.entity_fields.IntegerField`."""

    def test_int_is_returned(self):
        """Enture the value returned is an ``int``."""
        self.assertIsInstance(entity_fields.IntegerField().gen_value(), int)

    def test_min_val_arg(self):
        """Ensure that the ``min_val`` argument is respected."""
        min_val = randint(-1000, 1000)
        val = entity_fields.IntegerField(min_val=min_val).gen_value()
        self.assertGreaterEqual(val, min_val)

    def test_max_val_arg(self):
        """Ensure that the ``max_val`` argument is respected."""
        max_val = randint(-1000, 1000)
        val = entity_fields.IntegerField(max_val=max_val).gen_value()
        self.assertLessEqual(val, max_val)

    def test_min_val_max_val_args(self):
        """Ensure that the ``min_val`` and ``max_val`` args are respected."""
        min_val = randint(-1000, 0)
        max_val = randint(0, 1000)

        # First, we'll allow a range of values...
        val = entity_fields.IntegerField(min_val, max_val).gen_value()
        self.assertGreaterEqual(val, min_val)
        self.assertLessEqual(val, max_val)

        # ... then, we'll allow only a single value...
        val = entity_fields.IntegerField(min_val, min_val).gen_value()
        self.assertEqual(val, min_val)

        # ... twice over, just to be sure.
        val = entity_fields.IntegerField(max_val, max_val).gen_value()
        self.assertEqual(val, max_val)
