"""Unit tests for :mod:`nailgun.config`."""

import builtins
import json
import tempfile
from unittest import TestCase
from unittest.mock import call, mock_open, patch

from packaging.version import InvalidVersion, parse

from nailgun.config import (
    BaseServerConfig,
    ConfigFileError,
    ServerConfig,
    _get_config_file_path,
)

FILE_PATH = tempfile.NamedTemporaryFile(suffix='.json', delete=False).name
CONFIGS = {
    'default': {'url': 'http://example.com'},
    'Ask Aak': {'url': 'bogus value', 'auth': ['username', 'password']},
    'Acros-Krik': {'url': 'booger', 'version': '1.2.3.4.dev5+67'},
}
INVALID_CONFIG = {'url': 'burger', 'version': 'silly version'}
CONFIGS2 = CONFIGS.copy()
CONFIGS2.update(
    {
        'Abeloth': {'url': 'bogus value', 'verify': True},
        'Admiral Gial Ackbar': {'url': 'bogus', 'auth': [], 'verify': False},
    }
)

# Tests use an unused nailgun import
# ruff: noqa: F401

# Cannot use ast.literal_eval because ServerConfig isn't a basic type
# ruff: noqa: S307


def _convert_bsc_attrs(bsc_attrs):
    """Alter a dict of attributes in the same way as ``BaseServerConfig``.

    ``bsc_attrs`` is not altered. If changes are made, a copy is returned.

    :param bsc_attrs: A dict of attributes as might be passed to
        :class:`nailgun.config.BaseServerConfig`.
    :returns: A dict of attributes as is returned by
        ``vars(BaseServerConfig(bsc_attrs))``.
    """
    if 'version' in bsc_attrs:
        bsc_attrs = bsc_attrs.copy()  # shadow the passed in dict
        bsc_attrs['version'] = parse(bsc_attrs.pop('version'))
    return bsc_attrs


class BaseServerConfigTestCase(TestCase):
    """Tests for :class:`nailgun.config.BaseServerConfig`."""

    def test_init(self):
        """Test instantiating :class:`nailgun.config.BaseServerConfig`.

        Assert that only provided values become object attributes.

        """
        for config in CONFIGS.values():
            self.assertEqual(
                _convert_bsc_attrs(config),
                vars(BaseServerConfig(**config)),
            )

    def test_init_invalid(self):
        """Test instantiating :class: `nailgun.config.BaseServerConfig`.

        Assert that configs with invalid versions do not load.
        """
        with self.assertRaises(InvalidVersion):
            _convert_bsc_attrs(INVALID_CONFIG)

    def test_get(self):
        """Test :meth:`nailgun.config.BaseServerConfig.get`.

        Assert that the method extracts the asked-for section from a
        configuration file and correctly populates a new ``BaseServerConfig``
        object. Also assert that the ``auth`` attribute is a list. (See the
        docstring for :meth:`nailgun.config.ServerConfig.get`.)

        """
        for label, config in CONFIGS.items():
            open_ = mock_open(read_data=json.dumps(CONFIGS))
            with patch.object(builtins, 'open', open_):
                server_config = BaseServerConfig.get(label, FILE_PATH)
            self.assertEqual(type(server_config), BaseServerConfig)
            open_.assert_called_once_with(FILE_PATH)
            self.assertEqual(_convert_bsc_attrs(config), vars(server_config))
            if hasattr(server_config, 'auth'):
                self.assertIsInstance(server_config.auth, list)

    def test_get_labels(self):
        """Test :meth:`nailgun.config.BaseServerConfig.get_labels`.

        Assert that the method returns the correct labels.

        """
        open_ = mock_open(read_data=json.dumps(CONFIGS))
        with patch.object(builtins, 'open', open_):
            self.assertEqual(
                set(CONFIGS.keys()),
                set(BaseServerConfig.get_labels(FILE_PATH)),
            )
        open_.assert_called_once_with(FILE_PATH)

    def test_save(self):
        """Test :meth:`nailgun.config.BaseServerConfig.save`.

        Assert that the method reads the config file before writing, and that
        it writes out a correct config file.

        """
        label = 'Ask Aak'
        config = {label: {'url': 'https://example.org'}}
        open_ = mock_open(read_data=json.dumps(CONFIGS))
        with patch.object(builtins, 'open', open_):
            BaseServerConfig(config[label]['url']).save(label, FILE_PATH)

        # We care about two things: that this method reads the config file
        # before writing, and that the written string is correct. The first is
        # easy to verify...
        self.assertEqual(
            open_.call_args_list,
            [call(FILE_PATH), call(FILE_PATH, 'w')],
        )
        # ...and the second is a PITA to verify.
        actual_config = _get_written_json(open_)
        target_config = CONFIGS.copy()
        target_config[label] = config[label]
        self.assertEqual(target_config, actual_config)

    def test_delete(self):
        """Test :meth:`nailgun.config.BaseServerConfig.delete`.

        Assert that the method reads the config file before writing, and that
        it writes out a correct config file.

        """
        open_ = mock_open(read_data=json.dumps(CONFIGS))
        with patch.object(builtins, 'open', open_):
            BaseServerConfig.delete('Ask Aak', FILE_PATH)

        # See `test_save` for further commentary on what's being done here.
        self.assertEqual(
            open_.call_args_list,
            [call(FILE_PATH), call(FILE_PATH, 'w')],
        )
        actual_config = _get_written_json(open_)
        target_config = CONFIGS.copy()
        del target_config['Ask Aak']
        self.assertEqual(target_config, actual_config)


