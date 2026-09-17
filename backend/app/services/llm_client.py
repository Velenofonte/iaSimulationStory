# shim: re-export from app.llm.llm_client (compat)
from importlib import import_module as _import_module
_m = _import_module('app.llm.llm_client')
globals().update({k: getattr(_m, k) for k in dir(_m)})
