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
}
CONFIGS2 = CONFIGS.copy()
CONFIGS2.update({
    'Abeloth': {'url': 'bogus value', 'verify': True},
    'Admiral Gial Ackbar': {'url': 'bogus', 'auth': [], 'verify': False},
})
# The pylint star-args warning is disabled for several tests. This is because
# star args make the relevant tests _so_ much more compact than any
# alternatives, and the dicts in question are hardcoded right here.


class BaseServerConfigTestCase(TestCase):
    """Tests for :class:`nailgun.config.BaseServerConfig`."""

    def test_init(self):
        """Test instantiating :class:`nailgun.config.BaseServerConfig`.

        Assert that only provided values become object attributes.

        """
        for config in CONFIGS.values():
            # pylint:disable=star-args
            self.assertEqual(config, vars(BaseServerConfig(**config)))

    def test_get(self):
        """Test :meth:`nailgun.config.BaseServerConfig.get`.

        Assert that the method extracts the asked-for section from a
        configuration file and correctly populates a new ``BaseServerConfig``
        object.

        """
        for label, config in CONFIGS.items():
            open_ = mock_open(read_data=json.dumps(CONFIGS))
            with patch.object(builtins, 'open', open_):
                server_config = BaseServerConfig.get(label, FILE_PATH)
            self.assertEqual(vars(server_config), config)
            open_.assert_called_once_with(FILE_PATH)

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
            # pylint:disable=star-args
            self.assertEqual(config, vars(ServerConfig(**config)))

    def test_get_client_kwargs(self):
        """Test :meth:`nailgun.config.ServerConfig.get_client_kwargs`.

        Assert that all attributes passed in are returned, but with "url"
        omitted.

        """
        for config in CONFIGS2.values():
            out = config.copy()
            out.pop('url')
            # pylint:disable=star-args
            self.assertEqual(out, ServerConfig(**config).get_client_kwargs())


def _get_written_json(mock_obj):
    """Return the JSON that has been written to a mock `open` object."""
    # json.dump() calls write() for each individual JSON token.
    return json.loads(''.join(
        tuple(call_obj)[1][0]
        for call_obj
        in mock_obj().write.mock_calls
    ))