class ServerConfigTestCase(TestCase):
    """Tests for :class:`nailgun.config.ServerConfig`."""

    def test_init(self):
        """Test instantiating :class:`nailgun.config.ServerConfig`.

        Assert that only provided values become object attributes.

        """
        for config in CONFIGS2.values():
            self.assertEqual(
                _convert_bsc_attrs(config),
                vars(ServerConfig(**config)),
            )

    def test_raise_config_file_error(self):
        """Should raise error if path not found."""
        with self.assertRaises(ConfigFileError):
            _get_config_file_path('foo', 'bar')

    def test_get_client_kwargs(self):
        """Test :meth:`nailgun.config.ServerConfig.get_client_kwargs`.

        Assert that:

        * ``get_client_kwargs`` returns all of the instance attributes from its
          object except the "url" attribute, and
        * no instance attributes from the object are removed.

        """
        for config in CONFIGS2.values():
            target = config.copy()
            target.pop('url')
            target.pop('version', None)
            server_config = ServerConfig(**config)
            self.assertDictEqual(target, server_config.get_client_kwargs())
            self.assertDictEqual(vars(ServerConfig(**config)), vars(server_config))

    def test_get(self):
        """Test :meth:`nailgun.config.ServerConfig.get`.

        Assert that the ``auth`` attribute is a tuple.

        """
        for label in CONFIGS:
            open_ = mock_open(read_data=json.dumps(CONFIGS))
            with patch.object(builtins, 'open', open_):
                server_config = ServerConfig.get(label, FILE_PATH)
            self.assertEqual(type(server_config), ServerConfig)
            if hasattr(server_config, 'auth'):
                self.assertIsInstance(server_config.auth, tuple)


class ReprTestCase(TestCase):
    """Test method ``nailgun.config.BaseServerConfig.__repr__``."""

    def test_bsc_v1(self):
        """Test :class:`nailgun.config.BaseServerConfig`.

        Assert that ``__repr__`` works correctly when ``url`` is specified.

        """
        target = "nailgun.config.BaseServerConfig(url='bogus')"
        self.assertEqual(target, repr(BaseServerConfig('bogus')))
        import nailgun

        self.assertEqual(target, repr(eval(repr(BaseServerConfig('bogus')))))

    def test_bsc_v2(self):
        """Test :class:`nailgun.config.BaseServerConfig`.

        Assert that ``__repr__`` works correctly when ``url`` and ``auth`` are
        specified.

        """
        targets = (
            "nailgun.config.BaseServerConfig(url='flim', auth='flam')",
            "nailgun.config.BaseServerConfig(auth='flam', url='flim')",
        )
        self.assertIn(repr(BaseServerConfig('flim', auth='flam')), targets)
        import nailgun

        self.assertIn(repr(eval(repr(BaseServerConfig('flim', auth='flam')))), targets)

    def test_bsc_v3(self):
        """Test :class:`nailgun.config.BaseServerConfig`.

        Assert that ``__repr__`` works correctly when ``url`` and ``version``
        are specified.

        """
        targets = (
            "nailgun.config.BaseServerConfig(url='flim', version='1')",
            "nailgun.config.BaseServerConfig(version='1', url='flim')",
        )
        self.assertIn(repr(BaseServerConfig('flim', version='1')), targets)

    def test_sc_v1(self):
        """Test :class:`nailgun.config.ServerConfig`.

        Assert that ``__repr__`` works correctly when only a URL is passed in.

        """
        target = "nailgun.config.ServerConfig(url='bogus')"
        self.assertEqual(target, repr(ServerConfig('bogus')))
        import nailgun

        self.assertEqual(target, repr(eval(repr(ServerConfig('bogus')))))

    def test_sc_v2(self):
        """Test :class:`nailgun.config.ServerConfig`.

        Assert that ``__repr__`` works correctly when ``url`` and ``auth`` are
        specified.

        """
        targets = (
            "nailgun.config.ServerConfig(url='flim', auth='flam')",
            "nailgun.config.ServerConfig(auth='flam', url='flim')",
        )
        self.assertIn(repr(ServerConfig('flim', auth='flam')), targets)
        import nailgun

        self.assertIn(repr(eval(repr(ServerConfig('flim', auth='flam')))), targets)

    def test_sc_v3(self):
        """Test :class:`nailgun.config.ServerConfig`.

        Assert that ``__repr__`` works correctly when ``url`` and ``version``
        are specified.

        """
        targets = (
            "nailgun.config.ServerConfig(url='flim', version='1')",
            "nailgun.config.ServerConfig(version='1', url='flim')",
        )
        self.assertIn(repr(ServerConfig('flim', version='1')), targets)

    def test_sc_v4(self):
        """Test :class:`nailgun.config.ServerConfig`.

        Assert that ``__repr__`` works correctly when ``url`` and ``verify``
        are specified.

        """
        targets = (
            "nailgun.config.ServerConfig(url='flim', verify='flub')",
            "nailgun.config.ServerConfig(verify='flub', url='flim')",
        )
        self.assertIn(repr(ServerConfig('flim', verify='flub')), targets)
        import nailgun

        self.assertIn(repr(eval(repr(ServerConfig('flim', verify='flub')))), targets)


def _get_written_json(mock_obj):
    """Return the JSON that has been written to a mock `open` object."""
    # json.dump() calls write() for each individual JSON token.
    return json.loads(''.join(tuple(call_obj)[1][0] for call_obj in mock_obj().write.mock_calls))
