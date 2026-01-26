from datetime import datetime, timedelta, timezone
import json
import os
import random
from pathlib import Path
from typing import List, Optional, Dict, Any, Iterable
from dataclasses import dataclass
import logging
import sys

import keyring
import requests
from dotenv import load_dotenv
from requests import Session
from .auth_storage import load_tokens, save_tokens_full, get_username
from .auth import refresh_tokens

# === lightweight data objects used by the UI ===
from .data_models import Notification

serviceKeyring = "tuitter"

load_dotenv(override=True)

# Make sure keyring service has default values. Prefer canonical store.
try:
    if not get_username():
        try:
            keyring.set_password(serviceKeyring, "username", "")
        except Exception:
            pass
except Exception:
    # Fallback: try direct keyring lookup if auth_storage import failed or errored
    try:
        if not keyring.get_password(serviceKeyring, "username"):
            try:
                keyring.set_password(serviceKeyring, "username", "")
            except Exception:
                pass
    except Exception:
        pass

# File-based debug logger (Textual swallows stdout/stderr in some modes)
_debug_logfile = Path.home() / ".tuitter_tokens_debug.log"
_debug_logger = logging.getLogger("tuitter.api.debug")
# Only enable the file-backed debug logger when TUITTER_DEBUG is explicitly set.
if os.getenv("TUITTER_DEBUG"):
    if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == str(_debug_logfile) for h in _debug_logger.handlers):
        try:
            fh = logging.FileHandler(_debug_logfile, encoding="utf-8")
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            _debug_logger.addHandler(fh)
        except Exception:
            # If file logging fails, fall back to normal logging handlers
            logging.getLogger("tuitter.api").exception("Failed to create debug logfile %s", _debug_logfile)
    _debug_logger.setLevel(logging.DEBUG)
else:
    # Ensure debug logger does not emit when TUITTER_DEBUG is not set
    _debug_logger.setLevel(logging.WARNING)

@dataclass
class User:
    id: int
    handle: str
    username: str
    display_name: str
    bio: str
    followers: int
    following: int
    posts_count: int
    ascii_pic: str = ""


@dataclass
class Post:
    id: str
    author: str
    content: str
    timestamp: datetime
    likes: int
    reposts: int
    comments: int
    liked_by_user: bool = False
    reposted_by_user: bool = False
    attachments: List[Dict[str, Any]] = None


@dataclass
class Message:
    id: int
    sender: str
    sender_handle: str  # Denormalized from user table per PostgreSQL schema
    content: str
    created_at: datetime
    is_read: bool = False


@dataclass
class Conversation:
    id: int
    participant_handles: List[str]
    last_message_preview: str
    last_message_at: datetime
    unread: bool = False


class Comment:
    def __init__(self, author: str, content: str, timestamp: datetime):
        self.author = author
        self.content = content
        self.timestamp = timestamp


@dataclass
class UserSettings:
    # Match backend SettingsResponse schema
    username: Optional[str] = None
    display_name: Optional[str] = None
    bio: Optional[str] = ""
    email_notifications: Optional[bool] = True
    show_online_status: Optional[bool] = True
    private_account: Optional[bool] = False
    github_connected: Optional[bool] = False
    gitlab_connected: Optional[bool] = False
    google_connected: Optional[bool] = False
    discord_connected: Optional[bool] = False
    ascii_pic: Optional[str] = ""

class APIInterface:
    def get_current_user(self) -> User: ...
    def set_handle(self, handle: str) -> None: ...
    def get_timeline(self, limit: int = 50) -> List[Post]: ...
    def get_discover_posts(self, limit: int = 50) -> List[Post]: ...
    def get_conversations(self) -> List[Conversation]: ...
    def get_conversation_messages(self, conversation_id: int) -> List[Message]: ...
    def send_message(self, conversation_id: int, content: str) -> Message: ...
    def get_or_create_dm(self, other_user_handle: str) -> Conversation: ...
    def get_notifications(self, unread_only: bool = False) -> List[Notification]: ...
    def mark_notification_read(self, notification_id: int) -> bool: ...
    def get_user_settings(self) -> UserSettings: ...
    def update_user_settings(self, settings: UserSettings) -> bool: ...
    def get_user_posts(self, handle: str, limit: int = 50) -> List[Post]: ...
    def get_user_comments(self, handle: str, limit: int = 100) -> List[Dict[str, Any]]: ...
    def create_post(self, content: str) -> bool: ...
    def like_post(self, post_id: int) -> bool: ...
    def unlike_post(self, post_id: int) -> bool: ...
    def repost(self, post_id: int) -> bool: ...
    def unrepost(self, post_id: int) -> bool: ...
    # comments
    def get_comments(self, post_id: int) -> List[Dict[str, Any]]: ...
    def add_comment(self, post_id: int, text: str) -> Dict[str, Any]: ...



