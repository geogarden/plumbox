"""Kontekst wykonawcy dla audytu, niezależny od silnika sterownika."""
from contextlib import contextmanager
from contextvars import ContextVar
_audit_actor = ContextVar("plumbox_audit_actor", default=(None, "internal_or_mqtt"))
def current_audit_actor():
    return _audit_actor.get()
@contextmanager
def audit_actor(username, source="api"):
    token = _audit_actor.set((username, source))
    try:
        yield
    finally:
        _audit_actor.reset(token)
