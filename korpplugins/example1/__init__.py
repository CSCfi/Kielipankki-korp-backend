
"""
korpplugins.example1

Korp example plugin: endpoint /example and a result wrapper in a package.
"""


import functools

from korp import pluginlib, utils
# Rename info to views_info to avoid a clash with korpplugins.example1.info
from korp.views import info as views_info


pluginconf = pluginlib.get_plugin_config(
    ARGS_NAME = "args_default",
    WRAP_NAME = "wrap_default",
)


PLUGIN_INFO = {
    "name": "korp.pluginlib example plugin 1",
    "version": "0.3",
    "date": "2023-11-02",
}


example_plugin = pluginlib.EndpointPlugin()


def example_decor(generator):
    """An example of defining an extra decorator for WSGI endpoint plugins."""
    @functools.wraps(generator)
    def decorated(args=None, *pargs, **kwargs):
        for x in generator(args, *pargs, **kwargs):
            yield {"example_decor": "Endpoint decorated with example_decor",
                   "payload": x}
    return decorated


@example_plugin.route("/example")
@utils.main_handler
@example_decor
def example(args):
    """Yield arguments wrapped in ARGS_NAME."""
    yield {pluginconf["ARGS_NAME"]: args}


@example_plugin.route("/query")
@utils.main_handler
@example_decor
def query(args):
    """Yield arguments wrapped in ARGS_NAME."""
    yield {pluginconf["ARGS_NAME"]: args}


@example_plugin.route("/query")
@utils.main_handler
@example_decor
def query2(args):
    """Yield arguments wrapped in ARGS_NAME."""
    yield {pluginconf["ARGS_NAME"]: args}


@example_plugin.route("/count")
@utils.main_handler
@example_decor
def count(args):
    """Yield arguments wrapped in ARGS_NAME."""
    print("example1.count")
    yield {pluginconf["ARGS_NAME"]: args}


@example_plugin.route("/count")
@utils.main_handler
@example_decor
def count2(args):
    """Yield arguments wrapped in ARGS_NAME."""
    print("example1.count2")
    yield {pluginconf["ARGS_NAME"]: args}


@example_plugin.route("/info1")
@utils.main_handler
@example_decor
def info1(args):
    """Yield arguments wrapped in ARGS_NAME, result of /info in "result".

    This is an example of calling the view function of an existing
    endpoint from the one of a new endpoint.
    """
    print("example1.info1")
    yield {pluginconf["ARGS_NAME"]: args,
           "result": next(views_info.info(args))}


class Example1b(pluginlib.CallbackPlugin):

    def filter_result(self, request, d):
        """Wrap the result dictionary in WRAP_NAME and add "endpoint"."""
        return {"endpoint": request.endpoint,
                pluginconf["WRAP_NAME"]: d}
