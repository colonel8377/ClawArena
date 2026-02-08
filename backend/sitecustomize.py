"""
Import compatibility shim.

Allows running the backend as a top-level app (e.g. `uvicorn main:asgi_app`)
while keeping relative imports that expect a parent package.
"""

import importlib
import importlib.abc
import importlib.util
import os
import sys
import types


_BASE_DIR = os.path.dirname(__file__)
_ALIASED_TOP_LEVEL = {
    "config",
    "database",
    "economy",
    "events",
    "games",
    "indexer",
    "manager",
}


def _ensure_backend_package() -> None:
    if "backend" in sys.modules:
        return
    try:
        importlib.import_module("backend")
        return
    except ModuleNotFoundError:
        backend_pkg = types.ModuleType("backend")
        backend_pkg.__path__ = [_BASE_DIR]
        backend_pkg.__file__ = os.path.join(_BASE_DIR, "__init__.py")
        sys.modules["backend"] = backend_pkg


class _BackendAliasLoader(importlib.abc.Loader):
    def __init__(self, alias: str, target: str) -> None:
        self.alias = alias
        self.target = target

    def create_module(self, spec):
        return importlib.import_module(self.target)

    def exec_module(self, module) -> None:
        sys.modules[self.alias] = module


class _BackendAliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.startswith("backend."):
            return None
        root = fullname.split(".", 1)[0]
        if root not in _ALIASED_TOP_LEVEL:
            return None
        target_name = f"backend.{fullname}"
        return importlib.util.spec_from_loader(
            fullname,
            _BackendAliasLoader(fullname, target_name),
        )


def _install_alias_finder() -> None:
    for finder in sys.meta_path:
        if isinstance(finder, _BackendAliasFinder):
            return
    sys.meta_path.insert(0, _BackendAliasFinder())


_ensure_backend_package()
_install_alias_finder()