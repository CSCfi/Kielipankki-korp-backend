
"""
korpplugins.example2

Korp example plugin: a result wrapper as a stand-alone module.
"""


import traceback

from types import SimpleNamespace

from korp import pluginlib


PLUGIN_INFO = {
    "name": "korp.pluginlib example plugin 2",
    "version": "0.3",
    "date": "2023-11-02",
}


class Example2(pluginlib.CallbackPlugin):

    def filter_result(self, request, d):
        return {"wrap2": d}


class Example3(pluginlib.CallbackPlugin):

    """Print the arguments at all plugin mount points"""

    def enter_handler(self, request, args, starttime):
        print("enter_handler", request, args, starttime)

    def exit_handler(self, request, *args):
        print("exit_handler", request, *args)

    def error(self, request, error, exc):
        print("error", request, error, traceback.format_exception(*exc))

    def filter_args(self, request, args):
        print("filter_args", request, args)

    def filter_result(self, request, result):
        print("filter_result", request, result)

    def filter_cqp_input(self, request, cmd):
        print("filter_cqp_input", request, cmd)

    def filter_cqp_output(self, request, output):
        print("filter_cqp_output", request, output)

    def filter_sql(self, request, sql):
        print("filter_sql", request, sql)


class Example4a(pluginlib.CallbackPlugin):

    """A callback plugin that applies only to the "info" endpoint."""

    @classmethod
    def applies_to(cls, request_obj):
        return request_obj.endpoint == 'info.info'

    def enter_handler(self, request, args, starttime):
        print("enter_handler, info only")

    def filter_result(self, request, result):
        return {'info': result}


class Example4b(pluginlib.CallbackPlugin):

    """A callback plugin that applies only to all but the "info" endpoint."""

    @classmethod
    def applies_to(cls, request_obj):
        return request_obj.endpoint != 'info.info'

    def enter_handler(self, request, args, starttime):
        print("enter_handler, not info")


class StateExample(pluginlib.CallbackPlugin):

    """A callback plugin keeping state (starttime) across callbacks."""

    _data = {}

    def enter_handler(self, request, args, starttime):
        self._data[request] = data = SimpleNamespace()
        data.starttime = starttime
        print("StateExample.enter_handler: starttime =", starttime)

    def exit_handler(self, request, endtime, *rest):
        print("StateExample.exit_handler: starttime =",
              self._data[request].starttime, "endtime =", endtime)
        del self._data[request]
