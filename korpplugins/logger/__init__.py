
"""
korpplugins.logger

Simple logging plugin for the Korp backend

The plugin contains functions for the plugin mount points in korp.py. The
plugin uses Python's standard logging module.

Configuration variables for the plugin are specified in
korpplugins.logger.config.

Note that the plugin currently handles concurrent logging from multiple worker
processes (such as when running the Korp backend with Gunicorn) only by writing
their log entries to separate files, so the configuration variable
LOG_FILENAME_FORMAT should contain a placeholder for the process id ({pid}).
The separate files can be concatenated later manually.
"""


import hashlib
import logging
import os
import os.path
import time

import korppluginlib


# See config.py.template for more information on the configuration variables

pluginconf = korppluginlib.get_plugin_config(
    # Base directory for log files
    LOG_BASEDIR = "/v/korp/log/korp-py",
    # Log filename format string (for str.format())
    LOG_FILENAME_FORMAT = (
        "{year}{mon:02}{mday:02}/korp-{year}{mon:02}{mday:02}"
        "_{hour:02}{min:02}{sec:02}-{pid:06}.log"),
    # Default log level
    LOG_LEVEL = logging.INFO,
    # If True, change the log level to logging.DEBUG if the query parameters in
    # the HTTP request contain "debug=true".
    LOG_ENABLE_DEBUG_PARAM = True,
    # Log message format string using the percent formatting for
    # logging.Formatter.
    LOG_FORMAT = (
        "[korp.py %(levelname)s %(process)d:%(starttime_us)d @ %(asctime)s]"
        " %(message)s"),
    # Categories of information to be logged: all available are listed
    LOG_CATEGORIES = [
        "auth",
        "debug",
        "env",
        "load",
        "params",
        "referrer",
        "result",
        "times",
        "userinfo",
    ],
    # A list of individual log items to be excluded from logging.
    LOG_EXCLUDE_ITEMS = [],
)


class LevelLoggerAdapter(logging.LoggerAdapter):

    """
    A LoggerAdapter subclass with its own log level

    This class keeps its own log level, so different LevelLoggerAdapters
    for the same Logger may have different log levels. (In contrast,
    LoggerAdapter.setlevel delegates to Logger.setLevel, so calling it
    sets the level for all LoggerAdapters of the Logger instance, which
    is not desired here.)
    """

    def __init__(self, logger, extra, level=None):
        super().__init__(logger, extra)
        self._level = logger.getEffectiveLevel() if level is None else level

    def setLevel(self, level):
        self._level = level

    def getEffectiveLevel(self):
        return self._level

    def log(self, level, msg, *args, **kwargs):
        # LoggerAdapter.log calls logger.log, which re-checks isEnabledFor
        # based on the info in logger, so we need to redefine it to use
        # self._level here. The following is a combination of Logger.log and
        # LoggerAdapter.log, but calling self.isEnabledFor (of LoggerAdapter),
        # which in turn calls self.getEffectiveLevel (of this class).
        if not isinstance(level, int):
            if logging.raiseExceptions:
                raise TypeError("level must be an integer")
            else:
                return
        if self.isEnabledFor(level):
            msg, kwargs = self.process(msg, kwargs)
            self._log(level, msg, args, **kwargs)


