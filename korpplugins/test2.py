
"""
korpplugins.test2

Korp test plugin for an object-based plugin proposal: a result wrapper as a
stand-alone module.
"""


import traceback

from types import SimpleNamespace

import korppluginlib


PLUGIN_INFO = {
    "name": "korppluginlib test plugin 2",
    "version": "0.1",
    "date": "2020-12-10",
}


class Test2(korppluginlib.KorpCallbackPlugin):

    def filter_result(self, request, d):
        return {"wrap2": d}


class Test3(korppluginlib.KorpCallbackPlugin):

    """Print the arguments at all plugin mount points"""

    def enter_handler(self, request, args, starttime):
        print("enter_handler", request, args, starttime)
        print("app_globals:", korppluginlib.app_globals)

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


class Test4a(korppluginlib.KorpCallbackPlugin):

    """A callback plugin that applies only to the "info" endpoint."""

    @classmethod
    def applies_to(cls, request_obj):
        return request_obj.endpoint == 'info'

    def enter_handler(self, request, args, starttime):
        print("enter_handler, info only")

    def filter_result(self, request, result):
        return {'info': result}


class Test4b(korppluginlib.KorpCallbackPlugin):

    """A callback plugin that applies only to all but the "info" endpoint."""

    @classmethod
    def applies_to(cls, request_obj):
        return request_obj.endpoint != 'info'

    def enter_handler(self, request, args, starttime):
        print("enter_handler, not info")


class StateTest(korppluginlib.KorpCallbackPlugin):

    """A callback plugin keeping state (starttime) across callbacks."""

    _data = {}

    def enter_handler(self, request, args, starttime):
        self._data[request] = data = SimpleNamespace()
        data.starttime = starttime
        print("StateTest.enter_handler: starttime =", starttime)

    def exit_handler(self, request, endtime, *rest):
        print("StateTest.exit_handler: starttime =",
              self._data[request].starttime, "endtime =", endtime)
        del self._data[request]