class RealAPI(APIInterface):
    """Real API client that talks to an external HTTP backend.

    It expects a base_url like https://api.example.com and optional
    token-based auth via BACKEND_TOKEN env var.
    """
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 5.0, handle: str = "yourname"):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.handle = handle
        self.session: Session = requests.Session()
        # Track the currently-set bearer token (explicitly initialize)
        self.token: str | None = None
        if token:
            try:
                self.set_token(token)
            except Exception:
                pass

    # --- helpers ---
    def set_token(self, token: str) -> None:
        # Record token and update session header. Log a short preview (not the full token).
        logger = logging.getLogger("tuitter.api")
        self.token = token
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        try:
            kind = "jwt" if isinstance(token, str) and token.count('.') == 2 else "opaque"
            preview = (token[:10] + "...") if isinstance(token, str) and len(token) > 10 else token
            logger.info("Set API token type=%s preview=%s", kind, preview)
        except Exception:
            logger.debug("Set API token (unable to preview)")

    def _get(self, path: str, params: Dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, json_payload: Dict[str, Any] | None = None, params: Dict[str, Any] | None = None) -> Any:
        return self._request("POST", path, params=params, json_payload=json_payload)

    def _patch(self, path: str, json_payload: Dict[str, Any] | None = None, params: Dict[str, Any] | None = None) -> Any:
        return self._request("PATCH", path, params=params, json_payload=json_payload)

    def _request(self, method: str, path: str, params: Dict[str, Any] | None = None, json_payload: Dict[str, Any] | None = None, retry: bool = True) -> Any:
        """Internal request helper that will attempt a single refresh+retry on 401.

        - method: "GET" or "POST"
        - retry: if True the helper will attempt refresh and one retry on 401
        """
        logger = logging.getLogger("tuitter.api")
        if params is None:
            params = {}
        params.setdefault("handle", self.handle)
        url = f"{self.base_url}/{path.lstrip('/')}"

        try:
            m = method.upper()
            if m == "GET":
                resp = self.session.get(url, params=params, timeout=self.timeout)
            elif m == "POST":
                resp = self.session.post(url, params=params, json=json_payload, timeout=self.timeout)
            elif m == "PATCH":
                resp = self.session.patch(url, params=params, json=json_payload, timeout=self.timeout)
            else:
                # Fallback to requests.request for other verbs
                resp = self.session.request(m, url, params=params, json=json_payload, timeout=self.timeout)

            # If we received an auth-related response (400/401/403), try centralized restore once
            if resp.status_code in (400, 401, 403) and retry:
                logger.info(
                    "API auth-failure %s received for %s %s - attempting try_restore_session()",
                    resp.status_code,
                    method,
                    path,
                )
                try:
                    restored = False
                    if hasattr(self, "try_restore_session"):
                        restored = self.try_restore_session()
                    if restored:
                        logger.info("try_restore_session succeeded; retrying original request")
                        if method.upper() == "GET":
                            resp = self.session.get(url, params=params, timeout=self.timeout)
                        else:
                            resp = self.session.post(url, params=params, json=json_payload, timeout=self.timeout)
                    else:
                        logger.debug("try_restore_session returned False; not retrying")
                except Exception:
                    logger.exception("Refresh attempt failed (non-fatal) while handling initial auth failure")

            resp.raise_for_status()
            return resp.json()

        except requests.HTTPError as e:
            status = None
            try:
                status = e.response.status_code if e.response is not None else None
            except Exception:
                pass

            # If we got an auth-related HTTP error (400/401/403) and haven't retried yet, try centralized restore and retry once
            if status in (400, 401, 403) and retry:
                logger.info(
                    "HTTPError %s; attempting try_restore_session() and retry for %s %s",
                    status,
                    method,
                    path,
                )
                try:
                    if hasattr(self, "try_restore_session") and self.try_restore_session():
                        logger.info("try_restore_session succeeded from exception path; retrying (no further retry allowed)")
                        return self._request(method, path, params=params, json_payload=json_payload, retry=False)
                    logger.debug("try_restore_session did not restore session from exception path")
                except Exception:
                    logger.exception("Refresh attempt failed (non-fatal) while handling auth error (exception path)")

            # Re-raise original HTTP error if refresh didn't succeed or cannot be performed
            raise

    def get_current_user(self) -> User:
        data = self._get("/me")
        return User(**data)

    def get_timeline(self, limit: int = 50) -> List[Post]:
        data = self._get("/timeline", params={"limit": limit})
        return [Post(**self._convert_post(p)) for p in data]

    def get_discover_posts(self, limit: int = 50) -> List[Post]:
        data = self._get("/discover", params={"limit": limit})
        return [Post(**self._convert_post(p)) for p in data]

    def get_conversations(self) -> List[Conversation]:
        data = self._get("/conversations")
        return [self._convert_conversation(c) for c in data]

    def get_conversation_messages(self, conversation_id: int) -> List[Message]:
        data = self._get(f"/conversations/{conversation_id}/messages")
        return [self._convert_message(m) for m in data]

    def send_message(self, conversation_id: int, content: str) -> Message:
        # Backend expects sender_handle in the request body
        data = self._post(
            f"/conversations/{conversation_id}/messages",
            json_payload={"content": content, "sender_handle": self.handle},
        )
        return self._convert_message(data)

    def get_or_create_dm(self, other_user_handle: str) -> Conversation:
        """Get or create a direct message conversation with another user"""
        data = self._post(
            "/dm",
            json_payload={
                "user_a_handle": self.handle,
                "user_b_handle": other_user_handle
            }
        )
        return self._convert_conversation(data)

    def get_notifications(self, unread_only: bool = False) -> List[Notification]:
        # Backend uses 'unread' parameter, not 'unread_only'
        params = {"unread": "true"} if unread_only else {}
        data = self._get("/notifications", params=params)
        notif_fields = Notification.__dataclass_fields__.keys()
        filtered = [{k: v for k, v in n.items() if k in notif_fields} for n in data]
        return [Notification(**n) for n in filtered]

    def mark_notification_read(self, notification_id: int) -> bool:
        self._post(f"/notifications/{notification_id}/read")
        return True

    def mark_conversation_read(self, conversation_id: int) -> bool:
        """Notify backend that the current user has read the conversation."""
        self._post(f"/conversations/{conversation_id}/read")
        return True

    def get_user_settings(self) -> UserSettings:
        data = self._get("/settings")
        # Filter out fields that don't belong to UserSettings
        # (API may return username, display_name, bio which belong to User model)
        settings_fields = {
            'user_id', 'email_notifications', 'show_online_status',
            'private_account', 'github_connected', 'gitlab_connected',
            'google_connected', 'discord_connected', 'ascii_pic', 'updated_at'
        }
        filtered_data = {k: v for k, v in data.items() if k in settings_fields}
        return UserSettings(**filtered_data)

    def update_user_settings(self, settings: UserSettings) -> bool:
        # Use PATCH for partial updates. Only send fields that are not None
        try:
            payload = {k: v for k, v in settings.__dict__.items() if v is not None}
        except Exception:
            payload = settings.__dict__
        self._patch("/settings", json_payload=payload)
        return True

    def get_user_posts(self, handle: str, limit: int = 50) -> List[Post]:
        data = self._get("/posts", params={"handle": handle, "limit": limit})
        # Expect list of post dicts
        return [Post(**self._convert_post(p)) for p in data]

    def get_user_comments(self, handle: str, limit: int = 100) -> List[Dict[str, Any]]:
        data = self._get("/comments", params={"handle": handle, "limit": limit})
        return data

    def get_user_profile(self, handle: str) -> User:
        """Fetch canonical user profile from backend.

        Raises requests.HTTPError on non-2xx (404 will be raised by _request).
        """
        data = self._get(f"/users/{handle}")
        # Backend returns fields compatible with User dataclass
        return User(**data)

    def create_post(self, content: str) -> Post:
        # Check if content is JSON string containing attachments
        try:
            post_data = json.loads(content)
            data = self._post("/posts", json_payload=post_data)
        except json.JSONDecodeError:
            # If not JSON, treat as simple text post
            data = self._post("/posts", json_payload={"content": content})
        return Post(**self._convert_post(data))

    def like_post(self, post_id: int) -> bool:
        self._post(f"/posts/{post_id}/like")
        return True

    def unlike_post(self, post_id: int) -> bool:
        # Backend must support unliking via DELETE or a dedicated endpoint; use a symmetric endpoint here
        try:
            self._post(f"/posts/{post_id}/unlike")
            return True
        except Exception:
            # Try a fallback: call the like endpoint with a param 'undo'
            try:
                self._post(f"/posts/{post_id}/like", params={"undo": "1"})
                return True
            except Exception:
                raise

    def repost(self, post_id: int) -> bool:
        self._post(f"/posts/{post_id}/repost")
        return True

    def unrepost(self, post_id: int) -> bool:
        try:
            self._post(f"/posts/{post_id}/unrepost")
            return True
        except Exception:
            try:
                self._post(f"/posts/{post_id}/repost", params={"undo": "1"})
                return True
            except Exception:
                raise

    def get_comments(self, post_id: int) -> List[Dict[str, Any]]:
        data = self._get(f"/posts/{post_id}/comments")
        return data

    def add_comment(self, post_id: int, text: str) -> Dict[str, Any]:
        data = self._post(f"/posts/{post_id}/comments", json_payload={"text": text})
        return data

    # --- conversion helpers ---
    def _convert_post(self, p: Dict[str, Any]) -> Dict[str, Any]:
        # Ensure fields match Post dataclass naming
        # Normalize timestamp into a datetime object (local naive)
        ts_raw = p.get("timestamp")
        timestamp = None
        try:
            if isinstance(ts_raw, datetime):
                timestamp = ts_raw
            elif isinstance(ts_raw, str):
                # If the string contains an explicit timezone (Z or ±HH:MM), parse
                # it as an aware datetime. If it lacks timezone info, assume the
                # server returned UTC (common for ISO timestamps without a suffix)
                # and convert to local time.
                try:
                    s = ts_raw
                    has_tz = s.endswith("Z") or ("+" in s[10:] or "-" in s[10:])
                    if has_tz:
                        # Normalize trailing Z to +00:00 then parse as aware
                        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                    else:
                        # No timezone info: treat as UTC
                        dt = datetime.fromisoformat(s)
                        dt = dt.replace(tzinfo=timezone.utc)

                    # Convert to local timezone and return naive local datetime
                    timestamp = dt.astimezone().replace(tzinfo=None)
                except Exception:
                    # Last-resort parse: use now
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()
        except Exception:
            timestamp = datetime.now()

        try:
            logging.getLogger("tuitter.api").debug(
                "_convert_post: raw timestamp=%r parsed=%r for post id=%s",
                ts_raw,
                timestamp,
                p.get("id"),
            )
        except Exception:
            pass

        out = dict(
            id=str(p.get("id")),
            author=p.get("author") or p.get("username") or p.get("user"),
            content=p.get("content") or p.get("text") or "",
            timestamp=timestamp,
            likes=int(p.get("likes") or 0),
            reposts=int(p.get("reposts") or 0),
            comments=int(p.get("comments") or 0),
            liked_by_user=bool(p.get("liked_by_user") or p.get("liked") or False),
            reposted_by_user=bool(
                p.get("reposted_by_user") or p.get("reposted") or False
            ),
            attachments=p.get("attachments", [])  # Add attachments to the post object
        )
        return out

    def _convert_conversation(self, c: Dict[str, Any]) -> Conversation:
        """Convert backend conversation response to Conversation dataclass"""
        # Backend uses 'created_at' but we need 'last_message_at'
        last_message_at_value = c.get("last_message_at") or c.get("created_at")

        return Conversation(
            id=int(c.get("id", 0)),
            participant_handles=c.get("participant_handles") or [],
            last_message_preview=c.get("last_message_preview") or "",
            last_message_at=last_message_at_value
            if isinstance(last_message_at_value, datetime)
            else datetime.fromisoformat(last_message_at_value)
            if last_message_at_value
            else datetime.now(),
            # Normalize 'unread' which may be boolean, numeric or string
            unread=(
                (c.get("unread") is True)
                if isinstance(c.get("unread"), bool)
                else (str(c.get("unread")).lower() in ("true", "1", "yes"))
            ),
        )

    def _convert_message(self, m: Dict[str, Any]) -> Message:
        """Convert backend message response to Message dataclass"""
        # Normalize timestamp into a local naive datetime using same rules as posts
        ts_raw = m.get("timestamp") or m.get("created_at")

        created_at = None
        try:
            if isinstance(ts_raw, datetime):
                created_at = ts_raw
            elif isinstance(ts_raw, str):
                try:
                    s = ts_raw
                    # If the string contains an explicit timezone (Z or ±HH:MM), parse
                    # it as an aware datetime. If it lacks timezone info, assume the
                    # server returned UTC and convert to local time.
                    has_tz = s.endswith("Z") or ("+" in s[10:] or "-" in s[10:])
                    if has_tz:
                        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                    else:
                        dt = datetime.fromisoformat(s)
                        dt = dt.replace(tzinfo=timezone.utc)

                    # Convert to local timezone and return naive local datetime
                    created_at = dt.astimezone().replace(tzinfo=None)
                except Exception:
                    created_at = datetime.now()
            else:
                created_at = datetime.now()
        except Exception:
            created_at = datetime.now()

        return Message(
            id=int(m.get("id", 0)),
            sender=m.get("sender") or m.get("sender_handle") or self.handle,
            sender_handle=m.get("sender_handle") or m.get("sender") or self.handle,
            content=m.get("content") or "",
            created_at=created_at,
            is_read=bool(m.get("is_read") or False),
        )

    def try_restore_session(self) -> bool:
        """Attempt to restore session from stored credentials.

        This uses the centralized auth.get_stored_credentials() helper which
        will attempt a refresh if only a refresh token is present. On success
        the API token and handle are set and True is returned. Otherwise
        False is returned.
        """
        logger = logging.getLogger("tuitter.api")
        _debug_logger.debug("try_restore_session: called")
        try:
            # Use auth_storage directly so we can see both full tokens and a
            # separate refresh token. This lets us verify the token is still
            # valid and attempt a refresh if necessary.
            from .auth_storage import load_tokens as _load
            found = _load()
            _debug_logger.debug("try_restore_session: load_tokens returned %s", type(found).__name__)

            if not found:
                _debug_logger.debug("try_restore_session: no stored tokens found")
                return False

            # Normalize common shapes: dict or JSON string
            if isinstance(found, str):
                try:
                    found = json.loads(found)
                    _debug_logger.debug("try_restore_session: parsed json token blob")
                except Exception:
                    _debug_logger.exception("try_restore_session: failed to parse token string")
                    return False

            # If we have a full token blob, try to validate it with a light /me call.
            if isinstance(found, dict) and 'tokens' in found and isinstance(found['tokens'], dict):
                tokens = found['tokens']
                username = found.get('username') or None
                access = tokens.get('access_token')
                refresh = tokens.get('refresh_token') or found.get('refresh_token')

                _debug_logger.debug("try_restore_session: found tokens keys=%s username=%s", list(tokens.keys()), username)

                if access:
                    try:
                        self.set_token(access)
                        _debug_logger.debug("try_restore_session: applied access token to session headers")
                    except Exception:
                        _debug_logger.exception("try_restore_session: set_token failed")
                    if username:
                        self.handle = username

                    # Quick validation call (include handle param required by backend)
                    try:
                        resp = self.session.get(f"{self.base_url}/me", params={"handle": self.handle}, timeout=self.timeout)
                        _debug_logger.debug("try_restore_session: /me validation status=%s", getattr(resp, 'status_code', None))
                        if resp.ok:
                            return True
                        if resp.status_code == 401:
                            # Try to refresh if we have a refresh token
                            if refresh:
                                try:
                                    new_tokens = refresh_tokens(refresh)
                                    _debug_logger.debug("try_restore_session: refresh_tokens returned type=%s", type(new_tokens).__name__)
                                    if new_tokens and isinstance(new_tokens, dict) and new_tokens.get('access_token'):
                                        try:
                                            self.set_token(new_tokens['access_token'])
                                        except Exception:
                                            _debug_logger.exception("try_restore_session: set_token failed after refresh")
                                        try:
                                            save_tokens_full(new_tokens, username)
                                            _debug_logger.debug("try_restore_session: saved refreshed tokens")
                                        except Exception:
                                            _debug_logger.exception("try_restore_session: save_tokens_full failed (non-fatal)")
                                        return True
                                except Exception:
                                    _debug_logger.exception("try_restore_session: refresh failed")
                            return False
                        # Other non-auth failures - treat as restore failure
                        return False
                    except Exception:
                        _debug_logger.exception("try_restore_session: validation request failed")
                        # Fallthrough to attempt refresh if possible
                        if refresh:
                            try:
                                new_tokens = refresh_tokens(refresh)
                                if new_tokens and isinstance(new_tokens, dict) and new_tokens.get('access_token'):
                                    try:
                                        self.set_token(new_tokens['access_token'])
                                    except Exception:
                                        _debug_logger.exception("try_restore_session: set_token failed after validation failure")
                                    try:
                                        save_tokens_full(new_tokens, username)
                                    except Exception:
                                        _debug_logger.exception("try_restore_session: save_tokens_full failed (non-fatal)")
                                    if username:
                                        self.handle = username
                                    return True
                            except Exception:
                                _debug_logger.exception("try_restore_session: refresh after validation failure failed")
                        return False

            # If we only have a refresh token, try to refresh now
            if isinstance(found, dict) and 'refresh_token' in found and found.get('refresh_token'):
                refresh = found.get('refresh_token')
                username = found.get('username') or None
                _debug_logger.debug("try_restore_session: refresh-only blob found username=%s", username)
                try:
                    new_tokens = refresh_tokens(refresh)
                    _debug_logger.debug("try_restore_session: refresh_tokens returned type=%s", type(new_tokens).__name__)
                    if new_tokens and isinstance(new_tokens, dict) and new_tokens.get('access_token'):
                        try:
                            self.set_token(new_tokens['access_token'])
                        except Exception:
                            _debug_logger.exception("try_restore_session: set_token failed after refresh-only")
                        try:
                            save_tokens_full(new_tokens, username)
                        except Exception:
                            _debug_logger.exception("try_restore_session: save_tokens_full failed (non-fatal)")
                        if username:
                            self.handle = username
                        return True
                except Exception:
                    _debug_logger.exception("try_restore_session: refresh_tokens failed for refresh-only blob")

            _debug_logger.debug("try_restore_session: no usable tokens or refresh failed")
            return False
        except Exception as e:
            _debug_logger.exception("try_restore_session failed: %s", e)
            logging.getLogger("tuitter.api").exception("try_restore_session failed: %s", e)
            return False

# Global api selection: prefer real backend when BACKEND_URL is set
# Allow overriding backend URL via environment for local development
_BACKEND_URL = os.getenv("BACKEND_URL") or "https://voqbyhcnqe.execute-api.us-east-2.amazonaws.com"

# Initialize global `api` client. Prefer the saved username from auth_storage
# (keyring) when available so requests that rely on `api.handle` use the
# correct account rather than the literal default "yourname".
if _BACKEND_URL:
    try:
        # get_username was imported earlier from auth_storage when available
        initial_handle = "None"
        initial_handle = get_username()
    except Exception:
        pass

    api = RealAPI(base_url=_BACKEND_URL, handle=initial_handle)
