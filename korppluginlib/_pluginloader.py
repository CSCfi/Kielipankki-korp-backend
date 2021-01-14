
"""
Module korppluginlib._pluginloader

Module containing the korppluginlib plugin loading function

This module is intended to be internal to the package korppluginlib; the names
intended to be visible outside the package are imported at the package level.
"""


import importlib
import sys

from collections import OrderedDict
from types import SimpleNamespace

from ._configutil import pluginlibconf, add_plugin_config, plugin_configs
from ._endpointplugin import KorpEndpointPlugin
from ._util import print_verbose, print_verbose_delayed


# The attributes of app_globals allows accessing the values of global
# application variables (and possibly functions) passed to load(), typically at
# least "app" and "mysql". Values to app_globals are added in load(), but it is
# initialized here, so that its value is correct when it is imported at the
# package level.
app_globals = SimpleNamespace()

# An ordered dictionary of loaded plugins: keys are plugin names, values dicts
# with the key "module" (the plugin module) and any keys from the PLUGIN_INFO
# dictionary of the plugin module in question, typically "name", "version" and
# "date". The dictionary is ordered by the order in which the plugins have been
# loaded.
loaded_plugins = OrderedDict()


def load(app, plugin_list, decorators=None, app_globals=None):
    """Load the plugins in the modules listed in plugin_list.

    Load the plugins in the modules listed in plugin_list by importing
    the modules within this package. app is the Flask application, and
    decorators are the (globally available) decorators for endpoints.
    (decorators must contain main_handler.) app_globals is a
    dictionary of global application variables to be made available as
    attributes of the module global app_globals.

    The items in plugin list may be either strings (plugin names) or
    pairs (plugin name, config) where config is a dictionary- or
    namespace-like object containing values for configuration
    variables of the module. The values defined here override those in
    the possible config submodule of the plugin.
    """
    global loaded_plugins
    if not decorators or not any(decor.__name__ == "main_handler"
                                 for decor in decorators):
        raise ValueError("decorators must contain main_handler")
    KorpEndpointPlugin.add_endpoint_decorators(decorators)
    app_globals = app_globals or {}
    global_app_globals = globals()["app_globals"]
    for name, val in app_globals.items():
        setattr(global_app_globals, name, val)
    saved_sys_path = sys.path
    sys.path.extend(pluginlibconf.SEARCH_PATH)
    for plugin in plugin_list:
        # Add possible configuration
        if isinstance(plugin, tuple) and len(plugin) > 1:
            add_plugin_config(plugin[0], plugin[1])
            plugin = plugin[0]
        try:
            module = _find_plugin(plugin)
            # Add plugin information to loaded_plugins
            loaded_plugins[plugin] = {"module": module}
            try:
                loaded_plugins[plugin].update(module.PLUGIN_INFO)
            except AttributeError as e:
                pass
            load_msg = ("Loaded Korp plugin \"" + plugin + "\" ("
                        + module.__name__ + ")")
            if pluginlibconf.LOAD_VERBOSITY > 0:
                descr = ""
                for key, fmt in [
                    ("name", "{val}"),
                    ("version", "version {val}"),
                    ("date", "{val}"),
                ]:
                    val = loaded_plugins[plugin].get(key)
                    if val:
                        descr += (", " if descr else "") + fmt.format(val=val)
                if descr:
                    load_msg += ": " + descr
            if plugin in plugin_configs:
                print_verbose(2, "  configuration:", plugin_configs[plugin])
            print_verbose(1, load_msg, immediate=True)
            # Print the verbose messages collected when loading the plugin
            # module
            print_verbose_delayed()
        except ModuleNotFoundError as e:
            if pluginlibconf.HANDLE_NOT_FOUND == "ignore":
                continue
            msg_base = "Plugin \"" + plugin + "\" not found:"
            if pluginlibconf.HANDLE_NOT_FOUND == "warn":
                print("Warning:", msg_base, e, file=sys.stderr)
            else:
                print(msg_base, file=sys.stderr)
                raise
    sys.path = saved_sys_path
    KorpEndpointPlugin.register_all(app)
    _handle_duplicate_routing_rules(app)


def _find_plugin(plugin):
    """Return the imported module for plugin or raise ModuleNotFoundError.

    Try to import module plugin from the packages listed in
    pluginlibconf.PACKAGES and return the first one found. If no
    module of the name was found, raise ModuleNotFoundError with a
    message showing the tried (fully-qualified) module names and
    directories.
    """
    module = None
    not_found = []
    for pkg in pluginlibconf.PACKAGES:
        module_name = pkg + "." + plugin if pkg else plugin
        try:
            return importlib.import_module(module_name)
        except ModuleNotFoundError as e:
            not_found.append("'" + module_name + "'")
    if len(not_found) == 1:
        not_found_str = not_found[0]
    else:
        not_found_str = ", ".join(not_found[:-1]) + " nor " + not_found[-1]
    raise ModuleNotFoundError(
        "No module named " + not_found_str + " in any of "
        + ", ".join((dir or ".") for dir in sys.path))


