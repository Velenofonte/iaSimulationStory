# shim: re-export from app.player.presence (compat)
from importlib import import_module as _import_module
_m = _import_module('app.player.presence')
globals().update({k: getattr(_m, k) for k in dir(_m)})
