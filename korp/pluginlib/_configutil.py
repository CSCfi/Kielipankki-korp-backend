
"""
Module korp.pluginlib._configutil

Module of utility functions and definitions for plugin configuration.

This module is intended to be internal to the package korp.pluginlib; the names
intended to be visible outside the package are imported at the package level.
"""


import importlib

from types import SimpleNamespace

import config as korpconf

from ._util import get_plugin_name


# Try to import korp.pluginlib.config as _pluginlibconf; if not available,
# define _pluginlibconf as a SimpleNamespace. These are used to fill in the
# pluginlibconf SimpleNamespace below.
try:
    from . import config as _pluginlibconf
except ImportError:
    _pluginlibconf = SimpleNamespace()


# Default configuration values, if found neither in module korp.pluginlib.config
# nor config
_conf_defaults = SimpleNamespace(
    # Plugins are in package "korpplugins"
    PACKAGES = ["korpplugins"],
    # Search plugins only in the default ones
    SEARCH_PATH = [],
    # When loading, print plugin module names but not function names
    LOAD_VERBOSITY = 1,
    # Warn if a plugin is not found
    HANDLE_NOT_FOUND = "warn",
    # The last endpoint for a route overrides the preceding ones; if that
    # happens, print a warning
    HANDLE_DUPLICATE_ROUTES = "override,warn"
)


def _make_config(*configs, always_add=None):
    """Return a config object with values from configs.

    The returned object is a SimpleNamespace object that has a value for
    each attribute in *last* non-empty of configs, treated as defaults.
    The value is overridden by the corresponding value in the *first* of
    other configs that has an attribute with the same name. If an item
    in configs has an attribute that is not in the defaults (or
    always_add), it is ignored.

    Each configuration object is either a namespace-like object with
    attributes, in which case its __dict__ attribute is inspected, or
    a dictionary-like object whose keys can be iterated. Each item in
    configs is either such a configuration object directly or a pair
    (conf, prefix), where conf is the object and prefix is a string to
    be prefixed to attributes when searching from conf.

    The items in always_add (a dict or namespace) are added to the
    result even if the keys were not present in the defaults. Their
    values are those in always_add, unless a different value is
    specified in a configuration object.
    """
    # We need to handle the default configuration separately, as it lists the
    # available configuration attributes
    default_conf = {}
    other_confs = []
    # Loop over configs in the reverse order
    for conf in reversed(configs):
        bare_conf, prefix = conf if isinstance(conf, tuple) else (conf, "")
        conf_dict = _get_dict(bare_conf)
        if conf_dict:
            if not default_conf:
                # This is the last non-empty conf, so make it default
                if prefix:
                    # Use only prefixed keys and remove the prefix from the
                    # default keys
                    default_conf = dict((key[len(prefix):], val)
                                        for key, val in conf_dict.items()
                                        if key.startswith(prefix))
                else:
                    default_conf = conf_dict
                if always_add:
                    for key, val in _get_dict(always_add).items():
                        default_conf.setdefault(key, val)
            else:
                # Prepend non-defaults to other_confs: earlier ones have higher
                # priority, but they are later in the reversed list
                other_confs[:0] = [(conf_dict, prefix)]
    result_conf = SimpleNamespace(**default_conf)
    if other_confs:
        for attrname in default_conf:
            for conf, prefix in other_confs:
                try:
                    setattr(result_conf, attrname, conf[prefix + attrname])
                    # If a value was available, ignore the rest of configs
                    break
                except KeyError:
                    pass
    return result_conf


def _get_dict(obj):
    """Return a dictionary representation of obj."""
    return obj if isinstance(obj, dict) else obj.__dict__


# An object containing configuration attribute values. Values are checked first
# from the dictionary or namespace PLUGINLIB_CONFIG in the Korp configuration,
# then in korp.pluginlib.config, and finally the defaults in _conf_defaults.
pluginlibconf = _make_config(
    getattr(korpconf, "PLUGINLIB_CONFIG", {}),
    _pluginlibconf,
    _conf_defaults)


# Plugin configuration variables, added by add_plugin_config and possibly
# augmented by get_plugin_config (plugin name -> namespace)
plugin_configs = {}

# The names of plugins whose configurations in plugin_configs have already
# been expanded by get_plugin_config.
_plugin_configs_expanded = set()


def add_plugin_config(plugin_name, config):
    """Add config as the configuration of plugin plugin_name.

    The values in config will override those specified as defaults in
    the plugin or in the config module of the plugin.
    """
    global plugin_configs
    plugin_configs[plugin_name] = (
        SimpleNamespace(**config) if isinstance(config, dict) else config)


def get_plugin_config(defaults=None, **kw_defaults):
    """Get the configuration for the calling plugin, defaulting to defaults

    Return a namespace object with configuration variables as
    attributes. The attribute names are either the names of the keyword
    arguments kw_defaults or the keys or attributes of defaults, which
    can be either a dictionary- or namespace-like object. Values are
    taken from the first of the following three in which a value is
    found: (1) plugin configuration added using add_plugin_config
    (typically in the list of plugins to load); (2) the value of Korp's
    config.PLUGIN_CONFIG_PLUGINNAME (PLUGINNAME replaced with the name
    of the plugin in upper case); (3) "config" module for the plugin
    (package.plugin.config for sub-package plugins, package.config for
    module plugins), unless the plugin is a top-level module; and (4)
    defaults.

    If defaults is not specified or is empty and no keyword arguments
    are specified, the configuration variables and their default
    values are taken from the first non-empty of (3), (2) and (1),
    tried in this order.

    The function also assigns the result to plugin_configs[plugin].
    If the function is called again for the same plugin, it returns
    the same result as on the first call, even if the default keys
    were different.
    """
    if defaults is None:
        defaults = kw_defaults
    plugin, pkg, module = get_plugin_name(call_depth=2)
    # Assume module name package.plugin_package.module[.submodule...],
    # package.plugin_module or plugin_module
    if pkg:
        module_name_comps = module.__name__.split(".")
        # Module name does not contain ".__init__", so test it separately
        if len(module_name_comps) > 2 or "__init__.py" in module.__file__:
            # package.plugin_package.module[.submodule...]
            config_name = pkg + "." + plugin + ".config"
        else:
            # package.plugin_module
            config_name = pkg + ".config"
        # Import the configuration module if available
        try:
            plugin_config_mod = importlib.import_module(config_name)
        except ImportError:
            plugin_config_mod = SimpleNamespace()
    else:
        # plugin_module
        plugin_config_mod = SimpleNamespace()
    if plugin not in _plugin_configs_expanded:
        plugin_configs[plugin] = _make_config(
            plugin_configs.get(plugin, {}),
            getattr(korpconf, "PLUGIN_CONFIG_" + plugin.upper(), {}),
            plugin_config_mod,
            defaults or {},
            # Make RENAME_ROUTES configurable even if it has not been
            # given a default in the plugin
            always_add={"RENAME_ROUTES": None})
        _plugin_configs_expanded.add(plugin)
    return plugin_configs[plugin]
