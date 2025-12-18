
"""
Module korp.pluginlib._subclassplugin

Module containing code for subclass-based plugins

Plugin modules implement concrete subclasses of abstract subclasses of
SubclassPlugin. Supported abstract subclasses are currently defined in
module korp.utils.

This module is intended to be internal to the package korp.pluginlib;
the names intended to be visible outside the package are imported at
the package level.
"""


import inspect
import sys
import typing

from collections import defaultdict

from ._util import print_verbose


class SubclassPlugin:

    """Base class for (abstract) plugin base classes

    This class helps in defining abstract base classes for pluginable
    functionality implemented in concrete subclasses.

    Given an abstract base class C (subclass of this class):
    - C.__init_subclass__(cls) should call cls.set_baseclass(C), in
      addition to super().__init_subclass__().
    - After defining the potential subclasses Cn of C, an instance of
      the most recently defined subclass Cn is created and returned by
      C.get_instance() (or None if no subclasses were defined).
      Subsequent calls of C.get_instance() return the same instance,
      so C is a singleton.
    """

    # The concrete subclasses of abstract base classes
    _subclass = {}
    # Overridden concrete subclasses of abstract base classes (not
    # instantiated)
    _overridden = defaultdict(list)
    # The instances of abstract base classes
    _instance = {}

    def __init_subclass__(cls):
        # Is this needed?
        super().__init_subclass__()

    @classmethod
    def set_baseclass(cls, baseclass):
        """Set cls to be the subclass of baseclass to instantiate."""
        # Ignore cls if it is abstract, too
        if inspect.isabstract(cls):
            return
        # If baseclass has already set a class, append the previous
        # value to _overridden, to be warned about in get_instance
        if baseclass in SubclassPlugin._subclass:
            SubclassPlugin._overridden[baseclass].append(
                SubclassPlugin._subclass[baseclass])
        SubclassPlugin._subclass[baseclass] = cls

    @classmethod
    def get_instance(cls):
        """Return an instance of the most recently defined subclass of cls.

        Return None if no subclass of cls have been defined.
        Subsequent calls return the same instance.
        """
        subclass = SubclassPlugin._subclass.get(cls)
        if subclass:
            return SubclassPlugin._instance.setdefault(subclass, subclass())
        else:
            return None


def register_subclass_plugins(modules, override=False):
    """Register subclass plugins in modules.

    For all names c in module with type annotation Optional["C"] or
    "C" where C is a subclass of SubclassPlugin (an abstract plugin
    class), set the value of module.c to C.get_instance() (a singleton
    instance of the subclass of C defined last).

    modules can be a single module or an iterable of modules.
    If override == True, replace a possibly existing non-None value;
    otherwise, keep the existing value.
    """

    def get_qualname(obj):
        """Return the fully qualified name of obj."""
        return f"{obj.__module__}.{obj.__name__}"

    def test_and_set_value(module, cls, attr):
        """If cls is a subclass of SubclassPlugin, set module.attr to
        cls.get_instance() and return True. Also print informational
        messages."""
        try:
            if issubclass(cls, SubclassPlugin):
                instance = cls.get_instance()
                if instance is not None:
                    setattr(module, attr, instance)
                    subclass = instance.__class__
                    print_verbose(
                        1,
                        f"{cls.__name__}: Using subclass {subclass.__name__}"
                        f" in {subclass.__module__}",
                        immediate=True)
                    if cls in SubclassPlugin._overridden:
                        print(
                            f"Warning: Class {get_qualname(subclass)} overrides"
                            f" subclasses of {cls.__name__} defined earlier: "
                            + ", ".join(
                                f"{get_qualname(overridden)}"
                                for overridden
                                in SubclassPlugin._overridden[cls]),
                            file=sys.stderr)
                else:
                    print("Warning: No concrete subclasses found for",
                          cls.__name__,
                          file=sys.stderr)
                return True
        except TypeError:
            pass
        return False

    if getattr(typing, "get_origin", None):
        # Python 3.8+
        get_origin = typing.get_origin
        get_args = typing.get_args
    else:
        # Python <3.8
        get_origin = lambda tp: tp.__origin__
        get_args = lambda tp: tp.__args__
    if modules.__class__.__name__ == "module":
        modules = [modules]
    for module in modules:
        annots = typing.get_type_hints(module)
        # Go through all type annotations in module
        for name, annot in annots.items():
            if getattr(module, name, None) is None or override:
                origin = get_origin(annot)
                if repr(origin) == "typing.Union":
                    for cls in get_args(annot):
                        if test_and_set_value(module, cls, name):
                            break
                else:
                    test_and_set_value(module, origin, name)
