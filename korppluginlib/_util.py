
"""
Module korppluginlib._util

Module of utility functions and definitions

This module is intended to be internal to the package korppluginlib.
All modules of korppluginlib should be able to import this module, so
this module should not import any korppluginlib module.
"""


# A list of tuples of print_verbose call arguments whose printing has been
# delayed until printing with print_verbose_delayed.
_delayed_print_verbose_args = []

# Verbosity level for print_verbose(_delayed): if the verbosity
# argument of the functions is at least this, they print their
# arguments
_print_verbosity = 0


def set_print_verbosity(verbosity):
    """Set print verbosity level to verbosity."""
    global _print_verbosity
    _print_verbosity = verbosity


def print_verbose(verbosity, *args, immediate=False):
    """Print args if print verbosity level is at least verbosity.

    Print if _print_verbosity is at least verbosity. If immediate is
    True, print immediately, otherwise collect and print only with
    print_verbose_delayed.
    """
    if verbosity <= _print_verbosity:
        if immediate:
            print(*args)
        else:
            _delayed_print_verbose_args.append(args)


def print_verbose_delayed(verbosity=None):
    """Actually print the delayed verbose print arguments.

    If verbosity is not None and is larger than _print_verbosity do
    not print.
    """
    global _delayed_print_verbose_args
    if verbosity is None or verbosity <= _print_verbosity:
        for args in _delayed_print_verbose_args:
            print(*args)
    _delayed_print_verbose_args = []


def discard_print_verbose_delayed():
    """Discard collected delayed print verbose arguments."""
    global _delayed_print_verbose_args
    _delayed_print_verbose_args = []
