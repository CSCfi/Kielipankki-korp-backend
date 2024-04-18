
"""
korpplugins.logger

Simple logging plugin for the Korp backend

The plugin contains functions for the plugin mount points in the
modules of the korp package. The plugin uses Python's standard logging
module.

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
import resource
import time

from korp.pluginlib import get_plugin_config, CallbackPlugin


# See README.md for more information on the configuration variables

pluginconf = get_plugin_config(
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
        "[korp %(levelname)s %(process)d:%(starttime_us)d @ %(asctime)s]"
        " %(message)s"),
    # The maximum length of a log message, including the fixed part; 0 for
    # unlimited
    LOG_MESSAGE_DEFAULT_MAX_LEN = 100000,
    # The text to insert where a log message is truncated to the maximum length
    LOG_MESSAGE_TRUNCATE_TEXT = "[[...CUT...]]",
    # The position in which to truncate a log message longer than the maximum
    # length: positive values keep that many characters from the beginning,
    # negative from the end
    LOG_MESSAGE_TRUNCATE_POS = -100,
    # Categories of information to be logged: all available are listed
    LOG_CATEGORIES = [
        "auth",
        "debug",
        "env",
        "load",
        "memory",
        "params",
        "referrer",
        "result",
        "rusage",
        "times",
        "userinfo",
    ],
    # A list of individual log items to be excluded from logging.
    LOG_EXCLUDE_ITEMS = [],
    # A dict[str, set[str]] of log levels and the log items logged at
    # the level in question. If an item name has a leading asterisk,
    # it is taken as a category; the level for an individual item
    # overrides that of its category. If an item is not listed, its
    # level is "info".
    LOG_LEVEL_ITEMS = {
        "debug": {
            "App",
            "CQP",
            "CQP-output-length",
            "CQP-time",
            "Env",
            "Resource-usage-children",
            "Resource-usage-self",
            "Result",
            "SQL",
        },
    },
)


class LevelLoggerAdapter(logging.LoggerAdapter):

    """
    A LoggerAdapter subclass with its own log level

    This class keeps its own log level, so different LevelLoggerAdapters
    for the same Logger may have different log levels. (In contrast,
    LoggerAdapter.setlevel delegates to Logger.setLevel, so calling it
    sets the level for all LoggerAdapters of the Logger instance, which
    is not desired here.)

    Also in contrast to LoggerAdapter, the values in the "extra"
    keyword argument (dict) passed to logging methods override those
    specified in the "extra" argument of the instance creation.
    """

    def __init__(self, logger, extra, level=None):
        super().__init__(logger, extra)
        self._level = logger.getEffectiveLevel() if level is None else level

    def setLevel(self, level):
        self._level = level

    def getEffectiveLevel(self):
        return self._level

    def isEnabledFor(self, level):
        """Is this logger enabled for level?"""
        # This is copied from Python 3.6 logging.Logger.isEnabledFor.
        # Python 3.7 and greater have a more complex one with logging
        # level caching and locking, and their
        # LoggerAdapter.isEnabledFor delegates directly to
        # Logging.isEnabledFor, instead of calling getEffectiveLevel
        # directly.
        if self.manager.disable >= level:
            return False
        return level >= self.getEffectiveLevel()

    def process(self, msg, kwargs):
        """If the kwargs (passed to a logging method) contain dict
        "extra", its values override those of the instance-level
        "extra" instead of being discarded."""
        if "extra" in kwargs:
            extra = self.extra.copy()
            extra.update(kwargs["extra"])
            kwargs["extra"] = extra
        else:
            kwargs["extra"] = self.extra
        return msg, kwargs

    def log(self, level, msg, *args, **kwargs):
        # LoggerAdapter.log calls logger.log, which re-checks isEnabledFor
        # based on the info in logger, so we need to redefine it to use
        # self._level here. The following is a combination of Logger.log and
        # LoggerAdapter.log, but calling self.isEnabledFor (of this class),
        # which in turn calls self.getEffectiveLevel (of this class).
        if not isinstance(level, int):
            if logging.raiseExceptions:
                raise TypeError("level must be an integer")
            else:
                return
        if self.isEnabledFor(level):
            msg, kwargs = self.process(msg, kwargs)
            self._log(level, msg, args, **kwargs)


class FunctionLoggerAdapter(LevelLoggerAdapter):

    """
    LevelLoggerAdapter subclass with method logf calling given log function

    The constructor is passed log_func, which is the function called
    by logf, with the instance of this class as the first argument and
    the arguments to logf as the rest.

    This is a convenience class, so that you can call logger.logf(...)
    instead of self._log(logger, ...) when logging in KorpLogger
    callback methods below.
    """

    def __init__(self, logger, extra, log_func, level=None):
        super().__init__(logger, extra, level)
        self._log_func = log_func

    def logf(self, *args, **kwargs):
        """Call self._log_func with self as the first argument."""
        self._log_func(self, *args, **kwargs)


class TruncatingLogFormatter(logging.Formatter):

    """Log formatter class truncating log messages

    The class truncates messages to the length specified by the maxlen
    attribute of the LogRecord instance to be formatted or to
    pluginconf["LOG_MESSAGE_DEFAULT_MAX_LEN"] if it does not exist. If
    the value is <= 0, do not truncate the message.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def format(self, record):
        maxlen = getattr(record, "maxlen",
                         pluginconf["LOG_MESSAGE_DEFAULT_MAX_LEN"])
        result = super().format(record)
        if maxlen > 0 and len(result) > maxlen:
            trunc_text = pluginconf["LOG_MESSAGE_TRUNCATE_TEXT"]
            trunc_pos = pluginconf["LOG_MESSAGE_TRUNCATE_POS"]
            if trunc_pos < 0:
                trunc_head_len = maxlen + trunc_pos - len(trunc_text)
                trunc_tail_len = -trunc_pos
            else:
                trunc_head_len = trunc_pos
                trunc_tail_len = maxlen - trunc_pos - len(trunc_text)
            result = (result[:trunc_head_len] + trunc_text
                      + result[-trunc_tail_len:])
        return result


