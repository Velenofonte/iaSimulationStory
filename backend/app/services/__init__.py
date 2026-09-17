"""Compatibility shims.

Implementations live in domain packages (``app.turn``, ``app.wiki``, …).
Import from ``app.services.<module>`` still works during the migration.
Prefer domain imports for new code.
"""
