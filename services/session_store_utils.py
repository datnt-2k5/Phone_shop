
"""Utilities for safe Flet server-side Session operations."""

from services.auth_session import AuthSessionStore


def discard_session_key(
    session_store: AuthSessionStore,
    key: str,
) -> None:
    """Remove a session key, even when it is already absent.

    Flet SessionStore.remove() raises KeyError when the key
    is missing. Removing a missing key is not a business error.
    """
    try:
        session_store.remove(key)
    except KeyError:
        pass
