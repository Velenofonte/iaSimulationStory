# shim: re-export from app.persistence.turn_persistence (compat)
from importlib import import_module as _import_module
_m = _import_module('app.persistence.turn_persistence')
globals().update({k: getattr(_m, k) for k in dir(_m)})
