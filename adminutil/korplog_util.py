
"""
korplog_util.py

A module containing utility functions for scripts processing Korp
backend log data.
"""


import time


def make_logentry_id(fields):
    """Return an id of the form <milliseconds since epoch> ":" <pid>"""
    date_s = fields.get('start_date') or fields.get('date') or ''
    time_s, msecs = (
        (fields.get('start_time') or fields.get('time') or ',').split(","))
    try:
        return '{secs:d}{msecs}:{pid:05d}'.format(
            secs=int(time.mktime(time.strptime(date_s + ' ' + time_s,
                                               '%Y-%m-%d %H:%M:%S'))),
            msecs=msecs,
            pid=int(fields.get('pid', '0')))
    except ValueError:
        return 'None'