def _handle_duplicate_routing_rules(app):
    """Handle duplicate routing rules according to HANDLE_DUPLICATE_ROUTES.

    If app contains duplicate routing rules (added by plugins), handle
    them as specified by  pluginlibconf.HANDLE_DUPLICATE_ROUTES:
      "override": use the endpoint defined last without printing anything,
          allowing a plugin to override a built-in endpoint; if multiple
          plugins define an endpoint for the same route, the last one is
          used
      "override,warn": use the last endpoint and print a warning to stderr
      "ignore": use the endpoint defined first (Flask default behaviour)
          without printing anything
      "warn": use the endpoint defined first (Flask default) and print a
          warning message to stderr
      "error": print an error message to stderr and raise ValueError
    """
    handle_mode = pluginlibconf.HANDLE_DUPLICATE_ROUTES
    if "override" in handle_mode:
        _remove_duplicate_routing_rules(app)
    elif handle_mode in ("warn", "error"):
        dupls = _find_key_duplicates(app.url_map.iter_rules())
        if dupls:
            for rule_name, rules in dupls.items():
                msg_base = (
                    "Multiple endpoints for routing rule \"" + rule_name + "\"")
                if handle_mode == "warn":
                    msg = ("Warning: " + msg_base + ": using the first ("
                           + rules[0].endpoint + "), discarding the rest ("
                           + ", ".join(rule.endpoint for rule in rules[1:])
                           + ")")
                else:
                    msg = (msg_base + ": "
                           + ", ".join(rule.endpoint for rule in rules))
                print(msg, file=sys.stderr)
            if handle_mode == "error":
                raise ValueError(
                    "Multiple endpoints for a routing rule")


def _find_key_duplicates(iterable, key_func=str):
    """Return OrderedDict with lists of duplicates in iterable by key_func.

    Return an OrderedDict containing lists of values in iterable with
    the same value returend by key_func(value). The keys in the return
    value are those returned by key_func. Keys with a single value are
    omitted, so each list in the returned value contains at least two
    items.
    """
    item_dict = OrderedDict()
    for item in iterable:
        item_key = key_func(item)
        if item_key not in item_dict:
            item_dict[item_key] = []
        item_dict[item_key].append(item)
    # Remove keys with only a single item; done this way, as we cannot delete
    # from a dictionary while iterating over it.
    for item_key in [item_key for item_key, items in item_dict.items()
                     if len(items) == 1]:
        del item_dict[item_key]
    return item_dict


def _remove_duplicate_routing_rules(app):
    """Remove duplicate routing rules from app, keeping only the last one.

    If a route has duplicate rules, keep only the last one (most
    recently added?) of them, so that a plugin can override an
    endpoint.

    This requires using non-public attributes in Flask objects
    (app.url_map._rules, ._rules_by_endpoint and ._remap), so this may
    break if they are changed; see
    https://stackoverflow.com/a/24137773
    """
    url_map = app.url_map
    dupls = _find_key_duplicates(url_map.iter_rules())
    if dupls:
        for rule_name, rules in dupls.items():
            # Remove all the rules for a route except the last one
            for rule in rules[:-1]:
                # We need to remove the rule from both url.map._rules
                # and and url_map._rules_by_endpoint
                url_map._rules.remove(rule)
                url_map._rules_by_endpoint[rule.endpoint].remove(rule)
            if "warn" in pluginlibconf.HANDLE_DUPLICATE_ROUTES:
                print("Warning: Endpoint", rules[-1].endpoint,
                      "overrides endpoints defined earlier for routing rule \""
                      + rule_name + "\":",
                      ", ".join(rule.endpoint for rule in rules[:-1]),
                      file=sys.stderr)
        # Update the rule map
        url_map._remap = True
        url_map.update()


def get_loaded_plugins(names_only=False):
    """Return a list of loaded plugins, with PLUGIN_INFO unless names_only.

    If names_only, return a list of plugin names (as specified in
    PLUGINS). Otherwise, return a list of dicts with key "name" as the
    load name of the plugin and "info" the PLUGIN_INFO defined in the
    plugin, excluding key "module" added in load().
    """
    if names_only:
        return list(loaded_plugins.keys())
    else:
        return [
            {"name": name,
             "info": dict((key, val)
                          for key, val in info.items() if key != "module")}
            for name, info in loaded_plugins.items()
        ]
