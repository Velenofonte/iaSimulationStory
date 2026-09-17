# shim: re-export from app.turn.game_clock (compat)
from importlib import import_module as _import_module
_m = _import_module('app.turn.game_clock')
globals().update({k: getattr(_m, k) for k in dir(_m)})
