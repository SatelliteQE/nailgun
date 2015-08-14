"""Tools for managing and presenting server connection configurations.

NailGun needs to know certain facts about the remote server in order to do
anything useful. For example, NailGun needs to know the URL of the remote
server (e.g. 'https://example.com:250') and how to authenticate with the remote
server. :class:`nailgun.config.ServerConfig` eases the task of managing and
presenting that information.

"""
from os.path import isfile, join
from packaging.version import parse
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

    :param xdg_config_dir: A string. The name of the directory that is suffixed
        to the end of each of the ``XDG_CONFIG_DIRS`` paths.
    :param xdg_config_file: A string. The name of the configuration file that
        is being searched for.
    :returns: A ``str`` path to a configuration file.
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
    """A set of facts for communicating with a Satellite server.

    This object stores a set of facts that can be used when communicating with
    a Satellite server, regardless of whether that communication takes place
    via the API, CLI or UI. :class:`nailgun.config.ServerConfig` is more
    specialized and adds attributes that are useful when communicating with the
    API.

    :param url: A string. The URL of a server. For example:
        `'https://example.com:250'`.
    :param auth: Credentials to use when communicating with the server. For
        example: `('username', 'password')`. No instance attribute is created
        if no value is provided.
    :param version: A string, such as ``'6.0'`` or ``'6.1'``, indicating the
        Satellite version the server is running. This version number is parsed
        by ``packaging.version.parse`` before being stored locally. This allows
        for version comparisons:

        >>> from nailgun.config import ServerConfig
        >>> from packaging.version import parse
        >>> cfg = ServerConfig('http://sat.example.com', version='6.0')
        >>> cfg.version == parse('6.0')
        True
        >>> cfg.version == parse('6.0.0')
        True
        >>> cfg.version < parse('10.0')
        True
        >>> '6.0' < '10.0'
        False

        If no version number is provided, then no instance attribute is
        created, and it is assumed that the server is running an up-to-date
        nightly build.

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

    def __init__(self, url, auth=None, version=None):
        self.url = url
        if auth is not None:
            self.auth = auth
        if version is not None:
            self.version = parse(version)

    def __repr__(self):
        attrs = vars(self).copy()
        if 'version' in attrs:
            attrs['version'] = str(attrs.pop('version'))
        return '{0}.{1}({2})'.format(
            self.__module__,
            type(self).__name__,
            ', '.join(
                '{0}={1}'.format(key, repr(value))
                for key, value
                in attrs.items()
            )
        )

    @classmethod
    def delete(cls, label='default', path=None):
        """Delete a server configuration.

        This method is thread safe.

        :param label: A string. The configuration identified by ``label`` is
            deleted.
        :param path: A string. The configuration file to be manipulated.
            Defaults to what is returned by
            :func:`nailgun.config._get_config_file_path`.
        :returns: ``None``

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
        """Read a server configuration from a configuration file.

        :param label: A string. The configuration identified by ``label`` is
            read.
        :param path: A string. The configuration file to be manipulated.
            Defaults to what is returned by
            :func:`nailgun.config._get_config_file_path`.
        :returns: A brand new :class:`nailgun.config.BaseServerConfig` object
            whose attributes have been populated as appropriate.
        :rtype: BaseServerConfig

        """
        if path is None:
            path = _get_config_file_path(
                cls._xdg_config_dir,
                cls._xdg_config_file
            )
        with open(path) as config_file:
            return cls(**json.load(config_file)[label])

    @classmethod
    def get_labels(cls, path=None):
        """Get all server configuration labels.

        :param path: A string. The configuration file to be manipulated.
            Defaults to what is returned by
            :func:`nailgun.config._get_config_file_path`.
        :returns: Server configuration labels, where each label is a string.

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

        :param label: A string. An identifier for the current configuration.
            This allows multiple configurations with unique labels to be saved
            in a single file. If a configuration identified by ``label``
            already exists in the destination configuration file, it is
            replaced.
        :param path: A string. The configuration file to be manipulated. By
            default, an XDG-compliant configuration file is used. A
            configuration file is created if one does not exist already.
        :returns: ``None``

        """
        # What will we write out?
        cfg = vars(self)
        if 'version' in cfg:
            cfg['version'] = str(cfg['version'])

        # Where is the file we're writing to?
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
            config[label] = cfg
            with open(path, 'w') as config_file:
                json.dump(config, config_file)
        finally:
            self._file_lock.release()


class ServerConfig(BaseServerConfig):
    """Extend :class:`nailgun.config.BaseServerConfig`.

    This class adds functionality that is useful specifically when working with
    the API. For example, it stores the additional ``verify`` instance
    attribute and adds logic useful for presenting information to the methods
    in :mod:`nailgun.client`.

    :param verify: A boolean. Should SSL be verified when communicating with
        the server? No instance attribute is created if no value is provided.

    """
    # pylint:disable=too-few-public-methods
    # It's OK that this class has only one public method. This class is
    # intentionally small so that the parent class can be re-used.
    _xdg_config_dir = 'nailgun'
    _xdg_config_file = 'server_configs.json'

    def __init__(self, url, auth=None, version=None, verify=None):
        super(ServerConfig, self).__init__(url, auth, version)
        if verify is not None:
            self.verify = verify

    def get_client_kwargs(self):
        """Get kwargs for use with the methods in :mod:`nailgun.client`.

        This method returns a dict of attributes that can be unpacked and used
        as kwargs via the ``**`` operator. For example::

            cfg = ServerConfig.get()
            client.get(cfg.url + '/api/v2', **cfg.get_client_kwargs())

        This method is useful because client code may not know which attributes
        should be passed from a ``ServerConfig`` object to one of the
        ``nailgun.client`` functions. Consider that the example above could
        also be written like this::

            cfg = ServerConfig.get()
            client.get(cfg.url + '/api/v2', auth=cfg.auth, verify=cfg.verify)

        But this latter approach is more fragile. It will break if ``cfg`` does
        not have an ``auth`` or ``verify`` attribute.

        """
        config = vars(self).copy()
        config.pop('url')
        config.pop('version', None)
        return config

    @classmethod
    def get(cls, label='default', path=None):
        """Read a server configuration from a configuration file.

        This method extends :meth:`nailgun.config.BaseServerConfig.get`. Please
        read up on that method before trying to understand this one.

        The entity classes rely on the requests library to be a transport
        mechanism. The methods provided by that library, such as ``get`` and
        ``post``, accept an ``auth`` argument. That argument must be a tuple:

            Auth tuple to enable Basic/Digest/Custom HTTP Auth.

        However, the JSON decoder does not recognize a tuple as a type, and
        represents sequences of elements as a tuple. Compensate for that by
        converting ``auth`` to a two element tuple if it is a two element list.

        This override is done here, and not in the base class, because the base
        class may be extracted out into a separate library and used in other
        contexts. In those contexts, the presence of a list may not matter or
        may be desirable.

        """
        config = super(ServerConfig, cls).get(label, path)
        if hasattr(config, 'auth') and isinstance(config.auth, list):
            config.auth = tuple(config.auth)
        return config
