
"""
korpplugins.test1

Korp test plugin for an object- and Blueprint-based plugin proposal: endpoint
/test and a result wrapper in a package with a separate configuration module.
"""


import functools

import korppluginlib


pluginconf = korppluginlib.get_plugin_config(
    ARGS_NAME = "args_default",
    WRAP_NAME = "wrap_default",
)


PLUGIN_INFO = {
    "name": "korppluginlib test plugin 1",
    "version": "0.1",
    "date": "2020-12-10",
}


test_plugin = korppluginlib.KorpEndpointPlugin()


@test_plugin.endpoint_decorator
def test_decor(generator):
    """A decorator for testing specifying extra decorators in WSGI
    endpoint plugins."""
    @functools.wraps(generator)
    def decorated(args=None, *pargs, **kwargs):
        for x in generator(args, *pargs, **kwargs):
            yield {"test_decor": "Endpoint decorated with test_decor",
                   "payload": x}
    return decorated


@test_plugin.route("/test", extra_decorators=["test_decor"])
def test(args):
    """Yield arguments wrapped in ARGS_NAME."""
    yield {pluginconf.ARGS_NAME: args}


@test_plugin.route("/query", extra_decorators=["test_decor"])
def query(args):
    """Yield arguments wrapped in ARGS_NAME."""
    yield {pluginconf.ARGS_NAME: args}


@test_plugin.route("/query", extra_decorators=["test_decor"])
def query2(args):
    """Yield arguments wrapped in ARGS_NAME."""
    yield {pluginconf.ARGS_NAME: args}


@test_plugin.route("/count", extra_decorators=["test_decor"])
def count(args):
    """Yield arguments wrapped in ARGS_NAME."""
    yield {pluginconf.ARGS_NAME: args}


@test_plugin.route("/count", extra_decorators=["test_decor"])
def count2(args):
    """Yield arguments wrapped in ARGS_NAME."""
    yield {pluginconf.ARGS_NAME: args}


class Test1b(korppluginlib.KorpCallbackPlugin):

    def filter_result(self, request, d):
        """Wrap the result dictionary in WRAP_NAME and add "endpoint"."""
        return {"endpoint": request.endpoint,
                pluginconf.WRAP_NAME: d}
