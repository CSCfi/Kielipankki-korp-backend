from flask_mysqldb import MySQL

from korp.pluginlib import CallbackPluginCaller


mysql = MySQL()


def sql_execute(cursor, sql):
    """Execute SQL statement sql on cursor."""
    # This is a separate function to make it easier to add a plugin
    # callback hook point for filtering the SQL statement
    sql = CallbackPluginCaller.filter_value_for_request("filter_sql", sql)
    cursor.execute(sql)
