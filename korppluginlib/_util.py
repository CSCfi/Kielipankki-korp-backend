
"""
Module korppluginlib._util

Module of utility functions and definitions

This module is intended to be internal to the package korppluginlib.
All modules of korppluginlib should be able to import this module, so
this module should not import any korppluginlib module.
"""


import inspect


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


def get_plugin_name(call_depth=1):
    """Return (plugin name, package name, module info).

    Return the information for call stack depth call_depth: the
    default 1 returns the information for the directly calling code,
    but it needs to be increased if you need the information for the
    caller of the caller, for example. Module info is that returned by
    inspect.getmodule.
    """
    # Use the facilities in the module inspect to avoid having to pass __name__
    # as an argument to the function (https://stackoverflow.com/a/1095621)
    module = inspect.getmodule(inspect.stack()[call_depth][0])
    # Assume module name package.plugin_package.module[.submodule...],
    # package.plugin_module or plugin_module
    module_name_comps = module.__name__.split(".")
    if len(module_name_comps) > 1:
        pkg, plugin = module_name_comps[:2]
    else:
        pkg = None
        plugin = module_name_comps[0]
    return plugin, pkg, module
