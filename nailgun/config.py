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


class ConfigFileError(Exception):
    """Indicates an error occurred when locating a configuration file.

    .. WARNING:: This class will likely be moved to a separate Python package
        in a future release of NailGun. Be careful about making references to
        this class, as those references will likely need to be changed.

    """


def _get_config_file_path(xdg_config_dir, xdg_config_file):
    """Search ``XDG_CONFIG_DIRS`` for a config file and return the first found.

    Search each of the standard XDG configuration directories for a
    configuration file. Return as soon as a configuration file is found. Beware
    that by the time client code attempts to open the file, it may be gone or
    otherwise inaccessible.

    :param str xdg_config_dir: The name of the directory that is suffixed to
        the end of each of the ``XDG_CONFIG_DIRS`` paths.
    :param str xdg_config_file: The name of the configuration file that is
        being searched for.
    :returns: A path to a configuration file.
    :rtype: str
    :raises nailgun.config.ConfigFileError: When no configuration file can be
        found.

    """
    for config_dir in BaseDirectory.load_config_paths(xdg_config_dir):
        path = join(config_dir, xdg_config_file)
        if isfile(path):
            return path
    raise ConfigFileError(
        'No configuration files could be located after searching for a file '
        'named "{0}" in the standard XDG configuration paths, such as '
        '"~/.config/{1}/".'.format(xdg_config_file, xdg_config_dir)
    )


class BaseServerConfig(object):
    """A minimal set of facts for communicating with a Satellite server.

    :param str url: What is the URL Of the server? For example,
        `https://example.com/250`.
    :param auth: Credentials to use when communicating with the server. For
        example, `('username', 'password')`. No object attribute is created if
        no value is provided.

    .. WARNING:: This class will likely be moved to a separate Python package
        in a future release of NailGun. Be careful about making references to
        this class, as those references will likely need to be changed.

    """
    # Used to lock access to the configuration file when performing certain
    # operations, such as saving.
    _file_lock = Lock()
    # The name of the directory appended to ``XDG_CONFIG_DIRS``.
    _xdg_config_dir = 'librobottelo'
    # The name of the file in which settings are stored.
    _xdg_config_file = 'settings.json'

    def __init__(self, url, auth=None):
        self.url = url
        if auth is not None:
            self.auth = auth

    @classmethod
    def delete(cls, label='default', path=None):
        """Delete a server configuration.

        This method is thread safe.

        :param str label: The configuration identified by ``label`` is deleted.
        :param str path: The configuration file to be manipulated. Defaults to
            what is returned by :func:`nailgun.config._get_config_file_path`.
        :returns: Nothing.
        :rtype: None

        """
        if path is None:
            path = _get_config_file_path(
                cls._xdg_config_dir,
                cls._xdg_config_file
            )
        cls._file_lock.acquire()
        try:
            with open(path) as config_file:
                config = json.load(config_file)
            del config[label]
            with open(path, 'w') as config_file:
                json.dump(config, config_file)
        finally:
            cls._file_lock.release()

    @classmethod
    def get(cls, label='default', path=None):
        """Get a server configuration.

        :param str label: The configuration identified by ``label`` is read.
        :param str path: The configuration file to be manipulated. Defaults to
            what is returned by :func:`nailgun.config._get_config_file_path`.
        :returns: A brand new :class:`nailgun.config.ServerConfig` object whose
            attributes have been populated as appropriate.
        :rtype: ServerConfig

        """
        if path is None:
            path = _get_config_file_path(
                cls._xdg_config_dir,
                cls._xdg_config_file
            )
        with open(path) as config_file:
            return ServerConfig(**json.load(config_file)[label])

    @classmethod
    def get_labels(cls, path=None):
        """Get all server configuration labels.

        :param str path: The configuration file to be manipulated. Defaults to
            what is returned by :func:`nailgun.config._get_config_file_path`.
        :returns: Server configuration labels, where each label is a string.
        :rtype: tuple

        """
        if path is None:
            path = _get_config_file_path(
                cls._xdg_config_dir,
                cls._xdg_config_file
            )
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
        :param str path: The configuration file to be manipulated. By default,
            an XDG-compliant configuration file is used. A configuration file
            is created if one does not exist already.
        :returns: Nothing.
        :rtype: None

        """
        if path is None:
            path = join(
                BaseDirectory.save_config_path(self._xdg_config_dir),
                self._xdg_config_file
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


class ServerConfig(BaseServerConfig):
    """Facts for communicating with a server's API.

    This class inherits from :class:`nailgun.config.BaseServerConfig`. Other
    constructor parameters are documented there.

    :param bool verify: Should SSL be verified when communicating with the
        server? No object attribute is created if no value is provided.

    """
    # pylint:disable=too-few-public-methods
    # It's OK that this class has only one public method. This class is
    # intentionally small so that the parent class can be re-used.
    _xdg_config_dir = 'nailgun'
    _xdg_config_file = 'server_configs.json'

    def __init__(self, url, auth=None, verify=None):
        super(ServerConfig, self).__init__(url, auth)
        if verify is not None:
            self.verify = verify

    def get_client_kwargs(self):
        """Get a dict of object attributes, but with "url" omitted.

        This method makes working with :mod:`nailgun.client` more pleasant.
        Code such as the following can be written::

            cfg = ServerConfig.get()
            client.get(cfg.url + '/api/v2', **cfg.get_client_kwargs())

        This method has been placed here to promote a better layering of
        responsibilities: this class knows all about :mod:`nailgun.client`, and
        :mod:`nailgun.client` knows nothing about this class.

        """
        config = vars(self)
        config.pop('url')
        return config
