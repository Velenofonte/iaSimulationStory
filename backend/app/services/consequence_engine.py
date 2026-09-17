# shim: re-export from app.episodes.consequence_engine (compat)
from importlib import import_module as _import_module
_m = _import_module('app.episodes.consequence_engine')
globals().update({k: getattr(_m, k) for k in dir(_m)})
