
"""
Module korp.pluginlib._configutil

Module of utility functions and definitions for plugin configuration.

This module is intended to be internal to the package korp.pluginlib; the names
intended to be visible outside the package are imported at the package level.
"""


import importlib

from difflib import get_close_matches

from flask import current_app as app

from ._util import get_plugin_name


# Default configuration values, if not found in config; please see
# README.md for more details
_conf_defaults = dict(
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
    HANDLE_DUPLICATE_ROUTES = "override,warn",
)

# Plugin configuration variables, added by add_plugin_config and possibly
# augmented by get_plugin_config (plugin name -> dict)
plugin_configs = {}

# The names of plugins whose configurations in plugin_configs have already
# been expanded by get_plugin_config.
_plugin_configs_expanded = set()


class ConfigKeyError(KeyError):

    """Error class for reporting uknown configuration variables."""

    pass


def init_pluginlib_config():
    """Initialize plugin and pluginlib config; return pluginlib config.

    Note that this needs to be called within Flask application context.
    """
    # If PLUGINLIB_CONFIG is not configured, set it to _conf_defaults
    app.config.setdefault("PLUGINLIB_CONFIG", _conf_defaults)
    # Empty PLUGINS_CONFIG by default
    app.config.setdefault("PLUGINS_CONFIG", {})
    # An object containing configuration values. Values are checked
    # first from the dict PLUGINLIB_CONFIG in the Korp configuration,
    # and then in the defaults in _conf_defaults.
    pluginlibconf = _make_config(
        app.config.get("PLUGINLIB_CONFIG", {}),
        _conf_defaults)
    app.config["PLUGINLIB_CONFIG"] = pluginlibconf
    return pluginlibconf


def _make_config(*configs, always_add=None, plugin="", config_descrs=None):
    """Return a config object with values from configs.

    The returned object is a dict that has a value for each key in
    *last* non-empty of configs, treated as defaults. The value is
    overridden by the corresponding value in the *first* of other
    configs that has a key with the same name. If an item in configs
    has a key that is not in the defaults (or always_add), it is
    ignored.

    Each configuration object in configs is a dictionary-like object
    whose keys can be iterated.

    The items in always_add (a dict) are added to the result even if
    the keys were not present in the defaults. Their values are those
    in always_add, unless a different value is specified in a
    configuration object.

    plugin is the name of the plugin, and config_descrs is a list of
    descriptions of the configurations in the order they are in
    configs, both for an error message.
    """
    config_descrs = config_descrs or []
    # We need to handle the default configuration separately, as it lists the
    # available configuration keys
    default_conf = {}
    other_confs = []
    # The descriptions of configs in other_confs from config_descrs
    other_conf_descrs = []

    def make_error_msg(key, confnum):
        """Construct error message for key in configs[confnum]."""
        msg = f"Plugin {plugin}: Unknown configuration key" f" \"{key}\""
        if other_conf_descrs[confnum]:
            msg += f" in {other_conf_descrs[confnum]}"
        msg += ". "
        supported_keys = default_conf.keys()
        nearby_keys = get_close_matches(key, supported_keys)
        if nearby_keys:
            msg += "Did you mean "
            if len(nearby_keys) > 1:
                msg += "one of "
            msg += ", ".join(f"\"{k}\"" for k in nearby_keys)
            msg += "?"
        else:
            msg += "The supported ones are: "
            msg += ", ".join(f"\"{k}\"" for k in sorted(supported_keys)) + "."
        return msg

    # Loop over configs in the reverse order
    for confnum, conf in reversed(list(enumerate(configs))):
        if conf:
            if not default_conf:
                # This is the last non-empty conf, so make it default
                default_conf = conf
                if always_add:
                    for key, val in always_add.items():
                        default_conf.setdefault(key, val)
            else:
                # Prepend non-defaults to other_confs: earlier ones have higher
                # priority, but they are later in the reversed list
                other_confs[:0] = [conf]
                try:
                    other_conf_descrs[:0] = [config_descrs[confnum]]
                except IndexError:
                    other_conf_descrs[:0] = [""]
    result_conf = default_conf
    if other_confs:
        for key in default_conf:
            for conf in other_confs:
                if key in conf:
                    result_conf[key] = conf[key]
                    # If a value was available, ignore the rest of configs
                    break
        for confnum, conf in enumerate(other_confs):
            for key in conf:
                if key not in default_conf:
                    raise ConfigKeyError(make_error_msg(key, confnum))
    return result_conf


def add_plugin_config(plugin_name, config):
    """Add config as the configuration of plugin plugin_name.

    The values in config will override those specified as defaults in
    the plugin.
    """
    global plugin_configs
    plugin_configs[plugin_name] = config


def get_plugin_config(plugin=None, defaults=None, **kw_defaults):
    """Get the configuration for (the calling) plugin, defaulting to defaults

    If plugin is None, return the plugin configuration for the calling
    plugin (as found by get_plugin_name), otherwise for the named
    plugin.

    Return a dict with configuration variables as keys. The keys are
    either the names of the keyword arguments kw_defaults or the keys
    of defaults (a dict-like object). Values are taken from the first
    of the following three in which a value is found: (1) plugin
    configuration added using add_plugin_config (typically in the list
    of plugins to load); (2) the value of
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
            always_add={"RENAME_ROUTES": None},
            plugin=plugin,
            config_descrs=[
                f"PLUGINS[\"{plugin}\"][1]",
                f"PLUGINS_CONFIG[\"{plugin}\"]",
                "",
            ])
        _plugin_configs_expanded.add(plugin)
        app.config["PLUGINS_CONFIG"][plugin] = plugin_configs[plugin]
    return plugin_configs[plugin]
