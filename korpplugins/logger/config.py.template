
"""
korpplugins.logger.config

Configuration module for korpplugins.logger.
"""


import logging


# Base directory for log files
LOG_BASEDIR = "/v/korp/log/korp-py"

# Log filename format string (for str.format()), which may include a
# directory part, to be appended to LOG_BASEDIR to get the full log
# file path. The supported format keys are: year, mon, mday, hour,
# min, sec (the corresponding tm_X values returned by
# time.localtime()), and pid (process id), which should be included to
# avoid having multiple processes writing to the same log file when
# using a WSGI server with multiple worker processes.
LOG_FILENAME_FORMAT = ("{year}{mon:02}{mday:02}/korp-{year}{mon:02}{mday:02}"
                       "_{hour:02}{min:02}{sec:02}-{pid:06}.log")

# Default log level
LOG_LEVEL = logging.INFO

# If True, change the log level to logging.DEBUG if the query parameters in the
# HTTP request contain "debug=true".
LOG_ENABLE_DEBUG_PARAM = True

# Log message format string using the percent formatting for logging.Formatter.
# In addition to the standard keys, the format may (and typically should)
# contain at least one of the following, to identify the request uniquely
# together with %(process)d:
# - "request" (int), which identifies the request object
#   (id(request._get_current_object())).
# - "starttime" (float): start time recorded for the request as seconds since
#   the epoch
# - "starttime_ms" (int): start time recorded for the request as milliseconds
#   since the epoch
# - "starttime_us" (int): start time recorded for the request as microseconds
#   since the epoch
# %(message)s contains the actual message of the form "Item: Value".
LOG_FORMAT = ("[korp.py %(levelname)s %(process)d:%(request)d @ %(asctime)s]"
              " %(message)s")

# The maximum length of a log message, including the fixed part; 0 for
# unlimited
LOG_MESSAGE_DEFAULT_MAX_LEN = 100000

# The text to insert where a log message is truncated to the maximum length
LOG_MESSAGE_TRUNCATE_TEXT = "[[...CUT...]]"

# The position in which to truncate a log message longer than the maximum
# length: positive values keep that many characters from the beginning,
# negative from the end. Note that when counting from the beginning of the log
# message, the fixed part is also counted, so the value should be larger than
# the maximum length of the fixed part.
LOG_MESSAGE_TRUNCATE_POS = -100

# Categories of information to be logged: all available are listed. If a
# category is omitted from the list, information marked with that category is
# not logged. The category is not included in the log message.
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
]

# A list of individual log items (e.g. "IP", "User-agent") to be excluded from
# logging.
LOG_EXCLUDE_ITEMS = []

# A dict[str, set[str]] of log levels and the log items logged at the
# level in question. If an item name has a leading asterisk, it is
# taken as a category; the level for an individual item overrides that
# of its category. If an item is not listed, its level is "info".
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
}
