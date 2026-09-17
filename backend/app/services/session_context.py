# shim: re-export from app.application.session_context (compat)
from importlib import import_module as _import_module
_m = _import_module('app.application.session_context')
globals().update({k: getattr(_m, k) for k in dir(_m)})
