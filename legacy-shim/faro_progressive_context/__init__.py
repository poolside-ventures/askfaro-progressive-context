"""Compatibility shim: ``faro-progressive-context`` was renamed to
``askfaro-progressive-context``.

Importing ``faro_progressive_context`` (or any of its submodules) transparently
returns the corresponding object from ``askfaro_progressive_context`` and emits a
``DeprecationWarning``. This package will not receive further updates; please
``pip install askfaro-progressive-context`` and update your imports.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
import warnings

_OLD = "faro_progressive_context"
_NEW = "askfaro_progressive_context"

warnings.warn(
    "faro-progressive-context has been renamed to askfaro-progressive-context. "
    "Update your imports to `askfaro_progressive_context` and run "
    "`pip install askfaro-progressive-context`; this shim will not be updated.",
    DeprecationWarning,
    stacklevel=2,
)


class _RenameFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Redirect any ``faro_progressive_context[.x]`` import to ``askfaro_*``."""

    def find_spec(self, name, path=None, target=None):  # noqa: ARG002
        if name == _OLD or name.startswith(_OLD + "."):
            return importlib.util.spec_from_loader(name, self)
        return None

    def create_module(self, spec):
        new_name = _NEW + spec.name[len(_OLD):]
        module = importlib.import_module(new_name)
        sys.modules[spec.name] = module
        return module

    def exec_module(self, module):  # noqa: ARG002
        pass


sys.meta_path.insert(0, _RenameFinder())

# Re-export the top-level public API onto this module object.
from askfaro_progressive_context import *  # noqa: E402,F401,F403
