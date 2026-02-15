"""Token persistence helpers for tuitter.

This module provides a single canonical writer and reader for the full
token blob. Historically the codebase used a variety of shapes (separate
`refresh_token` entries, a small `username` key, or an entire JSON blob).
We normalize to one shape: the full token dict is stored under the key
`oauth_tokens.json` (in keyring when available) or in a fallback file.

Functions:
  - save_tokens_full(tokens: dict, username: Optional[str]) -> None
  - load_tokens() -> Optional[dict]  # returns {'tokens': {...}, 'username': '...'}
  - clear_tokens() -> None
"""

from __future__ import annotations

import json
import platform
from pathlib import Path
import os
import logging
import base64
from typing import Optional

_DEBUG_FLAG_FILE = Path.home() / ".tuitter_tokens_debug.log"
# Allow multiple instances with separate credentials via TUITTER_PROFILE env var.
# E.g. TUITTER_PROFILE=alice isolates keyring keys and token file for a second user.
_PROFILE = os.getenv("TUITTER_PROFILE", "").strip()
SERVICE_NAME = f"tuitter-{_PROFILE}" if _PROFILE else "tuitter"
FALLBACK_TOKEN_FILE = Path.home() / (f".tuitter_tokens_{_PROFILE}.json" if _PROFILE else ".tuitter_tokens.json")
# Size of each chunk in bytes when splitting large values for keyring storage.
# Keep this conservative to avoid per-credential limits on Windows Credential Manager.
_CHUNK_SIZE = 1000

logger = logging.getLogger("tuitter.auth_storage")

# Ensure auth_storage logger writes to the same debug file used elsewhere,
# but only when TUITTER_DEBUG is enabled.
if os.getenv("TUITTER_DEBUG"):
    if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == str(_DEBUG_FLAG_FILE) for h in logger.handlers):
        try:
            fh = logging.FileHandler(str(_DEBUG_FLAG_FILE), encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            logger.addHandler(fh)
        except Exception:
            # never fail core logic for logging issues
            pass
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.WARNING)


def _write_debug(msg: str) -> None:
    try:
        # Only write debug traces to the on-disk debug file when debugging is enabled.
        if not os.getenv("TUITTER_DEBUG"):
            return
        _DEBUG_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _DEBUG_FLAG_FILE.open("a", encoding="utf-8") as _dbg:
            _dbg.write(msg + "\n")
    except Exception:
        # Debug logging must never fail core logic
        pass


def _store_chunked_value(key_base: str, value: str) -> None:
    """Store a potentially-large string by splitting it into base64-encoded
    chunks and writing each chunk under keys: {key_base}.part{i}, with an
    index stored at {key_base}.parts containing the part count.

    This avoids per-credential size limits in some keyring backends.
    """
    try:
        import keyring
    except Exception as e:
        logger.exception("auth_storage: keyring import failed in _store_chunked_value")
        raise

    # Delete any existing chunked value first to avoid stale parts
    try:
        _delete_chunked_value(key_base)
    except Exception:
        # ignore cleanup errors
        pass

    data = value.encode("utf-8")

    # Try progressively smaller chunk sizes to find a size that the
    # backend accepts. This helps environments with tight per-credential
    # limits (Windows Credential Manager variants).
    sizes_to_try = [_CHUNK_SIZE, 512, 256, 128]
    last_exc = None
    for chunk_size in sizes_to_try:
        parts = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]
        written_parts = []
        try:
            for idx, part in enumerate(parts):
                b64 = base64.b64encode(part).decode("ascii")
                part_key = f"{key_base}.part{idx}"
                # write
                keyring.set_password(SERVICE_NAME, part_key, b64)
                # verify immediately
                readback = keyring.get_password(SERVICE_NAME, part_key)
                if readback is None or readback != b64:
                    raise RuntimeError(f"verification failed for {part_key}")
                written_parts.append(part_key)

            # store parts count index
            keyring.set_password(SERVICE_NAME, f"{key_base}.parts", str(len(parts)))
            # verify index
            idx_read = keyring.get_password(SERVICE_NAME, f"{key_base}.parts")
            if idx_read is None or int(idx_read) != len(parts):
                raise RuntimeError("verification failed for parts index")

            logger.debug("auth_storage: stored %s in %d chunk(s) (chunk_size=%d)", key_base, len(parts), chunk_size)
            return

        except Exception as e:
            last_exc = e
            logger.debug("auth_storage: chunked write with chunk_size=%d failed: %s", chunk_size, e)
            # cleanup any parts we already wrote for this attempt
            for pk in written_parts:
                try:
                    keyring.delete_password(SERVICE_NAME, pk)
                except Exception:
                    pass
            try:
                keyring.delete_password(SERVICE_NAME, f"{key_base}.parts")
            except Exception:
                pass
            # try next smaller size

    # If we exhausted sizes and couldn't write, raise the last exception
    logger.exception("auth_storage: all chunked write attempts failed for %s", key_base)
    raise last_exc or RuntimeError("failed to store chunked value")


