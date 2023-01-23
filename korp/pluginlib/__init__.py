
"""
Package korp.pluginlib

A class- and Blueprint-based proposal for a plugin framework for the Korp
backend

The classes are mostly for encapsulation: although plugin callbacks are
instance methods, the instances are singletons. Registering plugin callbacks
(for CallbackPlugin subclasses) is handled in the metaclass, adapted from
or inspired by http://martyalchin.com/2008/jan/10/simple-plugin-framework/

WSGI endpoints are functions decorated with the route method of an instance of
korp.pluginlib.EndpointPlugin.
"""


# This package initialization file only imports from package-internal modules
# the names to be visible to the importing code; the actual implementation is
# in the internal modules.


# The following names are visible to the code importing korp.pluginlib
from ._configutil import get_plugin_config, plugin_configs
from ._endpointplugin import EndpointPlugin
from ._callbackplugin import CallbackPlugin, CallbackPluginCaller
from ._pluginloader import load_plugins, loaded_plugins, get_loaded_plugins