class KorpLogger(korppluginlib.KorpCallbackPlugin):

    """Class containing plugin functions for various mount points"""

    # The class attribute _loggers contains loggers (actually,
    # LevelLogAdapters) for all the requests being handled by the current
    # process. Different LevelLogAdapters are needed so that the request id can
    # be recorded in the log messages, tying the different log messages for a
    # request, and so that the log level can be adjusted if the request
    # contains "debug=true".
    _loggers = dict()

    def __init__(self):
        """Initialize logging; called only once per process"""
        super().__init__()
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(pluginconf.LOG_LEVEL)
        tm = time.localtime()
        logfile = (os.path.join(pluginconf.LOG_BASEDIR,
                                pluginconf.LOG_FILENAME_FORMAT)
                   .format(year=tm.tm_year, mon=tm.tm_mon, mday=tm.tm_mday,
                           hour=tm.tm_hour, min=tm.tm_min, sec=tm.tm_sec,
                           pid=os.getpid()))
        logdir = os.path.split(logfile)[0]
        os.makedirs(logdir, exist_ok=True)
        handler = logging.FileHandler(logfile)
        handler.setFormatter(logging.Formatter(pluginconf.LOG_FORMAT))
        self._logger.addHandler(handler)
        # Storage for request-specific data, such as start times
        self._logdata = dict()

    # Helper methods

    def _init_logging(self, request, starttime, args):
        """Initialize logging; called once per request (in enter_handler)"""
        request_id = KorpLogger._get_request_id(request)
        loglevel = (logging.DEBUG if (pluginconf.LOG_ENABLE_DEBUG_PARAM
                                      and "debug" in args)
                    else pluginconf.LOG_LEVEL)
        logger = LevelLoggerAdapter(
            self._logger,
            {
                # Additional format keys and their values for log messages
                "request": request_id,
                "starttime": starttime,
                "starttime_ms": int(starttime * 1000),
                "starttime_us": int(starttime * 1e6),
            },
            loglevel)
        self._loggers[request_id] = logger
        self._logdata[request_id] = dict()
        return logger

    def _end_logging(self, request):
        """End logging for a request; called once per request in exit_handler"""
        request_id = KorpLogger._get_request_id(request)
        del self._loggers[request_id]
        del self._logdata[request_id]

    def _get_logdata(self, request, key, default=None):
        """Get the request-specific log data item for key (with default)"""
        return self._logdata[KorpLogger._get_request_id(request)].get(
            key, default)

    def _set_logdata(self, request, key, value, default=None):
        """Set the request-specific log data item key to value.

        If value is a function (of one argument), set the value to the
        return value of the function called with the existing value
        (or default if the values does not exist.
        """
        request_id = KorpLogger._get_request_id(request)
        if callable(value):
            value = value(self._logdata[request_id].get(key, default))
        self._logdata[request_id][key] = value

    def _log(self, log_fn, category, item, *values, format=None):
        """Log item in category with values using function log_fn and format

        Do not log if pluginconf.LOG_CATEGORIES is not None and it
        does not contain category, or if pluginconf.LOG_EXCLUDE_ITEMS
        contains item.

        If multiple values are given, each of them gets the format
        specifier "%s", separated by spaces, unless format is
        explicitly specified.
        """
        if (KorpLogger._log_category(category)
                and item not in pluginconf.LOG_EXCLUDE_ITEMS):
            if format is None:
                format = " ".join(len(values) * ("%s",))
            log_fn(item + ": " + format, *values)

    @staticmethod
    def _get_request_id(request):
        """Return request id (actual request object, not proxy)"""
        return id(request)

    @staticmethod
    def _get_logger(request):
        """Return the logger for request (actual request object, not proxy)"""
        return KorpLogger._loggers[KorpLogger._get_request_id(request)]

    @staticmethod
    def _log_category(category):
        """Return True if logging category"""
        return (pluginconf.LOG_CATEGORIES is None
                or category in pluginconf.LOG_CATEGORIES)

    # Actual plugin methods (functions)

    def enter_handler(self, args, starttime, request):
        """Initialize logging at entering Korp and log basic information"""
        logger = self._init_logging(request, starttime, args)
        env = request.environ
        # request.remote_addr is localhost when behind proxy, so get the
        # originating IP from request.access_route
        self._log(logger.info, "userinfo", "IP", request.access_route[0])
        self._log(logger.info, "userinfo", "User-agent", request.user_agent)
        self._log(logger.info, "referrer", "Referrer", request.referrer)
        # request.script_root is empty; how to get the name of the
        # script? Or is it at all relevant here?
        # self._log(logger.info, "params", "Script", request.script_root)
        self._log(logger.info, "params", "Loginfo", args.get("loginfo", ""))
        cmd = request.path.strip("/")
        if not cmd:
            cmd = "info"
        # Would it be better to call this "Endpoint"?
        self._log(logger.info, "params", "Command", cmd)
        self._log(logger.info, "params", "Params", args)
        # Log user information (Shibboleth authentication only). How could we
        # make this depend on using a Shibboleth plugin?
        if KorpLogger._log_category("auth"):
            self._log(logger.info, "auth", "Env", env)
            # request.remote_user doesn't seem to work here
            try:
                remote_user = env["HTTP_REMOTE_USER"]
            except KeyError:
                # HTTP_REMOTE_USER is usually empty, but sometimes missing
                remote_user = None
            if remote_user:
                auth_domain = remote_user.partition("@")[2]
                auth_user = hashlib.md5(remote_user.encode()).hexdigest()
            else:
                auth_domain = auth_user = None
            self._log(logger.info, "auth", "Auth-domain", auth_domain)
            self._log(logger.info, "auth", "Auth-user", auth_user)
        self._log(logger.debug, "env", "Env", env)
        self._set_logdata(request, "cqp_time_sum", 0)
        # self._log(logger.debug, "env", "App",
        #           repr(korppluginlib.app_globals.app.__dict__))

    def exit_handler(self, endtime, elapsed_time, request):
        """Log information at exiting Korp"""
        logger = KorpLogger._get_logger(request)
        self._log(logger.info, "times", "CQP-time-total",
                  self._get_logdata(request, "cqp_time_sum"))
        self._log(logger.info, "load", "CPU-load", *os.getloadavg())
        # FIXME: The CPU times probably make little sense, as the WSGI server
        # handles multiple requests in a single process
        self._log(logger.info, "times", "CPU-times", *(os.times()[:4]))
        self._log(logger.info, "times", "Elapsed", elapsed_time)
        self._end_logging(request)

    def filter_result(self, result, request):
        """Debug log the result (request response)

        Note that the possible filter_result functions of plugins
        loaded before this one have been applied to the result.
        """
        # TODO: Truncate the value if too long
        logger = KorpLogger._get_logger(request)
        if "corpus_hits" in result:
            self._log(logger.info, "result", "Hits", result["corpus_hits"])
        self._log(logger.debug, "debug", "Result", result)

    def filter_cqp_input(self, cqp, request):
        """Debug log CQP input cqp and save start time"""
        logger = KorpLogger._get_logger(request)
        self._log(logger.debug, "debug", "CQP", cqp)
        self._set_logdata(request, "cqp_start_time",  time.time())

    def filter_cqp_output(self, output, request):
        """Debug log CQP output length and time spent in CQP"""
        cqp_time = time.time() - self._get_logdata(request, "cqp_start_time")
        logger = KorpLogger._get_logger(request)
        # output is a pair (result, error): log the length of both
        self._log(logger.debug, "debug", "CQP-output-length",
                  *(len(val) for val in output))
        self._log(logger.debug, "debug", "CQP-time", cqp_time)
        self._set_logdata(request, "cqp_time_sum", lambda x: x + cqp_time, 0)

    def filter_sql(self, sql, request):
        """Debug log SQL statements sql"""
        logger = KorpLogger._get_logger(request)
        self._log(logger.debug, "debug", "SQL", sql)

    def log(self, levelname, category, item, value, request):
        """Log with the given level, category, item and value

        levelname should be one of "debug", "info", "warning", "error"
        and "critical", corresponding to the methods in
        logging.Logger.

        This general logging method can be called from other plugins
        via
        korppluginlib.KorpCallbackPluginCaller.raise_event_for_request("log",
        ...) whenever they wish to log something.
        """
        logger = KorpLogger._get_logger(request)
        self._log(getattr(logger, levelname, logger.info),
                  category, item, value)
