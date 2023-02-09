
"""
Module korp.pluginlib._configutil

Module of utility functions and definitions for plugin configuration.

This module is intended to be internal to the package korp.pluginlib; the names
intended to be visible outside the package are imported at the package level.
"""


import importlib

from types import SimpleNamespace

from flask import current_app as app

from ._util import get_plugin_name


# Default configuration values, if not found in config; please see
# README.md for more details
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

# Plugin configuration variables, added by add_plugin_config and possibly
# augmented by get_plugin_config (plugin name -> dict)
plugin_configs = {}

# The names of plugins whose configurations in plugin_configs have already
# been expanded by get_plugin_config.
_plugin_configs_expanded = set()


def init_pluginlib_config():
    """Initialize plugin and pluginlib config; return pluginlib config.

    Note that this needs to be called within Flask application context.
    """
    # If PLUGINLIB_CONFIG is not configured, set it to _conf_defaults
    app.config.setdefault("PLUGINLIB_CONFIG", _conf_defaults)
    # Empty PLUGINS_CONFIG by default
    app.config.setdefault("PLUGINS_CONFIG", {})
    # An object containing configuration attribute values. Values are
    # checked first from the dictionary or namespace PLUGINLIB_CONFIG
    # in the Korp configuration, and then in the defaults in
    # _conf_defaults.
    pluginlibconf = _make_config(
        app.config.get("PLUGINLIB_CONFIG", {}),
        _conf_defaults)
    app.config["PLUGINLIB_CONFIG"] = pluginlibconf
    return pluginlibconf


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


def add_plugin_config(plugin_name, config):
    """Add config as the configuration of plugin plugin_name.

    The values in config will override those specified as defaults in
    the plugin.
    """
    global plugin_configs
    plugin_configs[plugin_name] = (
        SimpleNamespace(**config) if isinstance(config, dict) else config)


def get_plugin_config(plugin=None, defaults=None, **kw_defaults):
    """Get the configuration for (the calling) plugin, defaulting to defaults

    If plugin is None, return the plugin configuration for the calling
    plugin (as found by get_plugin_name), otherwise for the named
    plugin.

    Return a namespace object with configuration variables as
    attributes. The attribute names are either the names of the keyword
    arguments kw_defaults or the keys or attributes of defaults, which
    can be either a dictionary- or namespace-like object. Values are
    taken from the first of the following three in which a value is
    found: (1) plugin configuration added using add_plugin_config
    (typically in the list of plugins to load); (2) the value of
    app.config.PLUGINS_CONFIG["pluginname"] (where pluginname is the
    name of the plugin); and (3) defaults.

    If defaults is not specified or is empty and no keyword arguments
    are specified, the configuration variables and their default
    values are taken from the first non-empty of (2) and (1), tried in
    this order.

    The function also assigns the result to plugin_configs[plugin].
    If the function is called again for the same plugin, it returns
    the same result as on the first call, even if the default keys
    were different.
    """
    if defaults is None:
        defaults = kw_defaults
    if plugin is None:
        plugin, _, _ = get_plugin_name(call_depth=2)
    if plugin not in _plugin_configs_expanded:
        plugin_configs[plugin] = _make_config(
            plugin_configs.get(plugin, {}),
            app.config["PLUGINS_CONFIG"].get(plugin, {}),
            defaults or {},
            # Make RENAME_ROUTES configurable even if it has not been
            # given a default in the plugin
            always_add={"RENAME_ROUTES": None})
        _plugin_configs_expanded.add(plugin)
        app.config["PLUGINS_CONFIG"][plugin] = plugin_configs[plugin]
    return plugin_configs[plugin]
