
"""
Module korppluginlib._util

Module of utility functions and definitions

This module is intended to be internal to the package korppluginlib.
"""


from ._configutil import pluginlibconf


# A list of tuples of print_verbose call arguments whose printing has been
# delayed until printing with print_verbose_delayed.
_delayed_print_verbose_args = []


def print_verbose(verbosity, *args, immediate=False):
    """Print args if plugin loading is configured to be verbose.

    Print if pluginlibconf.LOAD_VERBOSITY is at least verbosity. If
    immediate is True, print immediately, otherwise collect and print
    only with print_verbose_delayed.
    """
    if verbosity <= pluginlibconf.LOAD_VERBOSITY:
        if immediate:
            print(*args)
        else:
            _delayed_print_verbose_args.append(args)


def print_verbose_delayed(verbosity=None):
    """Actually print the delayed verbose print arguments.

    If verbosity is not None and is larger than
    pluginlibconf.LOAD_VERBOSITY, do not print."""
    global _delayed_print_verbose_args
    if verbosity is None or verbosity <= pluginlibconf.LOAD_VERBOSITY:
        for args in _delayed_print_verbose_args:
            print(*args)
    _delayed_print_verbose_args = []


def discard_print_verbose_delayed():
    """Discard collected delayed print verbose arguments."""
    global _delayed_print_verbose_args
    _delayed_print_verbose_args = []
