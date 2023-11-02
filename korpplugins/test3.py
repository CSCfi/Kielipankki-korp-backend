
"""
korpplugins.test3

Korp test plugin: non-JSON endpoint.
"""


from korp import pluginlib, utils


PLUGIN_INFO = {
    "name": "korp.pluginlib test plugin 3 (non-JSON endpoint /text)",
    "version": "0.2",
    "date": "2023-10-31",
}


plugin = pluginlib.EndpointPlugin()


@plugin.route("/text")
@utils.main_handler
@utils.use_custom_headers
def text(args):
    """Return the arguments as text/plain

    If args contains "filename", add header "Content-Disposition:
    attachment" with the given filename.
    """
    result = {}
    result["content"] = "\n".join(arg + "=" + repr(args[arg]) for arg in args)
    result["mimetype"] = "text/plain"
    if "filename" in args:
        result["headers"] = [
            ("Content-Disposition",
             "attachment; filename=\"" + args["filename"] + "\"")]
    yield result