def _read_chunked_value(key_base: str) -> Optional[str]:
    """Read a chunked value stored by _store_chunked_value and return the
    original string, or None if not present.
    """
    try:
        import keyring
    except Exception as e:
        logger.exception("auth_storage: keyring import failed in _read_chunked_value")
        raise

    count_s = keyring.get_password(SERVICE_NAME, f"{key_base}.parts")
    if not count_s:
        return None
    try:
        count = int(count_s)
    except Exception:
        logger.debug("auth_storage: invalid parts index for %s: %r", key_base, count_s)
        return None

    parts = []
    for i in range(count):
        part_key = f"{key_base}.part{i}"
        b64 = keyring.get_password(SERVICE_NAME, part_key)
        if b64 is None:
            # missing part -> treat as corruption
            raise RuntimeError(f"missing chunk {part_key}")
        part = base64.b64decode(b64.encode("ascii"))
        parts.append(part)

    data = b"".join(parts)
    return data.decode("utf-8")


def _delete_chunked_value(key_base: str) -> None:
    try:
        import keyring
    except Exception as e:
        logger.exception("auth_storage: keyring import failed in _delete_chunked_value")
        raise

    count_s = keyring.get_password(SERVICE_NAME, f"{key_base}.parts")
    if not count_s:
        return
    try:
        count = int(count_s)
    except Exception:
        # Unknown index format; attempt to delete the parts key and return
        try:
            keyring.delete_password(SERVICE_NAME, f"{key_base}.parts")
        except Exception:
            pass
        return

    for i in range(count):
        part_key = f"{key_base}.part{i}"
        try:
            keyring.delete_password(SERVICE_NAME, part_key)
        except Exception:
            pass

    try:
        keyring.delete_password(SERVICE_NAME, f"{key_base}.parts")
    except Exception:
        pass

# Public aliases (convenience for other modules)
store_chunked_value = _store_chunked_value
read_chunked_value = _read_chunked_value
delete_chunked_value = _delete_chunked_value


def save_tokens_full(tokens: dict, username: Optional[str] = None) -> None:
    """Persist the full token blob in a platform-appropriate store.

    This is the canonical writer used throughout the app. It will try, in
    order: (1) platform DPAPI-encrypted fallback file on Windows (if
    win32crypt is available), (2) keyring under key 'oauth_tokens.json',
    (3) plaintext fallback file as a last resort.

    Writing the separate small 'username' key into keyring is performed as
    a best-effort compatibility step so UI code that still reads
    keyring.get_password(SERVICE_NAME, 'username') continues to work.
    """
    # Prefer keyring-first across all platforms. If TUITTER_FORCE_KEYRING=1 is
    # set, we will attempt keyring and not fall back to file-based storage.
    # Enforce keyring-only storage. If keyring is not available or a write
    # operation fails, raise so callers can surface the error immediately.
    try:
        import keyring
    except Exception as e:
        logger.exception("auth_storage: keyring import failed")
        raise RuntimeError("keyring backend is not available") from e

    # Normalize incoming tokens
    tok = dict(tokens) if isinstance(tokens, dict) else {"access_token": tokens}

    access = tok.get("access_token")
    refresh = tok.get("refresh_token") or tok.get("refreshToken")
    idt = tok.get("id_token")

    # Persist each token as its own keyring entry to avoid backend blob size limits
    # (Windows Credential Manager can reject large blobs). We never write a large
    # single JSON blob — only small string entries.
    try:
        if access:
            keyring.set_password(SERVICE_NAME, "access_token", access)

        # Persist refresh token using chunking when necessary. Try a single
        # write first (simpler and compatible), but if it fails due to
        # backend limits, fall back to chunked storage using base64-encoded
        # pieces stored under keys: refresh_token.part{n} and a refresh_token.parts
        # index.
        if refresh:
            try:
                keyring.set_password(SERVICE_NAME, "refresh_token", refresh)
            except Exception:
                logger.debug("auth_storage: single refresh_token write failed; attempting chunked storage")
                _store_chunked_value("refresh_token", refresh)

        if idt:
            keyring.set_password(SERVICE_NAME, "id_token", idt)
        if username:
            try:
                keyring.set_password(SERVICE_NAME, "username", username)
            except Exception:
                logger.debug("auth_storage: failed to write username to keyring (non-fatal)")
        logger.debug("auth_storage: wrote token pieces to keyring")
    except Exception:
        logger.exception("auth_storage: failed to write token pieces to keyring")
        raise


