# shim: re-export from app.wiki.wiki_query (compat)
from importlib import import_module as _import_module
_m = _import_module('app.wiki.wiki_query')
globals().update({k: getattr(_m, k) for k in dir(_m)})
