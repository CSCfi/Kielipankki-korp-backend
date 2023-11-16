
"""
korpplugins.protectedcorporadb.config (template)

Sample configuration for korpplugins.protectedcorporadb.
"""


# All MySQL connection parameters as a dict; if non-empty, the values it
# contains override the individual DBCONN_* values
DBCONN_PARAMS = {}

# MySQL connection parameters as individual values. Each DBCONN_KEY
# corresponds to the parameter "key" of the MySQLdb.connect call.
DBCONN_HOST = "localhost"
DBCONN_PORT = 3306
# Keep DBCONN_UNIX_SOCKET commented-out unless you use a non-default
# socket for connecting
# DBCONN_UNIX_SOCKET = ""
DBCONN_DB = "korp_auth"
DBCONN_USER = "korp"
DBCONN_PASSWD = ""
DBCONN_USE_UNICODE = True
DBCONN_CHARSET = "utf8mb4"

# The name of the table in DBCONN_DB from which to retrieve licence
# information
LICENCE_TABLE = "auth_license"

# The SQL statement to list protected corpora in DBCONN_DB;
# {LICENCE_TABLE} is replaced with the value of LICENCE_TABLE.
LIST_PROTECTED_CORPORA_SQL = """
    SELECT corpus FROM {LICENCE_TABLE}
    WHERE NOT license LIKE 'PUB%'
"""

# Whether to keep the database connection persistent (True) or close
# after each call of filter_protected_corpora (False)
PERSISTENT_DB_CONNECTION = True
