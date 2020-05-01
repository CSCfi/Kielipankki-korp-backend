
"""
korplog_util.py

A module containing utility functions for scripts processing Korp
backend log data.
"""


import re
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


def decode_list_param(str_list):
    """Decode a list-valued parameter str_list into a list of strings.

    Split str_list at comma and full stop. Also expand one level of
    common prefixes with suffixes marked with parentheses:
    LAM_A(HLA,NTR) -> LAM_AHLA,LAM_ANTR (nesting parentheses is not
    allowed).

    If str_list is a real list, return it as is.
    """
    # Copied from korp.cgi, slightly modified.
    if isinstance(str_list, list):
        return str_list
    split_val = re.split(r"[.,]", str_list)
    result = []
    prefix = ""
    for elem in split_val:
        # print elem, prefix, result
        mo = re.match(r"^([^()]*)([()])?(.*)$", elem)
        pref, sep, suff = mo.groups()
        # print prefix, repr([pref, sep, suff])
        if sep == "(":
            # new_prefix(suffix
            prefix = pref
            result.append(prefix + suff)
        elif sep == ')':
            # last_suffix)
            result.append(prefix + pref)
            prefix = ""
        else:
            # Neither ( nor )
            result.append(prefix + pref)
    # print result
    return result
