
"""
Module korp.pluginlib._callbackplugin

Module containing code for callback plugins to be called at hook points

The classes are mostly for encapsulation: although the callbacks are instance
methods, the instances are singletons. Registering callbacks in
CallbackPlugin subclasses is handled in the metaclass, adapted from or
inspired by http://martyalchin.com/2008/jan/10/simple-plugin-framework/ .

This module is intended to be internal to the package korp.pluginlib; the names
intended to be visible outside the package are imported at the package level.
"""


from collections import defaultdict

from flask import request as flask_request

from ._util import print_verbose


class Singleton(type):

    """A metaclass for singleton classes

    https://stackoverflow.com/a/6798042
    """

    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class CallbackPluginMetaclass(Singleton):

    """Metaclass for CallbackPlugin, registering callbacks

    This metaclass takes care of registering the callback methods in the
    plugin classes (subclasses of CallbackPlugin); see
    http://martyalchin.com/2008/jan/10/simple-plugin-framework/
    """

    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, "_callbacks"):
            # This executes when initializing the base class for the
            # first time
            cls._callbacks = defaultdict(list)
            # Methods defined in the base class are not callback methods:
            # record them here so that they can be excluded when registering
            # callback methods in subclasses
            cls._base_methods = [name for name in attrs]
            # List of subclasses
            cls._subclasses = []
        else:
            # This executes in subclasses
            # Create class instance
            cls._subclasses.append(cls)
            inst = cls()
            for name in dir(inst):
                attr = getattr(inst, name)
                if (name[0].islower() and callable(attr)
                        and name not in cls._base_methods):
                    cls._callbacks[name].append((attr, inst.applies_to))
                    print_verbose(
                        2, ("  hook point \"" + name
                            + "\": callback " + attr.__qualname__))


class CallbackPlugin(metaclass=CallbackPluginMetaclass):

    """Base class for callback plugins

    Actual callback plugin classes are subclasses of this class, with
    callbacks as instance methods. All methods whose names begin with a
    lowercase letter are treated as callback methods for the hook point
    of the method name.
    """

    @classmethod
    def applies_to(cls, request):
        """Return True if the plugin should be applied to request.

        This method always returns True, so it should be overridden in
        callback plugin classes which restrict their applicability
        based on Flask request information, typically the endpoint.
        """
        return True


class CallbackPluginCaller:

    """Class for calling plugin callbacks at named hook points.

    This class should be instantiated once for each Flask request. The
    call methods take care of passing the actual request object to the
    callback methods, so that it need not be specified at every call.
    """

    # Instances of this class: dict[request object id,
    # CallbackPluginCaller]
    _instances = {}

    def __init__(self, request=None):
        """Initialize a CallbackPluginCaller with the given request.

        If request is None, use the object for the global request proxy.
        """
        self._request = self._get_request_obj(request)
        self._instances[id(self._request)] = self

    @staticmethod
    def _get_request_obj(request=None):
        """Return the actual non-proxy Request object for request.

        If request is None, get the object for the global request proxy.
        """
        request = request or flask_request
        try:
            return request._get_current_object()
        except AttributeError:
            return request

    @classmethod
    def get_instance(cls, request=None):
        """Get the class instance for request.

        If request is None, get the instance for the global request proxy.
        """
        request_obj = cls._get_request_obj(request)
        return cls._instances[id(request_obj)]

    def cleanup(self):
        """Clean up when this CallbackPluginCaller is no longer used."""
        # Remove self from _instances
        del self._instances[id(self._request)]

    def raise_event(self, hook_point, *args, **kwargs):
        """Raise the event hook_point, discarding callback return values.

        Call the callback methods registered for the event hook point
        hook_point with args and kwargs in sequence, discarding return
        values. Callback methods in plugin classes whose applies_to
        method returns false for the current request are skipped.
        """
        for callback, applies_to in (CallbackPlugin
                                    ._callbacks.get(hook_point, [])):
            if applies_to(self._request):
                callback(self._request, *args, **kwargs)

    def get_values(self, hook_point, *args, **kwargs):
        """Get the values returned by the callbacks for hook_point as a list.

        Call the callback methods registered for hook_point with args
        and kwargs in sequence, collect their return values to a list
        and return it. Return values None are ignored. Callback
        methods in plugin classes whose applies_to method returns
        false for the current request are skipped.
        """
        result = []
        for callback, applies_to in (CallbackPlugin
                                     ._callbacks.get(hook_point, [])):
            if applies_to(self._request):
                retval = callback(self._request, *args, **kwargs)
                if retval is not None:
                    result.append(retval)
        return result

    def filter_value(self, hook_point, arg1, *args, **kwargs):
        """Filter arg1 through the callbacks for hook_point.

        Return the value of arg1 as passed through the filtering
        callback methods registered for the filter hook point
        hook_point, with the return value of the preceding callback as
        the arg1 value of the following one, unless it is None, in
        which case arg1 is kept as is. *args and **kwargs are passed
        to each callback method as they are. Callback methods in
        plugin classes whose applies_to method returns false for the
        current request are skipped.

        This can be thought of as applying successive filters,
        function composition for the callbacks, or a reduce operation
        for functions ("freduce").
        """
        for callback, applies_to in (CallbackPlugin
                                     ._callbacks.get(hook_point, [])):
            if applies_to(self._request):
                retval = callback(self._request, arg1, *args, **kwargs)
                if retval is not None:
                    arg1 = retval
        return arg1

    @classmethod
    def raise_event_for_request(cls, hook_point, *args, request=None, **kwargs):
        """Call the callbacks for hook_point for request.

        If request is None, use the global request proxy.
        """
        cls.get_instance(request).raise_event(hook_point, *args, **kwargs)

    @classmethod
    def get_values_for_request(cls, hook_point, *args, request=None,
                               **kwargs):
        """Call the callbacks for hook_point for request, collecting to a list.

        If request is None, use the global request proxy.
        """
        return cls.get_instance(request).get_values(
            hook_point, *args, **kwargs)

    @classmethod
    def filter_value_for_request(cls, hook_point, arg1, *args, request=None,
                                **kwargs):
        """Call the callbacks for hook_point for request, passing return value.

        If request is None, use the global request proxy.
        """
        return cls.get_instance(request).filter_value(
            hook_point, arg1, *args, **kwargs)
