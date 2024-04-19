# -*- coding: utf-8 -*-

"""
A Korp backend plugin implementing endpoint "/kwic_download" to export
Korp search results to downloadable formats.

The plugin uses modules in the korpexport package to do most of the
work.

The following query string parameters are recognized and used by the
script, in addition to those common to all endpoints:
    query_params (JSON): parameters to the `/query` endpoint for
        generating a query result; if specified, `/query` is called to
        generate the result
    query_result (JSON): The Korp query result to format; overrides
        `query_params`
    format (string): The format to which to convert the result;
        default: ``json`` (JSON)
    filename_format (string): A format specification for the
        (suggested) name of the file to generate; may contain the
        following format keys: ``cqpwords``, ``start``, ``end``,
        ``date``, ``time``, ``ext``; default:
        ``korp_kwic_{cqpwords}_{date}_{time}.{ext}``
    filename (string): The (suggested) name of the file to generate;
        overrides `filename_format`
    korp_server (URL): The Korp server used (for documentation only)
    
The script requires at least one of the parameters `query_params` and
`query_result` to make the search result for downloading.

Additional parameters are recognized by formatter modules.

To write a formatter for a new format, add a corresponding module to
the package `.korpexport.format`. Please see
:mod:`.korpexport.formatter` for more information.

:Author: Jyrki Niemi <jyrki.niemi@helsinki.fi> for FIN-CLARIN
:Date: 2014, 2024 (converted CGI script to a plugin)
"""


import urllib.parse

from flask import request

from .korpexport import exporter as ke

from korp import pluginlib, utils


pluginconf = pluginlib.get_plugin_config(
    # The default URL for a URN resolver, to be prefixed to URN links in
    # the exported content; may be overridden by the query parameter
    # "urn_resolver"
    URN_RESOLVER = "",
)


plugin = pluginlib.EndpointPlugin()


@plugin.route("/kwic_download")
@utils.main_handler
@utils.use_custom_headers
def kwic_download(args):
    """Generate downloadable data from a KWIC based on `args`.

    Invokes :func:`.korpexport.exporter.make_download_file` to generate
    downloadable content.
    """

    result = ke.make_download_file(
        args,
        request.host_url,
        urn_resolver=args.get("urn_resolver", pluginconf["URN_RESOLVER"]))
    # Print HTTP header and content
    content_type, headers = make_headers(result)
    content = result.get("download_content")
    yield {
        "content": content,
        "content_type": content_type,
        "headers": headers,
    }


def make_headers(obj):
    """Return content type and other HTTP headers based on `obj`.

    Arguments:
        obj (dict): The downloadable file contents and information
            about it; may contain the following keys that affect the
            output headers:

            - download_content_type => Content-Type (default:
              ``text/plain``)
            - download_charset => Charset (default: utf-8)
            - download_filename => Content-Disposition filename
            - download_content => Length of the content to
              Content-Length

    Returns:
        str: Content-Type
        list[(str, str)]: Other HTTP headers as a list of pairs
            (header, value).
    """
    charset = obj.get("download_charset")
    content_type = (obj.get("download_content_type", "text/plain")
                    + (("; charset=" + charset) if charset else ""))
    headers = [
        make_content_disposition_attachment(
            obj.get("download_filename", "korp_kwic")),
        ("Content-Length", str(len(obj["download_content"]))),
    ]
    return content_type, headers


def make_content_disposition_attachment(filename):
    """Return a HTTP Content-Disposition header with attachment filename.

    Arguments:
        filename (str): The file name to use for the attachment

    Returns:
        str: A HTTP ``Content-Disposition`` header for an attachment
            with a parameter `filename` with a value `filename`

    If `filename` contains non-ASCII characters, encode it in UTF-8 as
    specified in RFC 5987 to the `Content-Disposition` header
    parameter `filename*`, as shown in a `Stackoverflow discussion`_.
    For a wider browser support, also provide a `filename` parameter
    with the encoded filename. According to the discussion, this does
    not work with IE prior to version 9 and Android browsers.
    Moreover, at least Firefox 28 on Linux seems save an empty file
    with the corresponding Latin-1 character in its name, in addition
    to the real file.

    .. _Stackoverflow discussion: http://stackoverflow.com/questions/93551/how-to-encode-the-filename-parameter-of-content-disposition-header-in-http
    """
    filename = urllib.parse.quote(filename)
    return ("Content-Disposition",
            ("attachment; "
             + (f"filename*=UTF-8''{filename}; " if "%" in filename else "")
             + f"filename={filename}"))