class KorpLogger(CallbackPlugin):

    """Class containing plugin functions for various mount points"""

    # The class attribute _loggers contains loggers (actually,
    # FunctionLogAdapters) for all the requests being handled by the
    # current process. Different FunctionLogAdapters are needed so
    # that the request id can be recorded in the log messages, tying
    # the different log messages for a request, and so that the log
    # level can be adjusted if the request contains "debug=true".
    _loggers = dict()

    def __init__(self):
        """Initialize logging; called only once per process"""
        super().__init__()
        self._logger = logging.getLogger(__name__)
        self._logger.setLevel(pluginconf["LOG_LEVEL"])
        tm = time.localtime()
        logfile = (os.path.join(pluginconf["LOG_BASEDIR"],
                                pluginconf["LOG_FILENAME_FORMAT"])
                   .format(year=tm.tm_year, mon=tm.tm_mon, mday=tm.tm_mday,
                           hour=tm.tm_hour, min=tm.tm_min, sec=tm.tm_sec,
                           pid=os.getpid()))
        logdir = os.path.split(logfile)[0]
        os.makedirs(logdir, exist_ok=True)
        handler = logging.FileHandler(logfile)
        handler.setFormatter(TruncatingLogFormatter(pluginconf["LOG_FORMAT"]))
        self._logger.addHandler(handler)
        # Storage for request-specific data, such as start times
        self._logdata = dict()
        # Log levels for items (other than "info")
        self._item_levels = {
            item: level
            for level, items in pluginconf["LOG_LEVEL_ITEMS"].items()
            for item in items
        }

    # Helper methods

    def _init_logging(self, request, starttime, args):
        """Initialize logging; called once per request (in enter_handler)"""
        request_id = KorpLogger._get_request_id(request)
        loglevel = (logging.DEBUG if (pluginconf["LOG_ENABLE_DEBUG_PARAM"]
                                      and "debug" in args)
                    else pluginconf["LOG_LEVEL"])
        logger = FunctionLoggerAdapter(
            self._logger,
            {
                # Additional format keys and their values for log messages
                "request": request_id,
                "starttime": starttime,
                "starttime_ms": int(starttime * 1000),
                "starttime_us": int(starttime * 1e6),
                # Default maximum message length
                "maxlen": pluginconf["LOG_MESSAGE_DEFAULT_MAX_LEN"],
            },
            self._log,
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

    def _log(self, logger, category, item, *values, format=None, maxlen=None,
             levelname=None):
        """Log item in category with values using logger and format.

        Do not log if pluginconf["LOG_CATEGORIES"] is not None and it
        does not contain category, or if pluginconf["LOG_EXCLUDE_ITEMS"]
        contains item.

        If levelname is not None, log using the logger method
        specified by it, otherwise by self._item_levels[item] or
        self._item_levels["*" + category] (default: logger.info).

        If multiple values are given, each of them gets the format
        specifier "%s", separated by spaces, unless format is
        explicitly specified.

        If maxlen is an integer, use the value as the maximum length
        of the log message, overriding the default.
        """
        if (KorpLogger._log_category(category)
                and item not in pluginconf["LOG_EXCLUDE_ITEMS"]):
            if format is None:
                format = " ".join(len(values) * ("%s",))
            extra = {}
            if maxlen is not None:
                extra["maxlen"] = maxlen
            if levelname is None:
                levelname = (self._item_levels.get(item)
                             or self._item_levels.get("*" + category)
                             or "info")
            log_fn = getattr(logger, levelname, logger.info)
            log_fn(item + ": " + format, *values, extra=extra)

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
        return (pluginconf["LOG_CATEGORIES"] is None
                or category in pluginconf["LOG_CATEGORIES"])

    # Actual plugin methods (functions)

    def enter_handler(self, request, args, starttime):
        """Initialize logging at entering Korp and log basic information"""
        logger = self._init_logging(request, starttime, args)
        self._set_logdata(request, "cpu_times_start", os.times()[:4])
        env = request.environ
        # request.remote_addr is localhost when behind proxy, so get the
        # originating IP from request.access_route
        logger.logf("userinfo", "IP", request.access_route[0])
        logger.logf("userinfo", "User-agent", request.user_agent)
        logger.logf("referrer", "Referrer", request.referrer)
        # request.script_root is empty; how to get the name of the
        # script? Or is it at all relevant here?
        # logger.logf("params", "Script", request.script_root)
        logger.logf("params", "Loginfo", args.get("loginfo", ""))
        cmd = request.path.strip("/")
        if not cmd:
            cmd = "info"
        # Would it be better to call this "Endpoint"?
        logger.logf("params", "Command", cmd)
        logger.logf("params", "Params", args)
        # Log user information (Shibboleth authentication only). How could we
        # make this depend on using a Shibboleth plugin?
        if KorpLogger._log_category("auth"):
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
            logger.logf("auth", "Auth-domain", auth_domain)
            logger.logf("auth", "Auth-user", auth_user)
        logger.logf("env", "Env", env)
        self._set_logdata(request, "cqp_time_sum", 0)
        # logger.logf("env", "App",
        #             repr(korppluginlib.app_globals.app.__dict__))

    def exit_handler(self, request, endtime, elapsed_time, result_len):
        """Log information at exiting Korp"""

        def format_rusage(rusage):
            """Format the resource usage representation more compactly"""
            return (str(rusage)
                    .replace("resource.struct_rusage(", "")
                    .replace(")", "")
                    .replace("ru_", "")
                    .replace(",", ""))

        logger = KorpLogger._get_logger(request)
        logger.logf("result", "Content-length", result_len)
        logger.logf("times", "CQP-time-total",
                    self._get_logdata(request, "cqp_time_sum"))
        logger.logf("load", "CPU-load", *os.getloadavg())
        # FIXME: The CPU times probably make little sense, as the WSGI server
        # handles multiple requests in a single process. However, does CPU
        # times difference make any more sense?
        cpu_times_start = self._get_logdata(request, "cpu_times_start")
        cpu_times_end = os.times()[:4]
        logger.logf("times", "CPU-times", *cpu_times_end)
        # The difference of CPU times at the beginning and end of the request
        cpu_times_diff = tuple(
            "{:.2f}".format(cpu_times_end[i] - cpu_times_start[i])
            for i in range(len(cpu_times_start)))
        logger.logf("times", "CPU-times-diff", *cpu_times_diff)
        rusage_self = resource.getrusage(resource.RUSAGE_SELF)
        rusage_children = resource.getrusage(resource.RUSAGE_CHILDREN)
        logger.logf("memory", "Memory-max-RSS",
                    rusage_self[2], rusage_children[2])
        logger.logf("rusage", "Resource-usage-self",
                    format_rusage(rusage_self))
        logger.logf("rusage", "Resource-usage-children",
                    format_rusage(rusage_children))
        logger.logf("times", "Elapsed", elapsed_time)
        self._end_logging(request)

    def filter_result(self, request, result):
        """Debug log the result (request response)

        Note that the possible filter_result functions of plugins
        loaded before this one have been applied to the result.
        """
        logger = KorpLogger._get_logger(request)
        if isinstance(result, dict) and "corpus_hits" in result:
            logger.logf("result", "Hits", result["corpus_hits"])
        logger.logf("debug", "Result", result)

    def filter_cqp_input(self, request, cqp):
        """Debug log CQP input cqp and save start time"""
        logger = KorpLogger._get_logger(request)
        logger.logf("debug", "CQP", cqp)
        self._set_logdata(request, "cqp_start_time",  time.time())

    def filter_cqp_output(self, request, output):
        """Debug log CQP output length and time spent in CQP"""
        cqp_time = time.time() - self._get_logdata(request, "cqp_start_time")
        logger = KorpLogger._get_logger(request)
        # output is a pair (result, error): log the length of both
        logger.logf("debug", "CQP-output-length",
                    *(len(val) for val in output))
        logger.logf("debug", "CQP-time", cqp_time)
        self._set_logdata(request, "cqp_time_sum", lambda x: x + cqp_time, 0)

    def filter_sql(self, request, sql):
        """Debug log SQL statements sql"""
        logger = KorpLogger._get_logger(request)
        logger.logf("debug", "SQL", sql)

    def log(self, request, levelname, category, item, value):
        """Log with the given level, category, item and value

        levelname should be one of "debug", "info", "warning", "error"
        and "critical", corresponding to the methods in
        logging.Logger.

        This general logging method can be called from other plugins
        via
        korp.pluginlib.CallbackPluginCaller.raise_event_for_request("log",
        ...) whenever they wish to log something.
        """
        logger = KorpLogger._get_logger(request)
        logger.logf(category, item, value, levelname=levelname)
