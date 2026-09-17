# shim: re-export from app.narrative.prompt_builder (compat)
from importlib import import_module as _import_module
_m = _import_module('app.narrative.prompt_builder')
globals().update({k: getattr(_m, k) for k in dir(_m)})
