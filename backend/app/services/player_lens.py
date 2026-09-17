# shim: re-export from app.player.player_lens (compat)
from importlib import import_module as _import_module
_m = _import_module('app.player.player_lens')
globals().update({k: getattr(_m, k) for k in dir(_m)})
