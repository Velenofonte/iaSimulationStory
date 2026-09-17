# shim: re-export from app.wiki.character_sheet_normalize (compat)
from importlib import import_module as _import_module
_m = _import_module('app.wiki.character_sheet_normalize')
globals().update({k: getattr(_m, k) for k in dir(_m)})