def load_tokens() -> Optional[dict]:
    """Load the canonical full-token blob and return a normalized dict.

    Returns either None or {'tokens': <dict>, 'username': <str or None>}.
    The function will try keyring first and then the fallback file (which may
    be DPAPI-encrypted on Windows).
    """
    try:
        import keyring
    except Exception as e:
        logger.exception("auth_storage: keyring import failed on load")
        raise RuntimeError("keyring backend is not available") from e

    _write_debug(f"load_tokens: called; platform={platform.system()}")

    try:
        access = keyring.get_password(SERVICE_NAME, "access_token")
    except Exception:
        logger.exception("auth_storage: failed to read access_token from keyring")
        raise

    try:
        # Try single-key read first.
        refresh = keyring.get_password(SERVICE_NAME, "refresh_token")
    except Exception:
        logger.exception("auth_storage: failed to read refresh_token from keyring (single read)")
        raise

    # If single-key read returned None, attempt to read chunked parts
    if not refresh:
        try:
            refresh = _read_chunked_value("refresh_token")
        except Exception:
            logger.exception("auth_storage: failed to read chunked refresh_token from keyring")
            raise

    try:
        idt = keyring.get_password(SERVICE_NAME, "id_token")
    except Exception:
        logger.exception("auth_storage: failed to read id_token from keyring")
        raise

    try:
        username = keyring.get_password(SERVICE_NAME, "username")
    except Exception:
        username = None

    tokens = {}
    if access:
        tokens["access_token"] = access
    if refresh:
        tokens["refresh_token"] = refresh
    if idt:
        tokens["id_token"] = idt

    if tokens:
        _write_debug("load_tokens: found token pieces in keyring")
        return {"tokens": tokens, "username": username}

    return None


def clear_tokens() -> None:
    """Remove stored tokens and username from all backends (best-effort)."""
    try:
        import keyring
    except Exception as e:
        logger.exception("auth_storage: keyring import failed on clear")
        raise RuntimeError("keyring backend is not available") from e

    try:
        # Delete single keys
        for key in ("access_token", "refresh_token", "id_token", "username"):
            try:
                keyring.delete_password(SERVICE_NAME, key)
            except Exception:
                pass

        # Also remove any chunked parts for refresh_token (if present)
        try:
            _delete_chunked_value("refresh_token")
        except Exception:
            # non-fatal
            pass
    except Exception:
        logger.exception("auth_storage: unexpected error while clearing keyring entries")
        raise


def get_username() -> Optional[str]:
    """Return the canonical stored username (or None).

    This prefers the canonical token store (which may contain a username
    alongside tokens) but falls back to the legacy per-key 'username'
    entry in keyring for compatibility.
    """
    try:
        found = load_tokens()
        if found and isinstance(found, dict):
            uname = found.get("username")
            if uname:
                return uname
    except Exception:
        # proceed to legacy keyring lookup
        pass

    try:
        import keyring

        return keyring.get_password(SERVICE_NAME, "username")
    except Exception:
        return None

