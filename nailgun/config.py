"""Tools for managing and presenting server connection configurations.

NailGun needs to know certain facts about the remote server in order to do
anything useful. For example, NailGun needs to know the URL of the remote
server (e.g. 'https://example.com:250') and how to authenticate with the remote
server. :class:`nailgun.config.ServerConfig` eases the task of managing and
presenting that information.

"""
from os.path import isfile, join
from threading import Lock
from xdg import BaseDirectory
import json


_SENTINEL = object()
XDG_CONFIG_DIR = 'nailgun'
XDG_CONFIG_FILE = 'settings.json'


class ConfigFileError(Exception):
    """Indicates an error occurred when locating a configuration file."""


def _get_config_file_path():
    """Search for a NailGun configuration file and return the first one found.

    Each of the standard XDG configuration directories (e.g.
    `~/.config/nailgun/`) is searched for a NailGun configuration file. Beware
    that a check is made that the file exists, but this check is cursory. By
    the time client code attempts to open the file, it may be gone or otherwise
    inaccessible.

    :returns: A path to a configuration file.
    :rtype: str
    :raises ConfigFileError: When no configuration file can be found.

    """
    for config_dir in BaseDirectory.load_config_paths(XDG_CONFIG_DIR):
        path = join(config_dir, XDG_CONFIG_FILE)
        if isfile(path):
            return path
    raise ConfigFileError(
        'No configuration files could be located after searching for a file '
        'named "{0}" in the standard XDG configuration paths, such as '
        '"~/.config/{1}/".'.format(XDG_CONFIG_FILE, XDG_CONFIG_DIR)
    )


class ServerConfig(object):
    """A set of facts that are useful when communicating with a server."""
    _file_lock = Lock()

    def __init__(self, url, auth=_SENTINEL, verify=_SENTINEL):
        """Create a server configuration.

        :param str url: What is the URL Of the server? For example,
            `https://example.com/250`.
        :param auth: Credentials to use when communicating with the server. For
            example, `('username', 'password')`. No object attribute is created
            if no value is provided.
        :param bool verify: Should SSL be verified when communicating with the
            server? No object attribute is created if no value is provided.

        """
        self.url = url
        if auth != _SENTINEL:
            self.auth = auth
        if verify != _SENTINEL:
            self.verify = verify

    @classmethod
    def delete(cls, label='default', path=None):
        """Delete a server configuration.

        This method is thread safe.

        :param str label: The configuration identified by ``label`` is deleted.
        :param str path: The file at ``path`` is searched. By default, each of
            the standard XDG configuration directories is searched for a
            configuration file, and the first configuration file found is used.
        :returns: Nothing.
        :rtype: None

        """
        if path is None:
            path = _get_config_file_path()
        cls._file_lock.acquire()
        try:
            with open(path) as config_file:
                config = json.load(config_file)
            del config[label]
            with open(path, 'w') as config_file:
                json.dump(config, config_file)
        finally:
            cls._file_lock.release()

    @staticmethod
    def get(label='default', path=None):
        """Get a server configuration.

        :param str label: The configuration identified by ``label`` is read.
        :param str path: The file at ``path`` is searched. By default, each of
            the standard XDG configuration directories is searched for a
            configuration file, and the first configuration file found is used.
        :returns: A brand new :class:`nailgun.config.ServerConfig` object whose
            attributes have been populated as appropriate.
        :rtype: ServerConfig

        """
        if path is None:
            path = _get_config_file_path()
        with open(path) as config_file:
            return ServerConfig(**json.load(config_file)[label])

    def get_client_kwargs(self):
        """Get a dict of object attributes, but with "url" omitted.

        This method makes working with :mod:`nailgun.client` more pleasant.
        Code such as the following can be written::

            client.get(cfg.url + '/api/v2', **cfg.get_client_kwargs())

        This method has been placed here to promote a better layering of
        responsibilities: this class knows all about :mod:`nailgun.client`, and
        :mod:`nailgun.client` knows nothing about this class.

        """
        config = vars(self)
        config.pop('url')
        return config

    @staticmethod
    def get_labels(path=None):
        """Get all server configuration labels.

        :param str path: The file at ``path`` is searched. By default, each of
            the standard XDG configuration directories is searched for a
            configuration file, and the first configuration file found is used.
        :returns: Server configuration labels, where each label is a string.
        :rtype: tuple

        """
        if path is None:
            path = _get_config_file_path()
        with open(path) as config_file:
            # keys() returns a list in Python 2 and a view in Python 3.
            return tuple(json.load(config_file).keys())

    def save(self, label='default', path=None):
        """Save the current connection configuration to a file.

        This method is thread safe.

        :param str label: An identifier for the current configuration. This
            allows multiple configurations with unique labels to be saved in a
            single file. If a configuration identified by ``label`` already
            exists in the destination configuration file, it is replaced.
        :param str path: A path to the file in which the current configuration
            should be saved. By default, an XDG-compliant configuration file is
            used. A configuration file is created if none exists already.
        :returns: Nothing.
        :rtype: None

        """
        if path is None:
            path = join(
                BaseDirectory.save_config_path(XDG_CONFIG_DIR),
                XDG_CONFIG_FILE
            )
        self._file_lock.acquire()
        try:
            # Either read an existing config or make an empty one. Then update
            # the config and write it out.
            try:
                with open(path) as config_file:
                    config = json.load(config_file)
            except IOError:
                config = {}
            config[label] = vars(self)
            with open(path, 'w') as config_file:
                json.dump(config, config_file)
        finally:
            self._file_lock.release()
