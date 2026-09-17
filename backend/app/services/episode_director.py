# shim: re-export from app.episodes.episode_director (compat)
from importlib import import_module as _import_module
_m = _import_module('app.episodes.episode_director')
globals().update({k: getattr(_m, k) for k in dir(_m)})
