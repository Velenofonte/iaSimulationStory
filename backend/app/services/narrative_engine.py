# shim: re-export from app.narrative.narrative_engine (compat)
from importlib import import_module as _import_module
_m = _import_module('app.narrative.narrative_engine')
globals().update({k: getattr(_m, k) for k in dir(_m)})
