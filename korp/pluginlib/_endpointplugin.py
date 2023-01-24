
"""
Module korp.pluginlib._endpointplugin

Module containing code for WSGI endpoint plugins

In plugin modules, functions decorated with the route method of an instance of
korp.pluginlib.EndpointPlugin (a subclass of flask.Blueprint) define new
WSGI endpoints.

This module is intended to be internal to the package korp.pluginlib; the names
intended to be visible outside the package are imported at the package level.
"""


import functools

import flask

from ._configutil import add_plugin_config, plugin_configs
from ._util import print_verbose, get_plugin_name


class EndpointPlugin(flask.Blueprint):

    """Blueprint modifying route() method.

    The constructor may be called with name and import_name as None,
    defaulting to the module name.
    """

    def __init__(self, name=None, import_name=None, *args, **kwargs):
        """Initialize with name and import_name defaulting to module name.

        If name is None, set it to import_name. If import_name is
        None, set it to the name of the calling module.
        """
        if import_name is None:
            plugin_name, _, module = get_plugin_name(call_depth=2)
            import_name = module.__name__
        if name is None:
            name = import_name
        # If plugin has no configuration, add one with RENAME_ROUTES
        # set to None
        if plugin_name not in plugin_configs:
            add_plugin_config(plugin_name, {"RENAME_ROUTES": None})
        self._plugin_name = plugin_name
        # Flask 2 seems not to allow "." in Blueprint name
        name = name.replace(".", "_")
        super().__init__(name, import_name, *args, **kwargs)

    def route(self, rule, **options):
        """Route with rule, renaming it if specified.

        Default to methods=["GET", "POST"].
        """

        def rename_rule(rule):
            """Rename routing rule according to RENAME_ROUTES in config.

            rule is without the leading slash.

            If RENAME_ROUTES for the plugin exists and is a string, it
            is used as a format string for the rule. If it is a dict,
            rule becomes RENAME_ROUTES.get(rule, rule). If it is a
            function (str) -> str, rule becomes RENAME_ROUTES(rule).
            """
            plugin_config = plugin_configs.get(self._plugin_name)
            if not plugin_config:
                return rule
            rename = getattr(plugin_config, "RENAME_ROUTES", None)
            if isinstance(rename, str):
                return rename.format(rule)
            elif isinstance(rename, dict):
                return rename.get(rule, rule)
            elif callable(rename):
                return rename(rule)
            else:
                return rule

        if "methods" not in options:
            options["methods"] = ["GET", "POST"]
        def decorator(func):
            nonlocal rule
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            rule = "/" + rename_rule(rule[1:])
            wrapped_func = functools.update_wrapper(
                super(EndpointPlugin, self).route(rule, **options)(wrapper),
                func)
            print_verbose(
                2, ("  route \"" + rule + "\": endpoint " + self.name + "."
                    + func.__qualname__))
            return wrapped_func
        return decorator
