# shim: re-export from app.episodes.notoriety (compat)
from importlib import import_module as _import_module
_m = _import_module('app.episodes.notoriety')
globals().update({k: getattr(_m, k) for k in dir(_m)})
