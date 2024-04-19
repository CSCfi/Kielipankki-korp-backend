# -*- coding: utf-8 -*-

"""
The main module for exporting Korp search results to downloadable formats.

It should generally be sufficient to call func:`make_download_file` to
generate downloadable file contents.

:Author: Jyrki Niemi <jyrki.niemi@helsinki.fi> for FIN-CLARIN
:Date: 2014, 2024 (converted CGI script to a plugin)
"""




import os.path
import time
import pkgutil
import json
import importlib
import urllib.request, urllib.parse
import re

from collections import defaultdict

from korp import utils, pluginlib
from korp.views import info, query

from . import queryresult as qr


__all__ = ['make_download_file',
           'KorpExportError',
           'KorpExporter']


def make_download_file(args, korp_server_url, **kwargs):
    """Format Korp query results and return them in a downloadable format.

    Arguments:
        args (dict): Query string parameters
        korp_server_url (str): Korp server URL (for documentation)

    Keyword arguments:
        **kwargs: Passed to class:`KorpExporter` constructor and its
            method:`make_download_file`

    Returns:
        dict: The downloadable file content and meta information;
            contains the following information (strings):

            - download_content: The actual file content
            - download_charset: The character encoding of the file
              content
            - download_content_type: MIME type for the content
            - download_filename: Name of the file
    """
    exporter = KorpExporter(args, **kwargs)
    return exporter.make_download_file(korp_server_url, **kwargs)


class KorpExportError(Exception):

    """An exception class for errors in exporting Korp query results."""

    pass


