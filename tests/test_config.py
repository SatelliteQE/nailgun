"""Unit tests for :mod:`nailgun.config`."""
from mock import call, mock_open, patch
from nailgun.config import BaseServerConfig, ServerConfig
from unittest import TestCase
import json

from sys import version_info
if version_info[0] == 2:
    # The `__builtins__` module (note the "s") also provides the `open`
    # function. However, that module is an implementation detail for CPython 2,
    # so it should not be relied on.
    import __builtin__ as builtins  # pylint:disable=import-error
else:
    import builtins  # pylint:disable=import-error


FILE_PATH = '/tmp/bogus.json'
CONFIGS = {
    'default': {'url': 'http://example.com'},
    'Ask Aak': {'url': 'bogus value', 'auth': ['username', 'password']},
    'Acros-Krik': {'url': 'booger', 'version': '1.2.3.4.dev5+67'},
    'King Adas': {'url': 'burger', 'version': 'silly version'},
}
CONFIGS2 = CONFIGS.copy()
CONFIGS2.update({
    'Abeloth': {'url': 'bogus value', 'verify': True},
    'Admiral Gial Ackbar': {'url': 'bogus', 'auth': [], 'verify': False},
})


def _compare_configs(self, dict_config, server_config):
    """Compare a server config in two different forms.

    :param dict_config: A dict of values, such as might be returned by
        ``json.load`` when reading a config file.
    :param server_config: A :class:`nailgun.config.BaseServerConfig` or a
        subclass thereof.

    """
    cfg = vars(server_config).copy()
    if 'version' in cfg:
        cfg['version'] = str(cfg['version'])
    self.assertEqual(dict_config, cfg)


class BaseServerConfigTestCase(TestCase):
    """Tests for :class:`nailgun.config.BaseServerConfig`."""

    def test_init(self):
        """Test instantiating :class:`nailgun.config.BaseServerConfig`.

        Assert that only provided values become object attributes.

        """
        for config in CONFIGS.values():
            server_config = BaseServerConfig(**config)
            _compare_configs(self, config, server_config)

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
            open_.assert_called_once_with(FILE_PATH)
            _compare_configs(self, config, server_config)
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
            _compare_configs(self, config, ServerConfig(**config))

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
            self.assertDictEqual(
                vars(ServerConfig(**config)),
                vars(server_config)
            )

    def test_get(self):
        """Test :meth:`nailgun.config.ServerConfig.get`.

        Assert that the ``auth`` attribute is a tuple.

        """
        for label in CONFIGS.keys():
            open_ = mock_open(read_data=json.dumps(CONFIGS))
            with patch.object(builtins, 'open', open_):
                server_config = ServerConfig.get(label, FILE_PATH)
            if hasattr(server_config, 'auth'):
                self.assertIsInstance(server_config.auth, tuple)


def _get_written_json(mock_obj):
    """Return the JSON that has been written to a mock `open` object."""
    # json.dump() calls write() for each individual JSON token.
    return json.loads(''.join(
        tuple(call_obj)[1][0]
        for call_obj
        in mock_obj().write.mock_calls
    ))
