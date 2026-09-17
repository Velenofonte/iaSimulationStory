# shim: re-export from app.persistence.save_manager (compat)
from importlib import import_module as _import_module
_m = _import_module('app.persistence.save_manager')
globals().update({k: getattr(_m, k) for k in dir(_m)})