class KorpExporter:

    """A class for exporting Korp query results to a downloadable file."""

    _FORMATTER_SUBPACKAGE = "format"
    """The `korpexport` subpackage containing actual formatter modules"""

    _filename_format_default = "korp_kwic_{cqpwords:.60}_{date}_{time}{ext}"
    """Default filename format"""

    def __init__(self, args, options=None, filename_format=None,
                 filename_encoding="utf-8", **kwargs):
        """Construct a KorpExporter.

        Arguments:
            args (dict): Query string parameters

        Keyword arguments:
            options (dict): Options passed to formatter
            filename_format (str): A format specification for the
                resulting filename; may contain the following format
                keys: cqpwords, start, end, date, time, ext
            filename_encoding (str): The encoding to use for the
                filename
        """
        self._args = args
        self._filename_format = (filename_format
                                 or args.get("filename_format")
                                 or self._filename_format_default)
        self._filename_encoding = filename_encoding
        self._opts = options or {}
        self._query_params = {}
        self._query_result = None
        self._formatter = None

    def make_download_file(self, korp_server_url, **kwargs):
        """Format query results and return them in a downloadable format.

        Arguments:
            korp_server_url (str): The Korp server URL (for
                documentation)

        Keyword arguments:
            args (dict): Use the parameters in here instead of those
                provided to the constructor
            **kwargs: Passed on to formatter

        Returns:
            dict: As described above in :func:`make_download_file`
        """
        result = {}
        if "args" in kwargs:
            self._args = kwargs["args"]
        self._formatter = self._formatter or self._get_formatter(**kwargs)
        self.process_query(korp_server_url)
        self._add_corpus_info(korp_server_url, self._query_result)
        self._debug_log("query-result", self._query_result)
        if "ERROR" in self._query_result:
            return self._query_result
        self._debug_log("formatter", self._formatter)
        result["download_charset"] = self._formatter.download_charset
        content = self._formatter.make_download_content(
            self._query_result, self._query_params, self._opts, **kwargs)
        if isinstance(content, str) and self._formatter.download_charset:
            content = content.encode(self._formatter.download_charset)
        result["download_content"] = content
        result["download_content_type"] = self._formatter.mime_type
        result["download_filename"] = self._get_filename()
        self._debug_log("result", repr(result))
        return result

    def _debug_log(self, key, value):
        """Write a debug log entry Kwicdownload-key: value.

        Calls callback plugin hook point `"log"` as defined in plugin
        "logger".
        """
        pluginlib.CallbackPluginCaller.raise_event_for_request(
            "log", "debug", "debug", f"Kwicdownload-{key}", value)

    def _get_formatter(self, **kwargs):
        """Get a formatter instance for the format specified in self._args.

        Keyword arguments:
            **kwargs: Passed to formatter constructor; "options"
                override the options passed to exporter constructor

        Returns:
            An instance of a korpexport.KorpExportFormatter subclass
        """
        format_name = self._args.get("format", "json").lower()
        subformat_names = self._args.get("subformat", [])
        if subformat_names:
            subformat_names = subformat_names.split(",")
        formatter_class = self._get_formatter_class(format_name)
        # Options passed to _get_formatter() override those passed to
        # the KorpExporter constructor
        opts = {}
        opts.update(self._opts)
        opts.update(kwargs.get("options", {}))
        kwargs["format"] = format_name
        kwargs["subformat"] = subformat_names
        kwargs["options"] = opts
        return formatter_class(**kwargs)

    def _get_formatter_class(self, format_names):
        """Get or construct a formatter class for the specified format.

        Arguments:
            format_names: Either a list of format name strings or a
                single string containing possibly several format names
                separated by a comma, semicolon, plus or space

        Returns:
            class: The formatter class for `format_names`.

        Raises:
            KorpExportError: If no formatter found for one of
                `format_names`

        For a single format name, returns the class as returned by
        method:`_find_formatter_class`. For multiple format names,
        finds the classes for each format and constructs a new class
        inheriting from each of them. The inheritance order is the
        reverse of the format names, so that the first format name can
        be considered as the main format which the subsequent formats
        may modify. For example, the main format may be a logical
        content format, for which the second format specifies a
        concrete representation: for example, a token per line content
        format represented as comma-separated values.
        """
        if isinstance(format_names, str):
            format_names = re.split(r"[,;+\s]+", format_names)
        if len(format_names) == 1:
            return self._find_formatter_class(format_names[0])
        else:
            format_names.reverse()
            base_classes = []
            # Find the base classes for the formatter class to be
            # constructed
            for format_name in format_names:
                base_classes.append(self._find_formatter_class(format_name))
            classname = "_" + "_".join(cls.__name__ for cls in base_classes)
            # First construct the class object (without methods), so
            # that we can refer to it in super() in the __init__()
            # method
            formatter_class = type(classname, tuple(base_classes), {})

            # Then define the function to be added as an __init__ method
            def __init__(self, **kwargs):
                super(formatter_class, self).__init__(**kwargs)

            # And finally add it to the formatter class as __init__
            setattr(formatter_class, "__init__", __init__)
            return formatter_class

    def _find_formatter_class(self, format_name):
        """Find a formatter class for the specified format.

        Arguments:
            format_name: The name of the format for which to find a
                formatter class

        Returns:
            class: The formatter class for `format_name`

        Raises:
            KorpExportError: If no formatter found for `format_name`

        Searches for a formatter in the classes of
        package:`korpexport.format` modules, and returns the first
        whose `format` attribute contains `format_name`.
        """
        pkgpath = os.path.join(os.path.dirname(__file__),
                               self._FORMATTER_SUBPACKAGE)
        for _, module_name, _ in pkgutil.iter_modules([pkgpath]):
            try:
                modname_full = ".".join([__name__.rpartition(".")[0],
                                         self._FORMATTER_SUBPACKAGE,
                                         module_name])
                module = importlib.import_module(modname_full)
                for name in dir(module):
                    try:
                        module_class = getattr(module, name)
                        if format_name in module_class.formats:
                            return module_class
                    except AttributeError as e:
                        pass
            except ImportError as e:
                continue
        raise KorpExportError("No formatter found for format '{0}'"
                              .format(format_name))

    def process_query(self, korp_server_url, query_params=None):
        """Get the query result in args or perform query via a Korp server.

        Arguments:
            korp_server_url (str): The Korp server URL (for
                documentation)
            query_params (dict): Korp query parameters

        If `self._args` contains `query_result`, use it. Otherwise use
        the result obtained by performing a query to the Korp server.
        (`korp_server_url` is only for including in the downloaded
        data.) The query parameters are retrieved from
        argument `query_params`, query argument `query_params` (as
        JSON) or the query parameters as a whole.

        Set a private attribute to contain the result, a dictionary
        converted from the JSON returned by Korp.
        """
        if "query_result" in self._args:
            query_result_json = self._args.get("query_result", "{}")
        else:
            if query_params:
                self._query_params = query_params
            elif "query_params" in self._args:
                self._query_params = json.loads(self._args.get("query_params"))
            else:
                self._query_params = self._args
            if "debug" in self._args and "debug" not in self._query_params:
                self._query_params["debug"] = self._args["debug"]
            # If the format uses structural information, add the
            # structs in param "show_struct" to "show", so that tokens
            # are associated with information on opening and closing
            # those structures. Param "show_struct" only gives us
            # struct attribute values for a whole sentence.
            if (self._formatter.structured_format
                and self._query_params.get("show_struct")):
                if self._query_params.get("show"):
                    self._query_params["show"] += (
                        "," + self._query_params["show_struct"])
                else:
                    self._query_params["show"] = self._query_params["show_struct"]
            self._debug_log("query-params", self._query_params)
            self._query_result = utils.generator_to_dict(
                query.query(self._query_params))
            # Support "sort" in format params even if not specified
            if "sort" not in self._query_params:
                self._query_params["sort"] = "none"
        # Query result with info is logged in make_download_file
        # self._debug_log("query-result-0", self._query_result)
        if "ERROR" in self._query_result or "kwic" not in self._query_result:
            return
        self._opts = self._extract_options(korp_server_url)
        self._debug_log("opts", self._opts)

    def _extract_options(self, korp_server_url=None):
        """Extract formatting options from args, affected by query params.

        Arguments:
            korp_server_url: The default Korp server URL; may be
                overridden by options on the query parameters.

        Returns:
            dict: The extracted options.

        Extract options from the query parameters: take the values of
        all parameters for which `_default_options` contains an option
        with the same name.

        In addition, the values of the query parameters `attrs` and
        `structs` control the attributes and structures to be shown in
        the result. Their values may be comma-separated lists of the
        following:

        - attribute or structure names;
        - ``*`` for those listed in the corresponding query parameter
          (`show` or `show_struct`);
        - ``+`` for all of those that actually occur in the
          corresponding query result structure; and
        - ``-attr`` for excluding the attribute or structure ``attr``
          (used following ``*`` or ``+``).
        """
        opts = {}

        def extract_show_opt(opt_name, query_param_name,
                             query_result_struct_name):
            """Set the show option opt_name based on query params and result.
            """
            if opt_name in self._args:
                vals = self._args.get(opt_name, "").split(",")
                new_vals = []
                for valnum, val in enumerate(vals):
                    if val in ["*", "+"]:
                        all_vals = (
                            self._query_params.get(query_param_name, "")
                            .split(","))
                        if val == "+":
                            add_vals = qr.get_occurring_attrnames(
                                self._query_result, all_vals,
                                query_result_struct_name)
                        else:
                            add_vals = all_vals
                        new_vals.extend(add_vals)
                    elif val.startswith("-"):
                        valname = val[1:]
                        if valname in new_vals:
                            new_vals.remove(valname)
                    else:
                        new_vals.append(val)
                opts[opt_name] = new_vals

        extract_show_opt("attrs", "show", "tokens")
        extract_show_opt("structs", "show_struct", "structs")
        for opt_name, default_val in self._formatter.get_options().items():
            opts[opt_name] = self._args.get(opt_name, default_val)
        if self._args.get("korp_url"):
            opts["korp_url"] = self._args.get("korp_url")
        # FIXME: This does not make sense to the user if
        # korp_server_url uses localhost.
        opts["korp_server_url"] = (korp_server_url
                                   or self._args.get("korp_server_url", ""))
        return opts

    def _add_corpus_info(self, korp_server_url, query_result):
        """Add information on the corpora to the query result.

        Retrieve info for each corpus in `query_result` from args and
        add the information as ``corpus_info`` to each hit in
        `query_result`.
        Also add ``corpus_config`` to each hit if available.
        """
        self._retrieve_corpus_info(korp_server_url)
        for query_hit in query_result["kwic"]:
            corpname = query_hit["corpus"].partition("|")[0].lower()
            query_hit["corpus_info"] = self._corpus_info.get(corpname)
            if self._corpus_config:
                query_hit["corpus_config"] = self._corpus_config[corpname]

    def _retrieve_corpus_info(self, korp_server_url):
        """Retrieve corpus info from args or from a Korp server.

        Retrieve corpus information and configuration first from
        `self._args` and then (for the corpus info only) from the Korp
        server `korp_server_url` (overriding the values on args),
        and fill `self._corpus_info` and `self._corpus_config` with
        them, corpus names as keys.

        For the corpus information on args, the query parameter
        ``corpus_info`` is preferred; if not available, use values in
        ``corpus_config``. These parameters need to be encoded in
        JSON.
        """
        self._corpus_info = defaultdict(dict)
        self._corpus_config = {}
        if "corpus_info" in self._args:
            self._corpus_info = json.loads(self._args["corpus_info"])
        elif "corpus_config" in self._args:
            self._corpus_config = json.loads(self._args["corpus_config"])
            self._corpus_info = dict(
                [(corpname.lower(), config.get("info"))
                 for corpname, config in self._corpus_config.items()])
            self._add_corpus_info_from_config()
        self._retrieve_corpus_info_from_server(korp_server_url)

    def _add_corpus_info_from_config(self):
        """Add corpus info items from corpus configuration information.

        Fill in `self._corpus_info` based on the values in
        `self._corpus_config` whose keys are specified by the query
        parameter ``corpus_config_info_keys`` or end in ``urn`` or
        ``url``. ``corpus_config_info_keys`` should be a string of
        comma-separated values.
        """
        config_info_items = (
            self._args["corpus_config_info_keys"].split(",")
            if "corpus_config_info_keys" in self._args
            else [])
        for corpname, config in self._corpus_config.items():
            corpname = corpname.lower()
            for confkey, confval in config.items():
                confkey = confkey.lower()
                if (confkey in ["urn", "url"] or confkey.endswith("_urn")
                    or confkey.endswith("_url")):
                    self._add_corpus_info_item(corpname, confkey, confval)
                elif confkey in config_info_items:
                    for subkey, subval in confval.items():
                        self._add_corpus_info_item(
                            corpname, confkey + "_" + subkey, subval)

    def _add_corpus_info_item(self, corpname, infoname, infovalue):
        """Add a corpus info item to `self._corpus_info`.

        Add to `self._corpus_info` for corpus `corpname` the
        information item `infoname` with value `infovalue`. If
        `infoname` contains an underscore, split the name at it and
        use the first part as the name of a substructure (`dict`)
        containing the second part as a key. `infoname` is lowercased.
        """
        infoname = infoname.lower()
        subinfoname = None
        if "_" in infoname:
            infoname, _, subinfoname = infoname.partition("_")
        if infoname not in self._corpus_info.setdefault(corpname, {}):
            self._corpus_info[corpname][infoname] = (
                {} if subinfoname else infovalue)
        if subinfoname:
            self._corpus_info[corpname][infoname][subinfoname] = infovalue

    def _retrieve_corpus_info_from_server(self, korp_server_url):
        """Retrieve corpus info from the server `korp_server_url`.

        Use the Korp server command `´info´´ to retrieve information
        available in the backend for all the corpora in the query
        results to be exported.
        """
        corpora = self._get_corpus_names()
        if not corpora:
            return
        korp_info_params = {'corpus': ','.join(corpora)}
        korp_corpus_info = utils.generator_to_dict(
            info.corpus_info(korp_info_params))
        for corpname, corpdata in (iter(korp_corpus_info.get("corpora", {})
                                        .items())):
            corpname = corpname.lower()
            corpinfo = corpdata.get("info", {})
            for infoname, infoval in corpinfo.items():
                self._add_corpus_info_item(corpname, infoname, infoval)

    def _get_corpus_names(self):
        """Return the names (ids) of corpora present in the query results.

        For parallel corpora, return all the names (ids) of all
        aligned corpora.
        """
        return set([corpname
                    for corpus_hit in self._query_result.get("kwic", [])
                    for corpname in corpus_hit["corpus"].split("|")])

    def _get_filename(self):
        """Return the filename for the result, from args or formatted.

        If args contains parameter `filename`, return it;
        otherwise format using `self._filename_format`. The filename
        format may contain the following keys (specified as
        ``{key}``):

        - date: Current date in *yyyymmdd* format
        - time: Current time in *hhmmss* format
        - ext: Filename extension, including the period
        - cqpwords: The words in the CQP query for the Korp result to
          be exported
        - start: The number of the first result
        - end: The number of the last result
        """
        # FIXME: Get a time first and then format it, to avoid the
        # unlikely possibility of date changing between formatting the
        # date and time.
        # TODO: User-specified date and time formatting
        return (self._args.get(
                "filename",
                self._filename_format.format(
                    date=time.strftime("%Y%m%d"),
                    time=time.strftime("%H%M%S"),
                    ext=self._formatter.filename_extension,
                    cqpwords=self._make_cqp_filename_repr(),
                    start=self._query_params.get("start", ""),
                    end=self._query_params.get("end", "")))
                .encode(self._filename_encoding))

    def _make_cqp_filename_repr(self, attrs=False, keep_chars=None,
                                replace_char='_'):
        """Make a representation of the CQP query for the filename

        Arguments:
            attrs (bool): Whether to include attribute names in the
                result (unimplemented)
            keep_chars (str): The (punctuation) characters to retain
                in the CQP query
            replace_char (str): The character with which to replace
                characters removed from the CQP query

        Returns:
            str: A representation of the CQP query
        """
        # TODO: If attrs is True, include attribute names. Could we
        # encode somehow the operator which could be != or contains?
        words = re.findall(r'\"((?:[^\\\"]|\\.)*?)\"',
                           self._query_params.get("cqp", ""))
        replace_chars_re = re.compile(
            r'[^\w' + re.escape(keep_chars or "") + ']+', re.UNICODE)
        return replace_char.join(replace_chars_re.sub(replace_char, word)
                                 for word in words)


# For testing: find formatter class for format "json".

if __name__ == "__main__":
    print(KorpExporter._find_formatter_class('json'))
