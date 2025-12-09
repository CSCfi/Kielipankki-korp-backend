
"""
tests.testutils

Utility functions that can be called from tests. The functions may
contain assertions that are subject to rewriting.
"""


from korp.utils import QUERY_DELIM


def get_response_json(client, *args, **kwargs):
    """Call client.get with given args, assert success, return response JSON."""
    # This function helps in making actual test functions for
    # endpoints slightly more compact and less repetitive
    response = client.get(*args, **kwargs)
    assert response.status_code == 200
    assert response.is_json
    return response.get_json()


def make_liststr(arg):
    """Return str arg as is, else return arg items separated by QUERY_DELIM."""
    if isinstance(arg, str):
        return arg
    else:
        return QUERY_DELIM.join(arg)


def get_info_value(key, lines):
    """Return value for key in lines (sequence of strings).

    For the first line in lines that starts with key followed by a
    colon, return the value after the colon, with leading and trailing
    spaces stripped.

    This function can be used to get the value of key from a corpus
    .info file or from the corresponding output of the CQP "info"
    command.
    """
    for line in lines:
        if line.strip().startswith(f"{key}:"):
            return line.partition(":")[2].strip()
    return None
