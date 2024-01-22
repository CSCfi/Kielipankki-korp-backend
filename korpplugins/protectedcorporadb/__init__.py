
"""
korpplugins.protectedcorporadb

Retrieve a list of protected corpora from a MySQL database.
"""


import MySQLdb

from korp import pluginlib, utils
from korp.cwb import cwb


# See README.py for further documentation of the configuration variables
pluginconf = pluginlib.get_plugin_config(
    # All MySQL connection parameters as a dict; if non-empty, overrides the
    # individual DBCONN_* values
    DBCONN_PARAMS = {},
    # MySQL connection parameters as individual values
    DBCONN_HOST = "localhost",
    DBCONN_PORT = 3306,
    # DBCONN_UNIX_SOCKET should be commented-out unless using a non-default
    # socket for connecting
    # DBCONN_UNIX_SOCKET = ""
    DBCONN_DB = "korp_auth",
    DBCONN_USER = "korp",
    DBCONN_PASSWD = "",
    DBCONN_USE_UNICODE = True,
    DBCONN_CHARSET = "utf8mb4",
    # The name of the table containing licence information, to be filled in
    # LIST_PROTECTED_CORPORA_SQL
    LICENCE_TABLE = "auth_license",
    # SQL statement to list protected corpora
    LIST_PROTECTED_CORPORA_SQL = """
        SELECT corpus FROM {LICENCE_TABLE}
        WHERE NOT license LIKE 'PUB%'
    """,
    # Whether to keep the database connection persistent or close after each
    # call of filter_protected_corpora
    PERSISTENT_DB_CONNECTION = True,
)


class ProtectedCorporaDatabase(utils.ProtectedCorporaGetter):

    """Retrieve protected corpora from a MySQL database"""

    def __init__(self):
        """Initialize but do not connect to the database yet."""
        super().__init__()
        self._connection = None
        # Fill in values in LIST_PROTECTED_CORPORA_SQL from other values in
        # pluginconf
        self._list_protected_corpora_sql = (
            pluginconf["LIST_PROTECTED_CORPORA_SQL"].format(**pluginconf))
        # Non-empty DBCONN_PARAMS overrides individual DBCONN_* values
        self._conn_params = (
            pluginconf["DBCONN_PARAMS"]
            or dict((key.lower().split("_", 1)[1], val)
                    for key, val in pluginconf.items()
                    if (key.startswith("DBCONN_")
                        and key != "DBCONN_PARAMS")))

    def __del__(self):
        """Close connection when deleting the object."""
        if self._connection:
            self._connection.close()

    def get_protected_corpora(self):
        """Get list of corpora with restricted access, in uppercase."""
        protected_corpora = None
        if self._connect():
            try:
                cursor = self._connection.cursor()
                cursor.execute(self._list_protected_corpora_sql)
                protected_corpora = [corpus.upper() for corpus, in cursor]
                cursor.close()
                # If the database connection is not persistent, close it
                if not pluginconf["PERSISTENT_DB_CONNECTION"]:
                    self._connection.close()
                    self._connection = None
            except (AttributeError, MySQLdb.MySQLError, MySQLdb.InterfaceError,
                    MySQLdb.DatabaseError):
                pass
        # Assume that all corpora are protected if trying to access the
        # database results in an error
        if protected_corpora is None:
            # The first item in the result of "show corpora;" is CQP
            # version, so omit it
            protected_corpora = list(cwb.run_cqp("show corpora;"))[1:]
        return protected_corpora

    def _connect(self):
        """Connect to authorization database if not already connected.

        Connect to the authorization database with parameters
        specified in the DBCONN_* configuration variables. Set
        self._connection to the connection and return it. If
        connecting fails, set it to None and return None.
        """
        if not self._connection:
            try:
                self._connection = MySQLdb.connect(**self._conn_params)
            except (MySQLdb.MySQLError, MySQLdb.InterfaceError,
                    MySQLdb.DatabaseError) as e:
                print("korpplugins.protectedcorporadb: Error connecting"
                      " to database:", e)
                self._connection = None
        return self._connection
