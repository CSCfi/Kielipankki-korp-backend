"""
Default configuration file.

Settings can be overridden by placing a copy of this file in a directory named 'instance', and editing that copy.
"""

# Host and port for the WSGI server
WSGI_HOST = "0.0.0.0"
WSGI_PORT = 1234

# The absolute path to the CQP binaries
CQP_EXECUTABLE = ""
CWB_SCAN_EXECUTABLE = ""

# The absolute path to the CWB registry files
CWB_REGISTRY = ""

# The default encoding for the cqp binary
CQP_ENCODING = "UTF-8"

# Locale to use when sorting
LC_COLLATE = "sv_SE.UTF-8"

# The maximum number of search results that can be returned per query (0 = no limit)
MAX_KWIC_ROWS = 0

# Number of threads to use during parallel processing
PARALLEL_THREADS = 3

# Database host and port
DBHOST = "0.0.0.0"
DBPORT = 3306

# Database name
DBNAME = ""

# Word Picture table prefix
DBWPTABLE = "relations"

# Username and password for database access
DBUSER = ""
DBPASSWORD = ""

# Cache path (optional). Script must have read and write access.
CACHE_DIR = ""

# Disk cache lifespan in minutes
CACHE_LIFESPAN = 20

# Memcached server IP address and port, or path to socket file (socket path must start with slash)
MEMCACHED_SERVER = None

# Max number of rows from count command to cache
CACHE_MAX_STATS = 50

# Max size in bytes per cached query data file (0 = no limit)
CACHE_MAX_QUERY_DATA = 0

# Corpus configuration directory
CORPUS_CONFIG_DIR = ""

# Set to True to enable "lab mode", potentially enabling experimental features and access to lab-only corpora
LAB_MODE = False

# Plugins to load
PLUGINS = []

# Plugin configuration
PLUGINS_CONFIG = {}

# Show plugin information in the result of the /info endpoint:
#  "name" = plugin names only
#  "info" = plugin information in the PLUGIN_INFO of the plugin
#  None = nothing
INFO_SHOW_PLUGINS = "name"

# Plugin library (korp.pluginlib) configuration (see
# korp/pluginlib/README.md for more details)
PLUGINLIB_CONFIG = dict(
    # List of packages (possibly namespace packages) which may contain
    # plugins, "" for top-level modules without packages. The packages
    # are searched for a plugin in the listed order.
    PACKAGES = ["plugins", "korpplugins"],
    # List of directories in which to search for plugins in addition
    # to default ones
    SEARCH_PATH = [],
    # What to do when a plugin is not found: "error", "warn" or "ignore"
    HANDLE_NOT_FOUND = "warn",
    # What is output to the console when loading plugins: 0 = nothing,
    # 1 = plugin names only, 2 = plugin names and plugin function
    # names
    LOAD_VERBOSITY = 1,
    # What to do with duplicate endpoints for a routing rule, added by
    # plugins: "override", "override,warn", "ignore", "warn" or
    # "error"
    HANDLE_DUPLICATE_ROUTES = "override,warn",
)
