# shim: re-export from app.story.era_loader (compat)
from importlib import import_module as _import_module
_m = _import_module('app.story.era_loader')
globals().update({k: getattr(_m, k) for k in dir(_m)})
