
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
    # The instances of abstract base classes
    _instance = {}

    def __init_subclass__(cls):
        # Is this needed?
        super().__init_subclass__()

    @classmethod
    def set_baseclass(cls, baseclass):
        """Set cls to be the subclass of baseclass to instantiate."""
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
