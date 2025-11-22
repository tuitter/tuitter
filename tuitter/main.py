from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import (
    Container,
    Horizontal,
    Vertical,
    VerticalScroll,
    ScrollableContainer,
)
from textual.widgets import Static, Input, Button, TextArea, Label, RichLog
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.message import Message
from datetime import datetime
from .api_interface import api
import sys
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import filedialog
from PIL import Image
from .ascii_video_widget import ASCIIVideoPlayer
import json
from typing import List, Dict
from rich.text import Text
import logging
import time
import webbrowser
import keyring
import os
import dotenv

dotenv.load_dotenv()

serviceKeyring = "tuitter"

# Prefer canonical username lookup from auth_storage which handles
# chunked tokens and centralized storage (falls back to legacy keyring).
try:
    from .auth_storage import get_username
except Exception:
    # Import-time failures should not break the UI; fall back to a no-op getter.
    def get_username():
        try:
            import keyring

            return keyring.get_password(serviceKeyring, "username")
        except Exception:
            return None

# Service name for keyring storage


# Custom message for draft updates
class DraftsUpdated(Message):
    """Posted when drafts are updated."""

    pass


class AuthenticationCompleted(Message):
    """Posted when authentication completes successfully."""

    def __init__(self, username: str) -> None:
        super().__init__()
        self.username = username


class AuthenticationFailed(Message):
    """Posted when authentication fails."""

    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


# Drafts file path
DRAFTS_FILE = Path.home() / ".proj101_drafts.json"


def load_drafts() -> List[Dict]:
    """Load drafts from local storage."""
    if not DRAFTS_FILE.exists():
        return []
    try:
        with open(DRAFTS_FILE, "r") as f:
            drafts = json.load(f)
            # Convert timestamp strings back to datetime objects
            for draft in drafts:
                draft["timestamp"] = datetime.fromisoformat(draft["timestamp"])
            return drafts
    except Exception:
        return []


def save_drafts(drafts: List[Dict]) -> None:
    """Save drafts to local storage."""
    try:
        # Convert datetime objects to ISO format strings
        drafts_to_save = []
        for draft in drafts:
            draft_copy = draft.copy()
            draft_copy["timestamp"] = draft["timestamp"].isoformat()
            drafts_to_save.append(draft_copy)

        with open(DRAFTS_FILE, "w") as f:
            json.dump(drafts_to_save, f, indent=2)
    except Exception as e:
        print(f"Error saving drafts: {e}")


def add_draft(content: str, attachments: List = None) -> None:
    """Add a new draft and maintain max 2 drafts."""
    drafts = load_drafts()

    # Create new draft
    new_draft = {
        "content": content,
        "attachments": attachments or [],
        "timestamp": datetime.now(),
    }

    # Add new draft
    drafts.append(new_draft)

    # Sort by timestamp (oldest first)
    drafts.sort(key=lambda x: x["timestamp"])

    # Keep only the 2 most recent drafts
    if len(drafts) > 2:
        drafts = drafts[-2:]

    save_drafts(drafts)


def delete_draft(index: int) -> None:
    """Delete a specific draft by index."""
    drafts = load_drafts()
    if 0 <= index < len(drafts):
        drafts.pop(index)
        save_drafts(drafts)


def format_time_ago(dt: datetime) -> str:
    """Format datetime as 'time ago' string."""
    # Normalize 'now' to the same tz-awareness as dt to avoid incorrect deltas
    if dt is None:
        return "just now"
    try:
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    except Exception:
        now = datetime.now()

    delta = now - dt
    total_seconds = int(delta.total_seconds())
    if total_seconds < 10:
        return "just now"
    if total_seconds < 60:
        return f"{total_seconds}s ago"
    minutes = total_seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


# ───────── Main UI Screen (not auth) ─────────
class MainUIScreen(Screen):
    """The main authenticated app screen with timeline/discover/etc."""

    def __init__(self, starting_view: str = "timeline"):
        super().__init__()
        self.starting_view = starting_view

    def compose(self) -> ComposeResult:
        username = get_username() or "yourname"
        yield Static(
            f"tuitter [{self.starting_view}] @{username}", id="app-header", markup=False
        )
        yield TopNav(id="top-navbar", current=self.starting_view)

        # Show the appropriate content based on starting_view
        if self.starting_view == "timeline":
            yield TimelineScreen(id="screen-container")
        elif self.starting_view == "discover":
            yield DiscoverScreen(id="screen-container")
        elif self.starting_view == "notifications":
            yield NotificationsScreen(id="screen-container")
        elif self.starting_view == "messages":
            yield MessagesScreen(id="screen-container")
        elif self.starting_view == "settings":
            yield SettingsScreen(id="screen-container")
        else:
            yield TimelineScreen(id="screen-container")

        yield Static(
            "[1-5] Screens [p] Profile [d] Drafts [j/k] Navigate [:n] New Post [:q] Quit",
            id="app-footer",
            markup=False,
        )
        yield Static("", id="command-bar")

        # Auth Debug Log - only show if TUITTER_DEBUG environment variable is set
        if os.getenv("TUITTER_DEBUG"):
            auth_log = RichLog(id="auth-log", highlight=True, markup=True)
            auth_log.styles.height = "10"
            auth_log.styles.border = ("solid", "yellow")
            auth_log.border_title = "Auth Debug Log"
            yield auth_log

    def on_mount(self) -> None:
        """When the MainUIScreen is mounted by the mode switch, ensure the
        initial content (timeline) receives focus. This covers the case where
        the App.switch_mode('main') path triggers the mode mount and previous
        scheduling in App.show_main_app was too early.
        """
        try:
            # Schedule focusing after the screen's layout settles
            try:
                # Ask the App to focus initial content after refresh
                self.app.call_after_refresh(self.app._focus_initial_content)
            except Exception:
                pass

            # Conservative fallback: small delayed timer to cover slow mounts
            try:
                self.app.set_timer(0.05, self.app._focus_initial_content)
            except Exception:
                pass
        except Exception:
            pass


# ───────── Auth Screen ─────────
class AuthScreen(Screen):
    """Authentication screen using Textual Screen for auth flow.

    Making this a Screen lets the App push/pop it using native Textual
    navigation which avoids layout races when switching between auth and
    main UI.
    """

    def compose(self) -> ComposeResult:
        # Minimal auth screen: centered sign-in button
        with Container(id="auth-wrapper"):
            with Container(id="auth-center"):
                yield Static(
                    "Continue in your browser", id="auth-title", classes="signin"
                )
                with Container(id="oauth-signin-container"):
                    # Make this the app's primary button so global Button.-primary styles apply
                    yield Button(
                        "Sign In",
                        id="oauth-signin",
                        variant="primary",
                        classes="signin",
                    )

        # Status text should appear outside and below the cyan card so it's visually
        # separated from the dialog. Center it horizontally.
        yield Static("", id="auth-status", classes="signin")
        # Small hint so users know Enter will activate the sign-in
        yield Static("press Enter to sign in", id="auth-hint", classes="signin")

        yield Static("press q to quit", id="quit-label", classes="signin")

    def on_mount(self) -> None:
        """Called when the AuthScreen is mounted."""
        import sys

        try:
            # Use App-level logging so it respects TUITTER_DEBUG and in-TUI RichLog
            self.app.log_auth_event("AuthScreen.on_mount CALLED")
        except Exception:
            pass
        try:
            button = self.query_one("#oauth-signin", Button)
            try:
                self.app.log_auth_event(f"Found button: {button.id}")
            except Exception:
                pass
        except Exception as e:
            try:
                self.app.log_auth_event(f"Failed to find button: {e}")
            except Exception:
                pass

        try:
            self.app.log_auth_event("AuthScreen.on_mount: Screen mounted")
        except Exception:
            pass

        # Attempt a silent restore here so if tokens are present (written by
        # another session) we immediately switch to the main UI without
        # requiring the user to quit/reopen. This mirrors App.on_mount but
        # runs when the AuthScreen becomes active.
        try:
            # Prefer the API's proactive restore which validates the token and
            # attempts refresh if needed. This avoids switching to the main UI
            # with an expired token which would crash during compose.
            try:
                restored = api.try_restore_session()
            except Exception:
                restored = False

            try:
                self.app.log_auth_event(
                    f"AuthScreen.on_mount: silent-restore restored={restored}"
                )
            except Exception:
                pass

            if restored:
                try:
                    # Let the App mount the main UI; tokens are already set on api
                    self.app.show_main_app()
                    return
                except Exception:
                    try:
                        self.app.log_auth_event(
                            "AuthScreen.on_mount: silent restore failed during show_main_app"
                        )
                    except Exception:
                        pass
        except Exception:
            # Don't let silent-restore errors prevent the auth screen from working
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle sign-in button press."""
        import sys

        try:
            self.app.log_auth_event(f"BUTTON PRESSED: {event.button.id}")
        except Exception:
            pass

        if event.button.id == "oauth-signin":
            try:
                self.app.log_auth_event("Sign-in button confirmed")
            except Exception:
                pass
            # Update status immediately
            try:
                self.query_one("#auth-status", Static).update("Opening browser...")
                try:
                    self.app.log_auth_event("Updated status text")
                except Exception:
                    pass
            except Exception as e:
                try:
                    self.app.log_auth_event(f"Failed to update status: {e}")
                except Exception:
                    pass

            # Schedule the OAuth flow
            try:
                self.app.log_auth_event("About to call call_after_refresh")
            except Exception:
                pass
            self.call_after_refresh(self._start_auth_flow)
            try:
                self.app.log_auth_event("call_after_refresh returned")
            except Exception:
                pass

    def key_enter(self) -> None:
        """Allow Enter to trigger the auth flow even when the button isn't focused.

        If the Button has keyboard focus it will handle Enter itself, so skip in
        that case to avoid double-triggering.
        """
        try:
            btn = self.query_one("#oauth-signin", Button)
            if getattr(btn, "has_focus", False):
                return
        except Exception:
            # No button found - still allow flow to start
            pass

        try:
            # Mirror the same behaviour as clicking the button
            self.query_one("#auth-status", Static).update("Opening browser...")
        except Exception:
            pass
        # Schedule the OAuth flow on the UI thread
        self.call_after_refresh(self._start_auth_flow)

    def _start_auth_flow(self) -> None:
        """Start the OAuth flow using simplified auth module."""
        # Run authenticate() in a background thread so the Textual event loop
        # stays responsive. Marshal UI updates back to the main thread using
        # call_from_thread / app.call_from_thread.
        from .auth import authenticate, AuthError
        import threading
        import sys

        # Log immediately that this method was called
        if os.getenv("TUITTER_DEBUG"):
            # Keep a very early guard to avoid spamming when debug not set
            try:
                self.app.log_auth_event("_start_auth_flow CALLED")
            except Exception:
                pass
        try:
            self.app.log_auth_event(
                "_start_auth_flow: Method called, about to start worker thread"
            )
        except Exception:
            try:
                self.app.log_auth_event("Failed to log start_auth_flow")
            except Exception:
                pass

        def _ui_call(fn):
            # Try to schedule a callable on the UI thread. Prefer Screen.call_from_thread
            # then App.call_from_thread, falling back to posting a no-op if unavailable.
            try:
                self.call_from_thread(fn)
            except Exception:
                try:
                    # Schedule the callable on the App thread
                    self.app.call_from_thread(fn)
                except Exception:
                    # Last-resort: post a message to trigger the UI loop
                    try:
                        self.app.call_from_thread(
                            lambda: self.post_message(DraftsUpdated())
                        )
                    except Exception:
                        pass

        def worker():
            try:
                # Wrap authenticate() call to catch ANY exception including Windows keyring errors
                result = None
                try:
                    result = authenticate()
                except Exception as auth_exc:
                    # Authentication failed - could be keyring error, network error, etc.
                    # Try to read any tokens that might have been saved to fallback file
                    # despite the exception (keyring errors often still save to fallback)
                    try:
                        from .auth import get_stored_credentials

                        creds = get_stored_credentials()
                        if creds and isinstance(creds, dict):
                            result = creds
                        else:
                            # No fallback credentials available - re-raise the auth error
                            raise
                    except Exception:
                        # Could not recover - re-raise original exception
                        raise auth_exc from None

                if not result:
                    raise AuthError("Authentication returned no result")

                # CRITICAL FIX: Set credentials IMMEDIATELY in the worker thread
                # Don't wait for UI thread to process them - this is thread-safe
                username = ""
                try:
                    tokens = result.get("tokens") if isinstance(result, dict) else None
                    username = (
                        result.get("username", "") if isinstance(result, dict) else ""
                    )

                    # Require an access_token from the OAuth exchange; do not accept id_token
                    if tokens and isinstance(tokens, dict) and "access_token" in tokens:
                        # Set access token immediately - this is thread-safe
                        api.set_token(tokens["access_token"])

                    if username:
                        # Set API handle immediately
                        api.handle = username

                        # Ensure user exists in DB (do this in worker thread)
                        try:
                            user_profile = api.get_current_user()
                        except Exception:
                            pass
                except Exception:
                    pass

                # Post a message and try to directly trigger the UI transition on the
                # application's main thread. We do multiple attempts to be robust
                # across Textual versions / environments where call_from_thread or
                # message routing may behave differently.
                def on_success():
                    try:
                        # Update status text if widget present
                        try:
                            self.query_one("#auth-status", Static).update(
                                "✓ Successfully signed in!"
                            )
                        except Exception:
                            pass
                        # Ensure tokens are picked up and main UI mounted - pass credentials
                        try:
                            self.app.show_main_app(credentials=result)
                        except Exception:
                            pass

                    except Exception:
                        pass

                try:
                    # 1) Post AuthenticationCompleted message
                    try:
                        self.app.call_from_thread(
                            lambda: self.post_message(
                                AuthenticationCompleted(username=username)
                            )
                        )
                    except Exception:
                        try:
                            # Some Textual versions route messages differently; try posting on screen
                            self.post_message(
                                AuthenticationCompleted(username=username)
                            )
                        except Exception:
                            pass

                    # 2) Set reactive flag on App
                    try:
                        self.app.call_from_thread(
                            lambda: setattr(self.app, "authenticated", True)
                        )
                    except Exception:
                        try:
                            setattr(self.app, "authenticated", True)
                        except Exception:
                            pass

                    # 3) Directly ask the App to show main UI (best-effort)
                    # Pass credentials directly to avoid file I/O race conditions

                    def transition_to_main():
                        try:
                            # Schedule show_main_app on the next event loop iteration
                            # This ensures all current event processing is complete first
                            self.app.call_later(
                                lambda: self.app.show_main_app(credentials=result)
                            )
                        except Exception:
                            pass

                    try:
                        # Use call_from_thread to schedule the transition on the main thread
                        self.app.call_from_thread(transition_to_main)
                    except Exception:
                        # Fallback: try direct call (might work if already on main thread)
                        try:
                            self.app.show_main_app(credentials=result)
                        except Exception:
                            pass

                except Exception:
                    # Last-resort: schedule on-success closure via _ui_call
                    _ui_call(on_success)

            except AuthError as e:
                # Post a message on the UI thread with failure
                try:
                    self.app.call_from_thread(
                        lambda: self.post_message(AuthenticationFailed(error=str(e)))
                    )
                except Exception:

                    def on_auth_fail():
                        try:
                            self.query_one("#auth-status", Static).update(
                                f"⚠️ Auth failed: {str(e)}"
                            )
                        except Exception:
                            pass
                        try:
                            self.app.notify("Authentication failed", severity="error")
                        except Exception:
                            pass

                    _ui_call(on_auth_fail)

            except Exception as e:
                try:
                    self.app.call_from_thread(
                        lambda: self.post_message(AuthenticationFailed(error=str(e)))
                    )
                except Exception:

                    def on_exc():
                        try:
                            self.query_one("#auth-status", Static).update(
                                "⚠️ An error occurred"
                            )
                        except Exception:
                            pass
                        try:
                            self.app.notify(str(e), severity="error")
                        except Exception:
                            pass

                    _ui_call(on_exc)

        try:
            self.app.log_auth_event("Creating worker thread")
        except Exception:
            pass
        t = threading.Thread(target=worker, daemon=True)
        try:
            self.app.log_auth_event("Starting worker thread")
        except Exception:
            pass
        t.start()
        try:
            self.app.log_auth_event("Worker thread started")
        except Exception:
            pass
        try:
            self.app.log_auth_event(
                "_start_auth_flow: Worker thread created and started"
            )
        except Exception:
            try:
                self.app.log_auth_event("Failed to log thread start")
            except Exception:
                pass

    # Message handlers for authentication results
    def on_authentication_completed(self, message: AuthenticationCompleted) -> None:
        """Handle successful authentication message."""
        try:
            # Update status - the worker thread already called show_main_app with credentials
            try:
                self.query_one("#auth-status", Static).update(
                    "✓ Successfully signed in!"
                )
            except Exception:
                pass
            # NOTE: Don't call show_main_app() here - it's already being called from the worker
            # thread with the correct credentials. Calling it again would overwrite with defaults.
        except Exception:
            pass

    def on_authentication_failed(self, message: AuthenticationFailed) -> None:
        """Handle failed authentication message."""
        try:
            try:
                self.query_one("#auth-status", Static).update(
                    f"⚠️ Auth failed: {message.error}"
                )
            except Exception:
                pass
            try:
                self.app.notify("Authentication failed", severity="error")
            except Exception:
                pass
        except Exception:
            pass


# ───────── Comment Screen ─────────
class CommentFeed(VerticalScroll):
    """Comment feed modeled after DiscoverFeed"""

    cursor_position = reactive(0)  # 0 = post, 1 = input, 2+ = comments
    scroll_y = reactive(0)  # Track scroll position

    def __init__(self, post, **kwargs):
        super().__init__(**kwargs)
        self.post = post
        self.comments = []

    def compose(self):
        # Post at the top
        yield Static("─ Post ─", classes="comment-thread-header", markup=False)
        yield PostItem(self.post)

        yield Static("─ Comments ─", classes="comment-thread-header", markup=False)

        # Input for new comment
        yield Input(
            placeholder="[i] to comment... Press Enter to submit",
            id="comment-input",
        )

        # Comments
        self.comments = api.get_comments(self.post.id)
        logging.debug(f"[compose] Comments fetched: {self.comments}")

        for i, c in enumerate(self.comments):
            author = c.get("user", "unknown")
            content = c.get("text", "")
            timestamp = (
                c.get("timestamp") or c.get("created_at") or datetime.now().isoformat()
            )
            try:
                c_time = format_time_ago(datetime.fromisoformat(timestamp))
            except Exception:
                c_time = "just now"
            comment = Static(
                f"  @{author} • {c_time}\n  {content}\n",
                classes="comment-thread-item comment-item",
                id=f"comment-{i}",
                markup=False,
            )
            comment.styles.background = "#282A36"  # Force dark background
            yield comment

    def on_mount(self) -> None:
        """Watch cursor position for updates"""
        self.watch(self, "cursor_position", self._update_cursor)
        self.watch(self, "scroll_y", self._check_scroll_load)

    def _check_scroll_load(self) -> None:
        """Check if we need to load more comments based on scroll position"""
        # Not needed for comments but keeping pattern consistent
        pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle comment submission"""
        if event.input.id != "comment-input":
            return
        text = event.value.strip()
        if not text:
            return

        api.add_comment(self.post.id, text)

        # Clear input
        event.input.value = ""
        event.input.blur()

        # Refresh comments
        self._refresh_comments()

        # Show notification
        if hasattr(self.app, "notify"):
            self.app.notify("Comment posted!", timeout=2)

    def _refresh_comments(self) -> None:
        """Refresh the comment list"""
        try:
            # Remove existing comment items
            for item in self.query(".comment-item"):
                item.remove()

            # Fetch updated comments
            self.comments = api.get_comments(self.post.id)

            # Add new comments
            for i, c in enumerate(self.comments):
                author = c.get("user", "unknown")
                content = c.get("text", "")
                timestamp = (
                    c.get("timestamp")
                    or c.get("created_at")
                    or datetime.now().isoformat()
                )
                try:
                    c_time = format_time_ago(datetime.fromisoformat(timestamp))
                except Exception:
                    c_time = "just now"
                comment_widget = Static(
                    f"  @{author} • {c_time}\n  {content}\n",
                    classes="comment-thread-item comment-item",
                    id=f"comment-{i}",
                    markup=False,
                )
                comment_widget.styles.background = "#282A36"  # Force dark background
                self.mount(comment_widget)

            # Reset cursor position
            self.cursor_position = 0
        except Exception:
            pass

    def key_i(self) -> None:
        """Focus comment input with i key"""
        if self.app.command_mode:
            return
        # Set cursor to position 1 (input) and focus it
        self.cursor_position = 1
        try:
            comment_input = self.query_one("#comment-input", Input)
            comment_input.focus()
        except Exception:
            pass

    def key_q(self) -> None:
        """Exit comment screen with q key"""
        if self.app.command_mode:
            return
        try:
            self.app.pop_screen()
        except Exception:
            pass

    def _get_navigable_items(self) -> list:
        """Get all navigable items (post + input + comments)"""
        try:
            post_item = self.query_one(PostItem)
            comment_input = self.query_one("#comment-input", Input)
            comment_items = list(self.query(".comment-item"))
            return [post_item, comment_input] + comment_items
        except Exception:
            return []

    def _update_cursor(self) -> None:
        """Update the cursor position - includes post + input + comments"""
        try:
            items = self._get_navigable_items()
            post_item = self.query_one(PostItem)
            comment_items = list(self.query(".comment-item"))
            comment_input = self.query_one("#comment-input", Input)

            # Remove cursor from all items
            post_item.remove_class("vim-cursor")
            comment_input.remove_class("vim-cursor")
            for item in comment_items:
                item.remove_class("vim-cursor")
                item.styles.background = (
                    "#282A36"  # Reset to dark background, not empty
                )

            if 0 <= self.cursor_position < len(items):
                item = items[self.cursor_position]
                if isinstance(item, PostItem):
                    # Add cursor to post
                    item.add_class("vim-cursor")
                    self.focus()
                elif isinstance(item, Input):
                    # Don't focus the input, just add visual indicator
                    item.add_class("vim-cursor")
                    # Make sure screen has focus so vim keys work
                    self.focus()
                else:
                    # Add cursor class to comment (no background change, just text style)
                    item.add_class("vim-cursor")
                self.scroll_to_widget(item, top=True)
        except Exception:
            pass

    def on_focus(self) -> None:
        """When the screen gets focus"""
        self.cursor_position = 0
        self._update_cursor()

    def on_blur(self) -> None:
        """When screen loses focus"""
        pass

    def on_scroll(self, event) -> None:
        """Update scroll position reactive when scrolling"""
        self.scroll_y = self.scroll_offset.y

    def key_j(self) -> None:
        """Move down with j key"""
        if self.app.command_mode:
            return
        items = self._get_navigable_items()
        if self.cursor_position < len(items) - 1:
            self.cursor_position += 1

    def key_k(self) -> None:
        """Move up with k key"""
        if self.app.command_mode:
            return
        if self.cursor_position > 0:
            self.cursor_position -= 1

    def key_g(self) -> None:
        """Go to top with gg"""
        if self.app.command_mode:
            return
        pass  # Handled in on_key for double-press

    def key_G(self) -> None:
        """Go to bottom with G"""
        if self.app.command_mode:
            return
        items = self._get_navigable_items()
        self.cursor_position = len(items) - 1

    def key_ctrl_d(self) -> None:
        """Half page down"""
        if self.app.command_mode:
            return
        items = self._get_navigable_items()
        self.cursor_position = min(self.cursor_position + 5, len(items) - 1)

    def key_ctrl_u(self) -> None:
        """Half page up"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 5, 0)

    def key_w(self) -> None:
        """Word forward - move down by 3"""
        if self.app.command_mode:
            return
        items = self._get_navigable_items()
        self.cursor_position = min(self.cursor_position + 3, len(items) - 1)

    def key_b(self) -> None:
        """Word backward - move up by 3"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 3, 0)

    def key_d(self) -> None:
        """Prevent 'd' from triggering drafts when in comment screen"""
        if self.app.command_mode:
            return
        # Just prevent propagation - 'd' has no function in comment screen
        pass

    def on_key(self, event) -> None:
        """Handle g+g key combination for top and escape from input"""
        # Don't process keys if app is in command mode
        if self.app.command_mode:
            return

        if event.key == "escape":
            # If comment input has focus, unfocus it and return focus to screen
            try:
                comment_input = self.query_one("#comment-input", Input)
                if comment_input.has_focus:
                    comment_input.blur()
                    self.focus()
                    self.cursor_position = 0
                    event.prevent_default()
                    event.stop()
                    return
            except Exception:
                pass

        if event.key == "g":
            now = time.time()
            if hasattr(self, "last_g_time") and now - self.last_g_time < 0.5:
                self.cursor_position = 0
                event.prevent_default()
                delattr(self, "last_g_time")
            else:
                self.last_g_time = now

        # Prevent 'd' from propagating to app level (show drafts)
        if event.key == "d":
            event.prevent_default()
            event.stop()


class CommentScreen(Screen):
    """Screen wrapper for CommentFeed"""

    def __init__(self, post, **kwargs):
        super().__init__(**kwargs)
        self.post = post

    def compose(self) -> ComposeResult:
        yield CommentFeed(self.post, id="comment-feed")
        yield Static(
            "[i] Input [q] Back [j/k] Navigate", id="comment-footer", markup=False
        )


# ───────── Items ─────────


class NavigationItem(Static):
    def __init__(
        self, label: str, screen_name: str, number: int, active: bool = False, **kwargs
    ):
        # Ensure markup is enabled
        kwargs.setdefault("markup", True)
        super().__init__(**kwargs)
        self.label_text = label
        self.screen_name = screen_name
        self.number = number
        self.active = active
        if active:
            self.add_class("active")

    def render(self) -> str:
        if self.active:
            return f"[bold white]{self.number}: {self.label_text}[/]"
        else:
            return f"[#888888]{self.number}: {self.label_text}[/]"

    def on_click(self) -> None:
        self.app.switch_screen(self.screen_name)

    def set_active(self, is_active: bool) -> None:
        self.active = is_active
        (self.add_class if is_active else self.remove_class)("active")
        self.refresh()


class CommandItem(Static):
    def __init__(self, shortcut: str, description: str, **kwargs):
        super().__init__(**kwargs)
        self.shortcut = shortcut
        self.description = description

    def render(self) -> str:
        return f"{self.shortcut} - {self.description}"


class DraftItem(Static):
    """Display a saved draft in sidebar."""

    def __init__(self, draft: Dict, index: int, **kwargs):
        super().__init__(**kwargs)
        self.draft = draft
        self.draft_index = index
        self.border = "round"
        self.border_title = f"Draft {index + 1}"

    def render(self) -> str:
        """Render the draft item as text."""
        content = (
            self.draft["content"][:40] + "..."
            if len(self.draft["content"]) > 40
            else self.draft["content"]
        )
        time_ago = format_time_ago(self.draft["timestamp"])
        attachments_count = len(self.draft.get("attachments", []))
        attach_text = f" 📎{attachments_count}" if attachments_count > 0 else ""

        return f"{time_ago}\n{content}{attach_text}"

    def on_click(self) -> None:
        """Handle click on draft item - for now just open it."""
        self.app.action_open_draft(self.draft_index)


class ProfileDisplay(Static):
    """Display user profile."""

    def compose(self) -> ComposeResult:
        user = api.get_current_user()
        username = get_username()
        if username == None:
            username = user.username
        yield Static(f"@{username}", classes="profile-username")


class ConversationItem(Static):
    def __init__(self, conversation, **kwargs):
        super().__init__(**kwargs)
        self.conversation = conversation

    def render(self) -> str:
        time_ago = format_time_ago(self.conversation.last_message_at)
        unread_text = "🔵 unread" if self.conversation.unread else ""
        # Get the other participant's username (first one that's not the current user)
        current_user = get_username() or "yourname"
        other_participants = [
            h for h in self.conversation.participant_handles if h != current_user
        ]
        username = (
            other_participants[0]
            if other_participants
            else self.conversation.participant_handles[0]
            if self.conversation.participant_handles
            else "unknown"
        )
        return (
            f"@{username}\n  {self.conversation.last_message_preview}\n  {unread_text}"
        )

    def on_click(self) -> None:
        """Handle click to open the conversation"""
        try:
            # Get the other participant's username
            current_user = get_username() or "yourname"
            other_participants = [h for h in self.conversation.participant_handles if h != current_user]
            username = other_participants[0] if other_participants else self.conversation.participant_handles[0] if self.conversation.participant_handles else "unknown"

            # Find the ConversationsList parent
            conv_list = self.parent
            if isinstance(conv_list, ConversationsList):
                # Find which index this conversation is
                items = list(conv_list.query(".conversation-item"))
                try:
                    index = items.index(self)
                    conv_list.selected_position = index
                    conv_list.cursor_position = index
                except ValueError:
                    pass

            # Get MessagesScreen parent container
            messages_screen = self.parent
            while messages_screen is not None:
                if isinstance(messages_screen, MessagesScreen):
                    break
                messages_screen = messages_screen.parent

            if isinstance(messages_screen, MessagesScreen):
                messages_screen._open_chat_view(self.conversation.id, username)

                # Focus the chat view
                try:
                    chat_views = list(messages_screen.query("ChatView"))
                    if chat_views:
                        chat_views[0].focus()
                        # Also focus the input field
                        try:
                            msg_input = chat_views[0].query_one("#message-input", Input)
                            msg_input.focus()
                        except:
                            pass
                except:
                    pass
        except Exception:
            pass


class ChatMessage(Static):
    def __init__(self, message, current_user: str = "", **kwargs):
        super().__init__(**kwargs)
        self.message = message
        is_sent = (message.sender or "").lower() == (current_user or "").lower()
        # Add sent/received class plus a 'me' class for messages from the current userq
        # Add sent/received class; avoid adding a separate 'me' class
        # as 'sent' is sufficient and avoids duplicate styling rules.
        self.add_class("sent" if is_sent else "received")
        # Layout and alignment are handled via TCSS classes in `main.tcss`.
        # Keep widget class markers but avoid programmatic style mutation
        # so styling is centralized in the stylesheet.

    def render(self) -> str:
        return f"{self.message.content}\n{format_time_ago(self.message.created_at)}"


class PostItem(Static):
    """Simple non-interactive post display."""

    liked_by_user = reactive(False)
    reposted_by_user = reactive(False)
    like_count = reactive(0)
    repost_count = reactive(0)
    comment_count = reactive(0)

    def __init__(self, post, reposted_by_you=False, **kwargs):
        super().__init__(**kwargs)
        self.post = post
        self.reposted_by_you = reposted_by_you
        self.has_video = hasattr(post, "video_path") and post.video_path

        # Initialize reactive counters from the post model
        try:
            self.liked_by_user = bool(getattr(post, "liked_by_user", False))
            self.like_count = int(getattr(post, "likes", 0) or 0)
            self.repost_count = int(getattr(post, "reposts", 0) or 0)
            self.comment_count = int(getattr(post, "comments", 0) or 0)
        except Exception:
            # Fallbacks if model attributes are missing or malformed
            self.liked_by_user = False
            self.like_count = 0
            self.repost_count = 0
            self.comment_count = 0

        # Check for ASCII art attachments in both the post.attachments property and dict
        attachments = getattr(post, "attachments", None)
        if isinstance(attachments, list):
            self.has_ascii_art = any(
                att.get("type") == "ascii_photo" for att in attachments
            )
        else:
            self.has_ascii_art = False

    def compose(self) -> ComposeResult:
        """Compose compact post."""
        time_ago = format_time_ago(self.post.timestamp)
        like_symbol = "❤️" if self.liked_by_user else "🤍"
        repost_symbol = "🔁" if self.reposted_by_user else "🔁"

        # Repost banner if this is a reposted post by you (either client-injected or backend-marked)
        if getattr(self, "reposted_by_you", False) or getattr(
            self.post, "reposted_by_user", False
        ):
            yield Static("🔁 Reposted by you", classes="repost-banner", markup=False)

        # Post header and reactive stats
        yield Static(
            f"@{self.post.author} • {time_ago}\n{self.post.content}",
            classes="post-text",
            markup=False,
        )

        # Display ASCII art attachments
        if self.has_ascii_art:
            attachments = getattr(self.post, "attachments", [])
            for attachment in attachments:
                if attachment.get("type") == "ascii_photo":
                    art_content = attachment.get("content", "")
                    if art_content:  # Only yield if we have content
                        # Add spacing before ASCII art
                        yield Static("\n", markup=False)
                        yield Static(
                            art_content,
                            classes="ascii-art",
                            markup=False,
                        )
                        # Add spacing after ASCII art
                        yield Static("\n", markup=False)

        # Video player if post has video
        if self.has_video and Path(self.post.video_path).exists():
            yield ASCIIVideoPlayer(
                frames_dir=self.post.video_path,
                fps=getattr(self.post, "video_fps", 2),
                classes="post-video",
            )

        # Post stats - use reactive fields so updates are instant
        yield Static(
            f"{like_symbol} {self.like_count}  {repost_symbol} {self.repost_count}  💬 {self.comment_count}",
            classes="post-stats",
            markup=False,
        )

    def watch_has_class(self, has_class: bool) -> None:
        """Watch for class changes to handle cursor"""
        if has_class and "vim-cursor" in self.classes:
            # We have cursor focus
            self.border = "ascii"
            self.styles.background = "darkblue"
        else:
            # We don't have cursor focus
            self.border = ""
            self.styles.background = ""

    def _update_stats_widget(self) -> None:
        """Update the post-stats Static text if mounted."""
        try:
            stats_widget = self.query_one(".post-stats", Static)
            like_symbol = "❤️" if self.liked_by_user else "🤍"
            repost_symbol = "🔁" if self.reposted_by_user else "🔁"
            stats_widget.update(
                f"{like_symbol} {self.like_count}  {repost_symbol} {self.repost_count}  💬 {self.comment_count}"
            )
        except Exception:
            # If not found, force a refresh as fallback
            try:
                self.refresh()
            except Exception:
                pass

    def watch_liked_by_user(self, liked: bool) -> None:
        """Update like count when liked_by_user changes"""
        if liked:
            self.like_count += 1
        else:
            self.like_count = max(0, self.like_count - 1)
        # Keep underlying model consistent
        try:
            self.post.liked_by_user = liked
            self.post.likes = self.like_count
        except Exception:
            pass
        self._update_stats_widget()

    def watch_reposted_by_user(self, reposted: bool) -> None:
        """Update repost count when reposted_by_user changes"""
        if reposted:
            self.repost_count += 1
        else:
            self.repost_count = max(0, self.repost_count - 1)
        try:
            self.post.reposted_by_user = reposted
            self.post.reposts = self.repost_count
        except Exception:
            pass
        self._update_stats_widget()

    def on_click(self) -> None:
        """Handle click to open comment screen"""
        try:
            self.app.push_screen(CommentScreen(self.post))
        except Exception:
            pass


class NotificationItem(Static):
    def __init__(self, notification, **kwargs):
        super().__init__(**kwargs)
        self.notification = notification
        if not notification.read:
            self.add_class("unread")

    def render(self) -> str:
        t = format_time_ago(self.notification.timestamp)
        icon = {
            "mention": "📢",
            "like": "❤️",
            "repost": "🔁",
            "follow": "👥",
            "comment": "💬",
        }.get(self.notification.type, "🔵")
        n = self.notification
        if n.type == "mention":
            return f"@{n.actor} mentioned you • {t}\n{n.content}"
        if n.type == "like":
            return f"{icon} @{n.actor} liked your post • {t}\n{n.content}"
        if n.type == "repost":
            return f"{icon} @{n.actor} reposted • {t}\n{n.content}"
        if n.type == "follow":
            return f"{icon} @{n.actor} started following you • {t}"
        return f"{icon} @{n.actor} • {t}\n{n.content}"


class UserProfileCard(Static):
    """A user profile card for search results."""

    def __init__(
        self,
        username: str,
        display_name: str,
        bio: str,
        followers: int,
        following: int,
        ascii_pic: str,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.username = username
        self.display_name = display_name
        self.bio = bio
        self.followers = followers
        self.following = following
        self.ascii_pic = ascii_pic

    def compose(self) -> ComposeResult:
        card_container = Container(classes="user-card-container")

        with card_container:
            pic_container = Container(classes="user-card-pic")
            with pic_container:
                yield Static(self.ascii_pic, classes="user-card-avatar")
            yield pic_container

            info_container = Container(classes="user-card-info")
            with info_container:
                yield Static(self.display_name, classes="user-card-name")
                # Resolve current local username once (fall back to the profile's username)
                current_user = get_username() or self.username
                # Make username clickable as a button-like widget
                yield Button(
                    f"@{current_user}",
                    id=f"username-{current_user}",
                    classes="user-card-username-btn",
                )

                yield Static(self.bio, classes="user-card-bio")

                stats_container = Container(classes="user-card-stats")
                with stats_container:
                    yield Static(
                        f"{self.followers} Followers", classes="user-card-stat"
                    )
                    yield Static(
                        f"{self.following} Following", classes="user-card-stat"
                    )
                yield stats_container

                buttons_container = Container(classes="user-card-buttons")
                with buttons_container:
                    # Reuse the resolved current_user to avoid repeated keyring calls
                    buttons_user = current_user
                    yield Button(
                        "Follow",
                        id=f"follow-{buttons_user}",
                        classes="user-card-button",
                    )
                    yield Button(
                        "Message",
                        id=f"message-{buttons_user}",
                        classes="user-card-button",
                    )
                    yield Button(
                        "View Profile",
                        id=f"view-{buttons_user}",
                        classes="user-card-button",
                    )
                yield buttons_container
            yield info_container

        yield card_container

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        btn_id = event.button.id

        if btn_id == f"view-{self.username}" or btn_id == f"username-{self.username}":
            self.app.action_view_user_profile(self.username)
        elif btn_id == f"follow-{self.username}":
            try:
                self.app.notify(f"✓ Following @{self.username}!", severity="success")
            except:
                pass
        elif btn_id == f"message-{self.username}":
            # Open messages screen with this user
            self.app.action_open_dm(self.username)


# ───────── Top Navbar ─────────


from textual.widgets import Tabs, Tab


class TopNav(Horizontal):
    """Top navigation implemented using Textual's Tabs widget.

    This wrapper preserves the `update_active(screen_name)` API so the rest
    of the app (notably `switch_screen`) doesn't need to change.
    """

    current = reactive("timeline")

    def __init__(self, current: str = "timeline", **kwargs):
        super().__init__(**kwargs)
        self.current = current
        # Expose the inner Tabs widget for easier external access
        self.tabs = None

    def compose(self) -> ComposeResult:
        # Use explicit Tab ids so programmatic activation is stable
        yield Tabs(
            Tab("[1] Timeline", id="tab-timeline"),
            Tab("[2] Discover", id="tab-discover"),
            Tab("[3] Notifs", id="tab-notifications"),
            Tab("[4] Messages", id="tab-messages"),
            Tab("[5] Settings", id="tab-settings"),
            id="top-tabs",
            active=self._screen_to_tab_id(self.current),
        )

    def _tab_to_screen_name(self, tab_id: str) -> str:
        return {
            "tab-timeline": "timeline",
            "tab-discover": "discover",
            "tab-notifications": "notifications",
            "tab-messages": "messages",
            "tab-settings": "settings",
        }.get(tab_id, "timeline")

    def _screen_to_tab_id(self, screen_name: str) -> str:
        return {
            "timeline": "tab-timeline",
            "discover": "tab-discover",
            "notifications": "tab-notifications",
            "messages": "tab-messages",
            "settings": "tab-settings",
        }.get(screen_name, "tab-timeline")

    def on_mount(self) -> None:
        # Ensure the active tab reflects current
        try:
            tabs = self.query_one("#top-tabs", Tabs)
            tabs.active = self._screen_to_tab_id(self.current)
            # Save reference for external callers
            self.tabs = tabs

        except Exception:
            pass

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """Handle TabActivated message from inner Tabs and switch screens."""
        try:
            # event.tab can be a Tab or None depending on Textual version
            tab = getattr(event, "tab", None)
            if tab is None:
                return
            tab_id = getattr(tab, "id", None)
            if not tab_id:
                return
            screen_name = self._tab_to_screen_name(tab_id)
            # Ask the App to switch screens
            self.app.switch_screen(screen_name)
        except Exception:
            pass

    def update_active(self, screen_name: str):
        """Compatibility method used by the App to set the active screen."""
        self.current = screen_name
        try:
            if getattr(self, "tabs", None) is not None:
                self.tabs.active = self._screen_to_tab_id(screen_name)
            else:
                tabs = self.query_one("#top-tabs", Tabs)
                tabs.active = self._screen_to_tab_id(screen_name)

        except Exception:
            pass


# ───────── Sidebar ─────────


class Sidebar(VerticalScroll):
    current_screen = reactive("timeline")

    def __init__(self, current: str = "timeline", show_nav: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.current_screen = current
        self.show_nav = show_nav

    def compose(self) -> ComposeResult:
        # Navigation box (optional, default hidden since we have top navbar)
        if self.show_nav:
            nav_container = Container(classes="navigation-box")
            nav_container.border_title = "Navigation [N]"
            with nav_container:
                yield NavigationItem(
                    "Timeline",
                    "timeline",
                    1,
                    self.current_screen == "timeline",
                    classes="nav-item",
                )
                yield NavigationItem(
                    "Discover",
                    "discover",
                    2,
                    self.current_screen == "discover",
                    classes="nav-item",
                )
                yield NavigationItem(
                    "Notifs",
                    "notifications",
                    3,
                    self.current_screen == "notifications",
                    classes="nav-item",
                )
                yield NavigationItem(
                    "Messages",
                    "messages",
                    4,
                    self.current_screen == "messages",
                    classes="nav-item",
                )
                yield NavigationItem(
                    "Settings",
                    "settings",
                    5,
                    self.current_screen == "settings",
                    classes="nav-item",
                )
            yield nav_container

        profile_container = Container(classes="profile-box")
        profile_container.border_title = "\\[p] Profile"
        with profile_container:
            yield ProfileDisplay()
        yield profile_container

        # Drafts section
        drafts_container = Container(classes="drafts-box")
        drafts_container.border_title = "\\[d] Drafts"
        with drafts_container:
            drafts = load_drafts()
            if drafts:
                # Show most recent first
                for i, draft in enumerate(reversed(drafts)):
                    yield DraftItem(draft, len(drafts) - 1 - i, classes="draft-item")
            else:
                yield Static(
                    "No drafts\n\nPress :n to create", classes="no-drafts-text"
                )
        yield drafts_container

        commands_container = Container(classes="commands-box")
        commands_container.border_title = "Commands"
        with commands_container:
            # Show only screen-specific commands to save space
            if self.current_screen == "messages":
                yield CommandItem(":m", "dm user", classes="command-item")
                yield CommandItem(":n", "new msg", classes="command-item")
                yield CommandItem(":r", "reply to msg", classes="command-item")
            elif self.current_screen in ("timeline", "discover"):
                yield CommandItem(":n", "new post", classes="command-item")
                yield CommandItem(":l", "like", classes="command-item")
                yield CommandItem(":rt", "repost", classes="command-item")
                yield CommandItem("<Enter>", "comments", classes="command-item")
            elif self.current_screen == "notifications":
                yield CommandItem(":m", "mark read", classes="command-item")
                yield CommandItem(":ma", "mark all", classes="command-item")
            elif self.current_screen == "profile":
                yield CommandItem(":e", "edit", classes="command-item")
                yield CommandItem(":f", "follow", classes="command-item")
            elif self.current_screen == "settings":
                yield CommandItem(":w", "save", classes="command-item")
                yield CommandItem(":e", "edit", classes="command-item")

            # Common commands (limited to save space)
            yield CommandItem("p", "profile", classes="command-item")
            yield CommandItem("d", "drafts", classes="command-item")
        yield commands_container

    def update_active(self, screen_name: str):
        self.current_screen = screen_name
        for nav_item in self.query(".nav-item"):
            try:
                nav_item.set_active(nav_item.screen_name == screen_name)
            except Exception:
                pass

    def refresh_drafts(self):
        """Refresh the drafts display."""
        try:
            # Find drafts container by class
            drafts_container = self.query_one(".drafts-box", Container)
            # Remove all draft items
            for item in drafts_container.query(".draft-item, .no-drafts-text"):
                item.remove()

            # Add updated drafts
            drafts = load_drafts()
            if drafts:
                # Show most recent first
                for i, draft in enumerate(reversed(drafts)):
                    drafts_container.mount(
                        DraftItem(draft, len(drafts) - 1 - i, classes="draft-item")
                    )
            else:
                drafts_container.mount(
                    Static("No drafts\n\nPress :n to create", classes="no-drafts-text")
                )
        except Exception as e:
            print(f"Error refreshing drafts: {e}")

    def on_drafts_updated(self, message: DraftsUpdated) -> None:
        """Handle drafts updated message."""
        self.refresh_drafts()


# ───────── Modal Dialogs ─────────


class NewPostDialog(ModalScreen):
    """Modal dialog for creating a new post."""

    cursor_position = reactive(0)  # 0 = textarea, 1-5 = buttons

    def __init__(self, draft_content: str = "", draft_attachments: List = None):
        super().__init__()
        self.draft_content = draft_content
        self.draft_attachments = draft_attachments or []
        self.in_insert_mode = True  # Start in insert mode (textarea focused)

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
            yield Static("✨ Create New Post", id="dialog-title")
            yield TextArea(id="post-textarea")
            # Key hints for vim navigation
            yield Static(
                "\\[i] edit | \\[esc] navigate", id="vim-hints", classes="vim-hints"
            )
            # Status/attachments display area
            yield Static("", id="attachments-list", classes="attachments-list")
            yield Static("", id="status-message", classes="status-message")

            # Media attachment buttons
            with Container(id="media-buttons"):
                yield Button("🖼️ Add Photo", id="attach-photo")

            # Action buttons
            with Container(id="action-buttons"):
                yield Button("📤 Post", variant="primary", id="post-button")
                yield Button("💾 Save", id="draft-button")
                yield Button("❌ Cancel", id="cancel-button")

    def on_mount(self) -> None:
        """Focus the textarea when dialog opens."""
        textarea = self.query_one("#post-textarea", TextArea)

        # Load draft content if provided
        if self.draft_content:
            textarea.text = self.draft_content

        # Initialize attachments list
        self._attachments = (
            self.draft_attachments.copy() if self.draft_attachments else []
        )

        # Update attachments display
        self._update_attachments_display()

        textarea.focus()
        self.in_insert_mode = True
        self.cursor_position = 0

    def _get_navigable_buttons(self) -> list:
        """Get list of all navigable buttons in order."""
        buttons = []
        try:
            # Media button
            buttons.append(self.query_one("#attach-photo", Button))
            # Action buttons
            buttons.append(self.query_one("#post-button", Button))
            buttons.append(self.query_one("#draft-button", Button))
            buttons.append(self.query_one("#cancel-button", Button))
        except:
            pass
        return buttons

    def _update_cursor(self) -> None:
        """Update visual cursor position."""
        buttons = self._get_navigable_buttons()

        # Remove vim-cursor from all buttons
        for btn in buttons:
            btn.remove_class("vim-cursor")

        textarea = self.query_one("#post-textarea", TextArea)

        if self.in_insert_mode:
            # In insert mode, textarea has focus
            textarea.focus()
        else:
            # In navigation mode, highlight current button
            if 1 <= self.cursor_position <= len(buttons):
                buttons[self.cursor_position - 1].add_class("vim-cursor")

    def watch_cursor_position(self, old: int, new: int) -> None:
        """React to cursor position changes."""
        self._update_cursor()

    def key_escape(self) -> None:
        """Exit insert mode and enter navigation mode."""
        if self.app.command_mode:
            return
        if self.in_insert_mode:
            self.in_insert_mode = False
            self.cursor_position = 1  # Start at first button
            self._update_cursor()

    def key_i(self) -> None:
        """Enter insert mode (focus textarea)."""
        if self.app.command_mode:
            return
        if not self.in_insert_mode:
            self.in_insert_mode = True
            self.cursor_position = 0
            self._update_cursor()

    def key_j(self) -> None:
        """Move cursor down (to next row)."""
        if self.app.command_mode:
            return
        if not self.in_insert_mode:
            buttons = self._get_navigable_buttons()
            if not buttons:
                return

            # Current position: 1 (photo button) -> 2-4 (action buttons)
            if self.cursor_position == 1:  # Photo button row
                self.cursor_position = 2  # Move to Post button
            # Action buttons stay in their row

    def key_k(self) -> None:
        """Move cursor up (to previous row)."""
        if self.app.command_mode:
            return
        if not self.in_insert_mode:
            # Current position: 2-4 (action buttons) -> 1 (photo button)
            if self.cursor_position >= 2:  # Action buttons row
                self.cursor_position = 1  # Move to photo button
            # Photo button stays in its row

    def key_h(self) -> None:
        """Move cursor left (within same row)."""
        if self.app.command_mode:
            return
        if not self.in_insert_mode:
            if self.cursor_position >= 2:  # Action buttons row
                self.cursor_position = max(self.cursor_position - 1, 2)
            # Photo button is alone in its row, no left movement needed

    def key_l(self) -> None:
        """Move cursor right (within same row)."""
        if self.app.command_mode:
            return
        if not self.in_insert_mode:
            buttons = self._get_navigable_buttons()
            if not buttons:
                return

            if self.cursor_position >= 2:  # Action buttons row
                self.cursor_position = min(self.cursor_position + 1, 4)
            # Photo button is alone in its row, no right movement needed

    def on_key(self, event) -> None:
        """Handle key events to prevent double-triggering."""
        if self.app.command_mode:
            return
        # In navigation mode, prevent Enter from bubbling to buttons
        if not self.in_insert_mode and event.key == "enter":
            event.prevent_default()
            event.stop()
            # Handle the button activation
            if self.cursor_position >= 1:
                buttons = self._get_navigable_buttons()
                if 1 <= self.cursor_position <= len(buttons):
                    button = buttons[self.cursor_position - 1]
                    self.on_button_pressed(Button.Pressed(button))

    def key_enter(self) -> None:
        """Activate the current button."""
        # This is now handled in on_key to prevent double-triggering
        pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = getattr(event.button, "id", None)

        if btn_id == "attach-photo":
            self._show_status("🖼️ Opening photo selector...")
            try:
                root = tk.Tk()
                root.withdraw()
                file_path = filedialog.askopenfilename(
                    title="Select an image",
                    filetypes=[("Image files", "*.png *.jpg *.jpeg *.gif *.bmp")],
                )
                root.destroy()
                if not file_path:
                    return

                try:
                    # Convert image to ASCII art
                    img = Image.open(file_path).convert("L")  # Convert to grayscale

                    # Calculate new dimensions
                    width = 60  # Desired width in characters
                    aspect_ratio = img.height / img.width
                    height = int(
                        width * aspect_ratio * 0.5
                    )  # Multiply by 0.5 since characters are taller than wide
                    img = img.resize((width, height))

                    # Convert pixels to ASCII
                    pixels = img.load()
                    # Use reversed density ramp so dark areas map to sparse chars
                    ascii_chars = [
                        ".",
                        ",",
                        ":",
                        ";",
                        "+",
                        "*",
                        "?",
                        "%",
                        "S",
                        "#",
                        "@",
                    ]
                    ascii_lines = []
                    for y in range(height):
                        line = ""
                        for x in range(width):
                            pixel_value = pixels[x, y]
                            char_index = (pixel_value * (len(ascii_chars) - 1)) // 255
                            line += ascii_chars[char_index]
                        ascii_lines.append(line)
                    ascii_art = "\n".join(ascii_lines)

                    # Store ASCII version instead of original photo
                    self._attachments.append(("ascii_photo", ascii_art))
                    self._update_attachments_display()
                    self._show_status("✓ Photo converted to ASCII!")
                except Exception as e:
                    self._show_status(f"⚠ Error converting image: {str(e)}", error=True)
            except Exception as e:
                self._show_status(f"⚠ Error: {str(e)}", error=True)

        elif btn_id == "post-button":
            self._handle_post()

        elif btn_id == "draft-button":
            self._handle_save_draft()

        elif btn_id == "cancel-button":
            self.dismiss(False)

    def _handle_post(self) -> None:
        """Handle posting the content."""
        textarea = self.query_one("#post-textarea", TextArea)
        content = textarea.text.strip()

        if not content and not self._attachments:
            self._show_status("⚠ Post cannot be empty!", error=True)
            return

        self._show_status("📤 Publishing post...")

        # Prepare attachments payload - ensure attachments is a list that gets set on the post
        attachments = []
        for t, p in self._attachments:
            if t == "ascii_photo":
                attachments.append({"type": "ascii_photo", "content": p})
            else:
                attachments.append({"type": t, "path": p})

        # Call API to create post with attachments properly set
        try:
            # Create post with attachment data included in content
            post_data = {"content": content, "attachments": attachments}
            new_post = api.create_post(json.dumps(post_data))

            self._show_status("✓ Post published successfully!")
            try:
                self.app.notify("📤 Post published!", severity="success")
            except:
                pass
            self.dismiss(True)
        except TypeError:
            # If first attempt fails, try direct API call with attachments
            try:
                new_post = api.create_post(content)  # Simple post without attachments
                setattr(
                    new_post, "attachments", attachments
                )  # Add attachments after creation
                self._show_status("✓ Post published successfully!")
                try:
                    self.app.notify("📤 Post published!", severity="success")
                except:
                    pass
                self.dismiss(True)
            except Exception as e:
                # Fallback without attachments
                try:
                    new_post = api.create_post(content)
                    self._show_status("✓ Post published (without attachments)")
                    try:
                        self.app.notify("📤 Post published!", severity="warning")
                    except:
                        pass
                    self.dismiss(True)
                except Exception as e:
                    self._show_status(f"⚠ Error: {str(e)}", error=True)

    def _handle_save_draft(self) -> None:
        """Handle saving the post as a draft."""
        textarea = self.query_one("#post-textarea", TextArea)
        content = textarea.text.strip()

        if not content and not self._attachments:
            self._show_status("⚠ Draft cannot be empty!", error=True)
            return

        self._show_status("💾 Saving draft...")

        # Save draft using the add_draft function
        try:
            add_draft(content, self._attachments)
            self._show_status("✓ Draft saved!")
            try:
                self.app.notify("💾 Draft saved successfully!", severity="success")
                # Post a custom message to refresh drafts everywhere
                self.app.post_message(DraftsUpdated())
            except:
                pass
            self.dismiss(False)
        except Exception as e:
            self._show_status(f"⚠ Error: {str(e)}", error=True)

    def _update_attachments_display(self) -> None:
        """Update the attachments display area."""
        try:
            widget = self.query_one("#attachments-list", Static)
            if not self._attachments:
                widget.update("")
                return
            lines = ["📎 Attachments:"]
            for i, (t, p) in enumerate(self._attachments, start=1):
                short = Path(p).name
                icon = {"file": "📁", "photo": "🖼️"}.get(t, "📎")
                if t == "ascii_photo":
                    lines.append(f"\n{p}")  # p is the ASCII art itself
                widget.update("\n".join(lines))
        except Exception:
            pass

    def _show_status(self, message: str, error: bool = False) -> None:
        """Show a status message."""
        try:
            widget = self.query_one("#status-message", Static)
            if error:
                widget.styles.color = "#ff4444"
            else:
                widget.styles.color = "#4a9eff"
            widget.update(message)
            # Clear status after 3 seconds
            self.set_timer(3, lambda: widget.update(""))
        except Exception:
            pass


class NewMessageDialog(ModalScreen):
    """Modal dialog to prompt for a username to start a DM with.

    The dialog will validate the username by calling `api.get_or_create_dm`.
    On success it will dismiss with the chosen username; on failure it will
    display an inline error and keep the dialog open.
    """

    # 0 = Open, 1 = Cancel
    cursor_position = reactive(0)
    in_input = reactive(True)

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
            yield Static("💬 New Message", id="dialog-title")
            yield Input(
                placeholder="Enter recipient handle (without @)", id="dm-username-input"
            )
            yield Static("", id="dm-status", classes="status-message")
            # Small hint for vim-style input/selection controls
            yield Static(
                "\\[i] edit  |  \\[esc] navigate", id="dm-hint", classes="input-hint"
            )
            with Container(id="action-buttons"):
                open_btn = Button("Open", variant="primary", id="dm-open")
                cancel_btn = Button("Cancel", id="dm-cancel")
                # Apply visual selection based on cursor position
                if self.cursor_position == 0:
                    open_btn.add_class("selected")
                else:
                    cancel_btn.add_class("selected")
                yield open_btn
                yield cancel_btn

    def on_mount(self) -> None:
        try:
            inp = self.query_one("#dm-username-input", Input)
            inp.focus()
        except Exception:
            pass

    def key_i(self) -> None:
        """Enter insert mode: focus the input box."""
        if self.app.command_mode:
            return
        try:
            self.in_input = True
            inp = self.query_one("#dm-username-input", Input)
            inp.focus()
        except Exception:
            pass

    def key_escape(self) -> None:
        """Exit input and focus buttons for h/l navigation."""
        if self.app.command_mode:
            return
        try:
            # If currently in input, move to button navigation
            if getattr(self, "in_input", False):
                self.in_input = False
                # Focus the currently-selected button
                btns = list(self.query("#action-buttons Button"))
                if not btns:
                    return
                sel = max(0, min(self.cursor_position, len(btns) - 1))
                try:
                    btns[sel].focus()
                except Exception:
                    pass
        except Exception:
            pass

    def key_h(self) -> None:
        """Move selection left (Open)."""
        if self.app.command_mode:
            return
        # Only navigate buttons when not in input
        if getattr(self, "in_input", True):
            return
        try:
            self.cursor_position = 0
        except Exception:
            pass

    def key_l(self) -> None:
        """Move selection right (Cancel)."""
        if self.app.command_mode:
            return
        if getattr(self, "in_input", True):
            return
        try:
            self.cursor_position = 1
        except Exception:
            pass

    def watch_cursor_position(self, old_position: int, new_position: int) -> None:
        """Update button selection visuals when cursor changes."""
        try:
            btns = list(self.query("#action-buttons Button"))
            for i, b in enumerate(btns):
                if i == new_position:
                    if "selected" not in b.classes:
                        b.add_class("selected")
                    if "vim-cursor" not in b.classes:
                        b.add_class("vim-cursor")
                else:
                    if "selected" in b.classes:
                        b.remove_class("selected")
                    if "vim-cursor" in b.classes:
                        b.remove_class("vim-cursor")
                # ensure focus follows the selected button when not in input
                if not getattr(self, "in_input", True) and i == new_position:
                    try:
                        b.focus()
                    except Exception:
                        pass
        except Exception:
            pass

    def watch_in_input(self, old: bool, new: bool) -> None:
        """When entering/exiting input mode, update button visuals accordingly."""
        try:
            btns = list(self.query("#action-buttons Button"))
            if new:
                # Entering input: remove selection visuals
                for b in btns:
                    if "selected" in b.classes:
                        b.remove_class("selected")
                    if "vim-cursor" in b.classes:
                        b.remove_class("vim-cursor")
            else:
                # Leaving input: ensure the selected button has visuals and focus
                sel = max(0, min(self.cursor_position, len(btns) - 1))
                for i, b in enumerate(btns):
                    if i == sel:
                        if "selected" not in b.classes:
                            b.add_class("selected")
                        if "vim-cursor" not in b.classes:
                            b.add_class("vim-cursor")
                        try:
                            b.focus()
                        except Exception:
                            pass
                    else:
                        if "selected" in b.classes:
                            b.remove_class("selected")
                        if "vim-cursor" in b.classes:
                            b.remove_class("vim-cursor")
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "dm-cancel":
            # Dismiss with falsy value
            self.dismiss(False)
            return
        if event.button.id == "dm-open":
            self._try_open()

    def key_enter(self) -> None:
        if self.app.command_mode:
            return
        # If currently in input, attempt to open; otherwise activate selected button
        if getattr(self, "in_input", True):
            self._try_open()
            return

        # Button navigation: 0 = Open, 1 = Cancel
        try:
            if self.cursor_position == 0:
                self._try_open()
            else:
                self.dismiss(False)
        except Exception:
            pass

    def _try_open(self) -> None:
        try:
            inp = self.query_one("#dm-username-input", Input)
            status = self.query_one("#dm-status", Static)
            handle = (inp.value or "").strip().lstrip("@")
            if not handle:
                status.update("Please enter a username")
                return

            # Attempt to get or create a DM - backend will 404 if user not found
            try:
                conv = api.get_or_create_dm(handle)
            except Exception:
                # Show friendly error (don't dismiss)
                try:
                    status.update(f"User '@{handle}' not found")
                except Exception:
                    pass
                return

            # Success - dismiss and return the username to caller
            self.dismiss(handle)
        except Exception:
            try:
                self.dismiss(False)
            except Exception:
                pass


class DeleteDraftDialog(ModalScreen):
    """Modal dialog for confirming draft deletion."""

    cursor_position = reactive(0)  # 0 = Yes, 1 = Cancel

    def __init__(self, draft_index: int):
        super().__init__()
        self.draft_index = draft_index

    def on_mount(self) -> None:
        """Initialize selection"""
        self.cursor_position = 0  # Default to Yes

    def compose(self) -> ComposeResult:
        with Container(id="dialog-container"):
            yield Static("🗑️ Delete Draft?", id="dialog-title")
            yield Static(
                "Are you sure you want to delete this draft?", classes="dialog-message"
            )

            with Container(id="action-buttons"):
                confirm_btn = Button("✓ Yes, Delete", id="confirm-delete")
                cancel_btn = Button("❌ Cancel", id="cancel-delete")
                if self.cursor_position == 0:
                    confirm_btn.add_class("selected")
                else:
                    cancel_btn.add_class("selected")
                yield confirm_btn
                yield cancel_btn

    def key_h(self) -> None:
        """Select Yes (left)"""
        self.cursor_position = 0

    def key_l(self) -> None:
        """Select Cancel (right)"""
        self.cursor_position = 1

    def key_enter(self) -> None:
        """Execute the selected action"""
        if self.cursor_position == 0:
            delete_draft(self.draft_index)
            try:
                self.app.notify("🗑️ Draft deleted!", severity="success")
                # Post message to refresh drafts everywhere
                self.app.post_message(DraftsUpdated())
            except:
                pass
            self.dismiss(True)
        else:
            self.dismiss(False)

    def watch_cursor_position(self, old_position: int, new_position: int) -> None:
        """Update button styles based on cursor position"""
        try:
            confirm_btn = self.query_one("#confirm-delete", Button)
            cancel_btn = self.query_one("#cancel-delete", Button)

            if new_position == 0:
                confirm_btn.add_class("selected")
                cancel_btn.remove_class("selected")
            else:
                cancel_btn.add_class("selected")
                confirm_btn.remove_class("selected")
        except:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = getattr(event.button, "id", None)

        if btn_id == "confirm-delete":
            delete_draft(self.draft_index)
            try:
                self.app.notify("🗑️ Draft deleted!", severity="success")
                # Post message to refresh drafts everywhere
                self.app.post_message(DraftsUpdated())
            except:
                pass
            self.dismiss(True)
        elif btn_id == "cancel-delete":
            self.dismiss(False)


# ───────── Screens ─────────


class TimelineFeed(VerticalScroll):
    cursor_position = reactive(0)
    reposted_posts = reactive([])  # List of (post, timestamp) tuples
    scroll_y = reactive(0)  # Track scroll position
    _all_posts = []  # Cache all posts locally
    _displayed_count = 20  # Number of posts currently displayed
    _batch_size = 20  # Number of posts to load at a time
    _loading_more = False  # Flag to prevent multiple simultaneous loads

    def key_enter(self) -> None:
        """Open comment screen for focused post"""
        if self.app.command_mode:
            return
        self.open_comment_screen()

    def open_comment_screen(self):
        """Open the comment screen for the currently focused post"""
        logging.debug("open_comment_screen called in TimelineFeed")
        items = list(self.query(".post-item"))
        logging.debug(
            f"cursor_position={self.cursor_position}, total_items={len(items)}"
        )
        if 0 <= self.cursor_position < len(items):
            post_item = items[self.cursor_position]
            post = getattr(post_item, "post", None)
            logging.debug(
                f"Opening comment screen for post id={getattr(post, 'id', None)} author={getattr(post, 'author', None)}"
            )
            if post:
                self.app.push_screen(CommentScreen(post))
        else:
            logging.debug("Invalid cursor position in open_comment_screen")

    def compose(self) -> ComposeResult:
        # Fetch all posts once and cache them
        posts = api.get_timeline()
        reposted_sorted = sorted(self.reposted_posts, key=lambda x: x[1], reverse=True)
        self._all_posts = [p for p, _ in reposted_sorted] + posts

        unread_count = len(
            [
                p
                for p in self._all_posts
                if (datetime.now() - p.timestamp).seconds < 3600
            ]
        )
        self.border_title = "Main Timeline"
        yield Static(
            f"timeline.home | {unread_count} new posts | line 1",
            classes="panel-header",
            markup=False,
        )

        # Initially display only the first batch
        repost_count = len(reposted_sorted)
        for i, post in enumerate(self._all_posts[: self._displayed_count]):
            is_repost = i < repost_count
            post_item = PostItem(
                post, reposted_by_you=is_repost, classes="post-item", id=f"post-{i}"
            )
            if i == 0:
                post_item.add_class("vim-cursor")
            yield post_item

    def on_mount(self) -> None:
        self.watch(self, "cursor_position", self._update_cursor)
        self.watch(self, "scroll_y", self._check_scroll_load)

    def _check_scroll_load(self) -> None:
        """Check if we need to load more posts based on scroll position"""
        try:
            # Get the virtual size (total content height) and viewport size
            virtual_size = self.virtual_size.height
            container_size = self.container_size.height

            # If we're within 100 pixels of the bottom, load more
            if (
                virtual_size > 0
                and self.scroll_y + container_size >= virtual_size - 100
            ):
                self._load_more_posts()
        except Exception:
            pass

    def _load_more_posts(self) -> None:
        """Load the next batch of posts from cache"""
        if self._loading_more or self._displayed_count >= len(self._all_posts):
            return

        self._loading_more = True
        try:
            # Calculate how many new posts to add
            old_count = self._displayed_count
            self._displayed_count = min(
                self._displayed_count + self._batch_size, len(self._all_posts)
            )

            # Mount the new posts
            repost_count = len(
                [
                    p
                    for p, _ in sorted(
                        self.reposted_posts, key=lambda x: x[1], reverse=True
                    )
                ]
            )
            for i in range(old_count, self._displayed_count):
                post = self._all_posts[i]
                is_repost = i < repost_count
                post_item = PostItem(
                    post, reposted_by_you=is_repost, classes="post-item", id=f"post-{i}"
                )
                self.mount(post_item)
        finally:
            self._loading_more = False

    def _update_cursor(self) -> None:
        """Update the cursor position and check if we need to load more"""
        try:
            # Find all post items
            items = list(self.query(".post-item"))

            # Remove cursor from all items
            for i, item in enumerate(items):
                item.remove_class("vim-cursor")

            # Add cursor to focused item
            if 0 <= self.cursor_position < len(items):
                item = items[self.cursor_position]
                item.add_class("vim-cursor")
                # Ensure the cursor is visible
                self.scroll_to_widget(item, top=True)

                # Load more posts if we're near the end (within 5 posts)
                if self.cursor_position >= len(items) - 5:
                    self._load_more_posts()
        except Exception:
            pass

    def on_focus(self) -> None:
        """When the feed gets focus"""
        self.cursor_position = 0
        self._update_cursor()

    def on_blur(self) -> None:
        """When feed loses focus"""
        pass

    def on_scroll(self, event) -> None:
        """Update scroll position reactive when scrolling"""
        self.scroll_y = self.scroll_offset.y

    def key_j(self) -> None:
        """Move down with j key"""
        if self.app.command_mode:
            return
        items = list(self.query(".post-item"))
        if self.cursor_position < len(items) - 1:
            self.cursor_position += 1

    def key_k(self) -> None:
        """Move up with k key"""
        if self.app.command_mode:
            return
        if self.cursor_position > 0:
            self.cursor_position -= 1

    def key_g(self) -> None:
        """Go to top with gg"""
        pass  # g is handled in on_key for double-press

    def key_G(self) -> None:
        """Go to bottom with G"""
        if self.app.command_mode:
            return
        items = list(self.query(".post-item"))
        self.cursor_position = len(items) - 1

    def key_ctrl_d(self) -> None:
        """Half page down"""
        if self.app.command_mode:
            return
        items = list(self.query(".post-item"))
        self.cursor_position = min(self.cursor_position + 5, len(items) - 1)

    def key_ctrl_u(self) -> None:
        """Half page up"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 5, 0)

    def key_w(self) -> None:
        """Word forward - move down by 3"""
        if self.app.command_mode:
            return
        items = list(self.query(".post-item"))
        self.cursor_position = min(self.cursor_position + 3, len(items) - 1)

    def key_b(self) -> None:
        """Word backward - move up by 3"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 3, 0)

    def on_key(self, event) -> None:
        """Handle g+g key combination for top and prevent escape from unfocusing"""
        # Don't process keys if app is in command mode
        if self.app.command_mode:
            return

        if event.key == "escape":
            # Prevent escape from unfocusing the feed
            event.prevent_default()
            event.stop()
            return
        if event.key == "g":
            now = time.time()
            if hasattr(self, "last_g_time") and now - self.last_g_time < 0.5:
                self.cursor_position = 0
                event.prevent_default()
                delattr(self, "last_g_time")
            else:
                self.last_g_time = now


class TimelineScreen(Container):
    def compose(self) -> ComposeResult:
        yield Sidebar(current="timeline", id="sidebar")
        yield TimelineFeed(id="timeline-feed")


class DiscoverFeed(VerticalScroll):
    cursor_position = reactive(0)
    query_text = reactive("")
    scroll_y = reactive(0)  # Track scroll position
    _search_timer = None  # Timer for debouncing search
    _all_posts = []  # Cache all posts locally
    _filtered_posts = []  # Currently filtered posts
    _displayed_count = 20  # Number of posts currently displayed
    _batch_size = 20  # Number of posts to load at a time
    _loading_more = False  # Flag to prevent multiple simultaneous loads

    def key_enter(self) -> None:
        """Open comment screen when pressing enter on a post"""
        if self.app.command_mode:
            return
        self.open_comment_screen()

    def open_comment_screen(self) -> None:
        """Open the comment screen for the currently focused post"""
        try:
            items = list(self.query(".post-item"))
            # Adjust cursor position to account for search input at position 0
            post_idx = self.cursor_position - 1
            if 0 <= post_idx < len(items):
                post_item = items[post_idx]
                post = getattr(post_item, "post", None)
                if post:
                    self.app.push_screen(CommentScreen(post))
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        self.border_title = "Discover"

        # Search input at the top
        yield Input(
            placeholder="[/] Search posts, people, tags...",
            classes="discover-search-input",
            id="discover-search",
        )

        # Fetch all posts once and cache them
        self._all_posts = api.get_discover_posts()
        self._filtered_posts = self._all_posts.copy()
        self._displayed_count = min(self._batch_size, len(self._filtered_posts))

        yield Static(
            "discover.trending | explore posts | line 1",
            classes="panel-header",
            markup=False,
        )

        # Initially display only the first batch
        for i, post in enumerate(self._filtered_posts[: self._displayed_count]):
            post_item = PostItem(post, classes="post-item", id=f"discover-post-{i}")
            # Don't add cursor here, will be handled by _update_cursor
            yield post_item

    def on_mount(self) -> None:
        self.watch(self, "cursor_position", self._update_cursor)
        self.watch(self, "scroll_y", self._check_scroll_load)

    def _check_scroll_load(self) -> None:
        """Check if we need to load more posts based on scroll position"""
        try:
            # Get the virtual size (total content height) and viewport size
            virtual_size = self.virtual_size.height
            container_size = self.container_size.height

            # If we're within 100 pixels of the bottom, load more
            if (
                virtual_size > 0
                and self.scroll_y + container_size >= virtual_size - 100
            ):
                self._load_more_posts()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input changes with debouncing"""
        if event.input.id == "discover-search":
            self.query_text = event.value

            # Cancel any existing timer
            if self._search_timer is not None:
                self._search_timer.stop()

            # Set a new timer to filter after 300ms of no typing
            self._search_timer = self.set_timer(0.3, self._filter_posts)

    def _filter_posts(self) -> None:
        """Filter posts based on search query from local cache"""
        try:
            # Filter from cached posts
            if self.query_text:
                q = self.query_text.lower()
                self._filtered_posts = [
                    p
                    for p in self._all_posts
                    if q in p.author.lower() or q in p.content.lower()
                ]
            else:
                self._filtered_posts = self._all_posts.copy()

            # Reset displayed count
            self._displayed_count = min(self._batch_size, len(self._filtered_posts))

            # Remove existing post items
            for item in self.query(".post-item"):
                item.remove()

            # Add filtered posts (only first batch)
            for i, post in enumerate(self._filtered_posts[: self._displayed_count]):
                post_item = PostItem(post, classes="post-item", id=f"discover-post-{i}")
                self.mount(post_item)

            # Reset cursor to search input (position 0)
            self.cursor_position = 0
        except Exception:
            pass

    def _load_more_posts(self) -> None:
        """Load the next batch of posts from filtered cache"""
        if self._loading_more or self._displayed_count >= len(self._filtered_posts):
            return

        self._loading_more = True
        try:
            # Calculate how many new posts to add
            old_count = self._displayed_count
            self._displayed_count = min(
                self._displayed_count + self._batch_size, len(self._filtered_posts)
            )

            # Mount the new posts
            for i in range(old_count, self._displayed_count):
                post = self._filtered_posts[i]
                post_item = PostItem(post, classes="post-item", id=f"discover-post-{i}")
                self.mount(post_item)
        finally:
            self._loading_more = False

    def key_slash(self) -> None:
        """Focus search input with / key"""
        if self.app.command_mode:
            return
        # Set cursor to position 0 and focus the input
        self.cursor_position = 0
        try:
            search_input = self.query_one("#discover-search", Input)
            search_input.focus()
        except Exception:
            pass

    def _get_navigable_items(self) -> list:
        """Get all navigable items (search input + posts)"""
        try:
            search_input = self.query_one("#discover-search", Input)
            post_items = list(self.query(".post-item"))
            return [search_input] + post_items
        except Exception:
            return []

    def _update_cursor(self) -> None:
        """Update the cursor position - includes search input + posts"""
        try:
            items = self._get_navigable_items()
            post_items = list(self.query(".post-item"))
            search_input = self.query_one("#discover-search", Input)

            # Remove cursor from all post items and search input
            for item in post_items:
                item.remove_class("vim-cursor")
            search_input.remove_class("vim-cursor")

            if 0 <= self.cursor_position < len(items):
                item = items[self.cursor_position]
                if isinstance(item, Input):
                    # Don't focus the input, just add visual indicator
                    item.add_class("vim-cursor")
                    # Make sure feed has focus so vim keys work
                    self.focus()
                else:
                    # Add cursor class to post
                    item.add_class("vim-cursor")
                self.scroll_to_widget(item, top=True)

                # Load more posts if we're near the end (within 5 posts)
                # Subtract 1 because position 0 is the search input
                if self.cursor_position > 0 and self.cursor_position >= len(items) - 5:
                    self._load_more_posts()
        except Exception:
            pass

    def on_focus(self) -> None:
        """When the feed gets focus"""
        self.cursor_position = 0
        self._update_cursor()

    def on_blur(self) -> None:
        """When feed loses focus"""
        pass

    def on_scroll(self, event) -> None:
        """Update scroll position reactive when scrolling"""
        self.scroll_y = self.scroll_offset.y

    def key_j(self) -> None:
        """Move down with j key"""
        if self.app.command_mode:
            return
        items = self._get_navigable_items()
        if self.cursor_position < len(items) - 1:
            self.cursor_position += 1

    def key_k(self) -> None:
        """Move up with k key"""
        if self.app.command_mode:
            return
        if self.cursor_position > 0:
            self.cursor_position -= 1

    def key_g(self) -> None:
        """Go to top with gg"""
        if self.app.command_mode:
            return
        pass  # Handled in on_key for double-press

    def key_G(self) -> None:
        """Go to bottom with G"""
        if self.app.command_mode:
            return
        items = self._get_navigable_items()
        self.cursor_position = len(items) - 1

    def key_ctrl_d(self) -> None:
        """Half page down"""
        if self.app.command_mode:
            return
        items = self._get_navigable_items()
        self.cursor_position = min(self.cursor_position + 5, len(items) - 1)

    def key_ctrl_u(self) -> None:
        """Half page up"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 5, 0)

    def key_w(self) -> None:
        """Word forward - move down by 3"""
        if self.app.command_mode:
            return
        items = self._get_navigable_items()
        self.cursor_position = min(self.cursor_position + 3, len(items) - 1)

    def key_b(self) -> None:
        """Word backward - move up by 3"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 3, 0)

    def key_i(self) -> None:
        """Focus search input with i key (insert mode) when cursor is on it"""
        if self.app.command_mode:
            return
        if self.cursor_position == 0:
            try:
                search_input = self.query_one("#discover-search", Input)
                search_input.focus()
            except Exception:
                pass

    def on_key(self, event) -> None:
        """Handle g+g key combination for top and escape from search"""
        # Don't process keys if app is in command mode
        if self.app.command_mode:
            return

        if event.key == "escape":
            # If search input has focus, move cursor to first post and return focus to feed
            try:
                search_input = self.query_one("#discover-search", Input)
                if search_input.has_focus:
                    # Move cursor to first post (position 1)
                    self.cursor_position = 1
                    # Remove focus from input and give it back to feed
                    self.focus()
                    event.prevent_default()
                    event.stop()
                    return
            except Exception:
                pass

        # If cursor is on search input (position 0) and user types a letter/number/space
        # Focus the search input to start typing
        if self.cursor_position == 0:
            # Check if it's a typeable character (letter, number, space, punctuation except vim keys)
            if len(event.key) == 1 and event.key not in [
                "j",
                "k",
                "g",
                "G",
                "w",
                "b",
                "h",
                "l",
                "0",
                "1",
                "2",
                "3",
                "4",
                "5",
                "6",
                "p",
                "d",
                "i",
                "q",
                ":",
                "/",
            ]:
                try:
                    search_input = self.query_one("#discover-search", Input)
                    search_input.focus()
                    # Let the event propagate to the input
                    return
                except Exception:
                    pass

        if event.key == "g":
            now = time.time()
            if hasattr(self, "last_g_time") and now - self.last_g_time < 0.5:
                self.cursor_position = 0
                event.prevent_default()
                delattr(self, "last_g_time")
            else:
                self.last_g_time = now


class DiscoverScreen(Container):
    def compose(self) -> ComposeResult:
        yield Sidebar(current="discover", id="sidebar")
        yield DiscoverFeed(id="discover-feed")


class NotificationsFeed(VerticalScroll):
    cursor_position = reactive(0)

    def compose(self) -> ComposeResult:
        notifications = api.get_notifications()
        unread_count = len([n for n in notifications if not n.read])
        self.border_title = "Notifications"
        yield Static(
            f"notifications.all | {unread_count} unread | line 1",
            classes="panel-header",
        )
        for i, notif in enumerate(notifications):
            item = NotificationItem(notif, classes="notification-item", id=f"notif-{i}")
            if i == 0:
                item.add_class("vim-cursor")
            yield item
        yield Static(
            "\n[j/k] Navigate [Enter] Open [:q] Quit",
            classes="help-text",
            markup=False,
        )

    def on_mount(self) -> None:
        """Watch for cursor position changes"""
        self.watch(self, "cursor_position", self._update_cursor)

    def _update_cursor(self) -> None:
        """Update the cursor position"""
        try:
            items = list(self.query(".notification-item"))
            for item in items:
                item.remove_class("vim-cursor")

            if 0 <= self.cursor_position < len(items):
                item = items[self.cursor_position]
                item.add_class("vim-cursor")
                self.scroll_to_widget(item)
        except Exception:
            pass

    def key_j(self) -> None:
        """Move down with j key"""
        if self.app.command_mode:
            return
        items = list(self.query(".notification-item"))
        if self.cursor_position < len(items) - 1:
            self.cursor_position += 1

    def key_k(self) -> None:
        """Move up with k key"""
        if self.app.command_mode:
            return
        if self.cursor_position > 0:
            self.cursor_position -= 1

    def key_g(self) -> None:
        """Go to top with gg"""
        if self.app.command_mode:
            return
        pass  # Handled in on_key for double-press

    def key_G(self) -> None:
        """Go to bottom with G"""
        if self.app.command_mode:
            return
        items = list(self.query(".notification-item"))
        self.cursor_position = len(items) - 1

    def key_ctrl_d(self) -> None:
        """Half page down"""
        if self.app.command_mode:
            return
        items = list(self.query(".notification-item"))
        self.cursor_position = min(self.cursor_position + 5, len(items) - 1)

    def key_ctrl_u(self) -> None:
        """Half page up"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 5, 0)

    def key_w(self) -> None:
        """Word forward - move down by 3"""
        if self.app.command_mode:
            return
        items = list(self.query(".notification-item"))
        self.cursor_position = min(self.cursor_position + 3, len(items) - 1)

    def key_b(self) -> None:
        """Word backward - move up by 3"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 3, 0)

    def on_key(self, event) -> None:
        """Handle g+g key combination for top and prevent escape from unfocusing"""
        # Don't process keys if app is in command mode
        if self.app.command_mode:
            return

        if event.key == "escape":
            # Prevent escape from unfocusing the feed
            event.prevent_default()
            event.stop()
            return
        if event.key == "g":
            now = time.time()
            if hasattr(self, "last_g_time") and now - self.last_g_time < 0.5:
                self.cursor_position = 0
                event.prevent_default()
                delattr(self, "last_g_time")
            else:
                self.last_g_time = now


class NotificationsScreen(Container):
    def compose(self) -> ComposeResult:
        yield Sidebar(current="notifications", id="sidebar")
        yield NotificationsFeed(id="notifications-feed")


class ConversationsList(VerticalScroll):
    cursor_position = reactive(0)
    selected_position = reactive(-1)
    can_focus = True
    # Track whether the list has performed its initial mount setup
    has_initialized = False

    def compose(self) -> ComposeResult:
        # Fetch conversations and sort most-recent-first by last_message_at
        conversations = api.get_conversations()
        try:
            conversations = sorted(
                conversations, key=lambda c: c.last_message_at, reverse=True
            )
        except Exception:
            # Fallback: leave order as-is
            pass

        # Store the ordered list so keyboard actions refer to the same ordering
        self._conversations = conversations

        unread_count = len([c for c in conversations if c.unread])
        yield Static(f"conversations | {unread_count} unread", classes="panel-header")
        for i, conv in enumerate(conversations):
            item = ConversationItem(conv, classes="conversation-item", id=f"conv-{i}")
            yield item

    def on_mount(self) -> None:
        """Watch for cursor position changes"""
        self.watch(self, "cursor_position", self._update_cursor)
        self.watch(self, "selected_position", self._update_selected)
        # Only perform initial focus and cursor setup the first time the list mounts.
        try:
            if not getattr(self, "has_initialized", False):
                # Default to first item only on first mount
                self.cursor_position = 0
                # Update visuals immediately
                self._update_cursor()
                # Give focus to the conversations list so keyboard navigation works right away
                try:
                    self.focus()
                except Exception:
                    pass
                self.has_initialized = True
        except Exception:
            pass

    def _update_cursor(self) -> None:
        """Update the cursor position"""
        try:
            # Find all conversation items
            items = list(self.query(".conversation-item"))

            # Remove cursor from all items
            for item in items:
                item.remove_class("vim-cursor")

            # Add cursor to focused item
            if 0 <= self.cursor_position < len(items):
                item = items[self.cursor_position]
                item.add_class("vim-cursor")
                # Ensure the cursor is visible
                self.scroll_to_widget(item, top=True)
        except Exception:
            pass

    def _update_selected(self) -> None:
        """Update the selected position (blue background for open conversation)"""
        try:
            # Find all conversation items
            items = list(self.query(".conversation-item"))

            # Remove selected from all items
            for item in items:
                item.remove_class("selected")

            # Add selected to the open conversation
            if 0 <= self.selected_position < len(items):
                item = items[self.selected_position]
                item.add_class("selected")
        except Exception:
            pass

    def on_focus(self) -> None:
        """When the list gets focus"""
        # Don't override the user's cursor_position when focusing; just refresh visuals
        try:
            self._update_cursor()
        except Exception:
            pass

    def on_blur(self) -> None:
        """When list loses focus"""
        pass

    def key_j(self) -> None:
        """Move down with j key"""
        if self.app.command_mode:
            return
        items = list(self.query(".conversation-item"))
        if self.cursor_position < len(items) - 1:
            self.cursor_position += 1

    def key_k(self) -> None:
        """Move up with k key"""
        if self.app.command_mode:
            return
        if self.cursor_position > 0:
            self.cursor_position -= 1

    def key_g(self) -> None:
        """Go to top with gg"""
        if self.app.command_mode:
            return
        # g is handled in on_key for double-press
        pass

    def key_G(self) -> None:
        """Go to bottom with G"""
        if self.app.command_mode:
            return
        items = list(self.query(".conversation-item"))
        self.cursor_position = len(items) - 1

    def key_ctrl_d(self) -> None:
        """Half page down"""
        if self.app.command_mode:
            return
        items = list(self.query(".conversation-item"))
        self.cursor_position = min(self.cursor_position + 5, len(items) - 1)

    def key_ctrl_u(self) -> None:
        """Half page up"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 5, 0)

    def key_w(self) -> None:
        """Word forward - move down by 3"""
        if self.app.command_mode:
            return
        items = list(self.query(".conversation-item"))
        self.cursor_position = min(self.cursor_position + 3, len(items) - 1)

    def key_b(self) -> None:
        """Word backward - move up by 3"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 3, 0)

    def key_enter(self) -> None:
        """Open the selected conversation when Enter is pressed"""
        if self.app.command_mode:
            return
        try:
            conversations = api.get_conversations()
            if 0 <= self.cursor_position < len(conversations):
                conv = conversations[self.cursor_position]
                # Mark this conversation as selected (blue background)
                self.selected_position = self.cursor_position

                # Get the other participant's username
                current_user = get_username() or "yourname"
                other_participants = [h for h in conv.participant_handles if h != current_user]
                username = other_participants[0] if other_participants else conv.participant_handles[0] if conv.participant_handles else "unknown"

                # Get MessagesScreen parent container
                messages_screen = self.parent
                if isinstance(messages_screen, MessagesScreen):
                    messages_screen._open_chat_view(conv.id, username)

                    # Focus the chat view
                    try:
                        chat_views = list(messages_screen.query("ChatView"))
                        if chat_views:
                            chat_views[0].focus()
                    except:
                        pass
        except Exception:
            pass

    def on_key(self, event) -> None:
        """Handle g+g key combination for top and prevent escape from unfocusing"""
        if self.app.command_mode:
            return
        if event.key == "escape":
            # Prevent escape from unfocusing the conversation list
            event.prevent_default()
            event.stop()
            return
        if event.key == "g":
            now = time.time()
            if hasattr(self, "last_g_time") and now - self.last_g_time < 0.5:
                self.cursor_position = 0
                event.prevent_default()
                delattr(self, "last_g_time")
            else:
                self.last_g_time = now


class ChatView(VerticalScroll):
    conversation_id = reactive(0)  # Changed to int to match backend
    conversation_username = reactive("")
    cursor_position = reactive(0)
    input_active = reactive(False)

    def __init__(self, conversation_id: int = 0, username: str = "", **kwargs):
        super().__init__(**kwargs)
        self.conversation_id = conversation_id
        self.conversation_username = username
        # Use an app-level sender map so colors remain stable across views
        if not hasattr(self.app, "_sender_map_global"):
            # store as {lower_handle: index}
            setattr(self.app, "_sender_map_global", {})
            setattr(self.app, "_sender_map_next_idx", 0)

    def compose(self) -> ComposeResult:
        self.border_title = "[0] Chat"

        # If no conversation is selected, show a friendly placeholder
        if not self.conversation_id or self.conversation_id <= 0:
            yield Static("Select a conversation", classes="panel-header")
            yield Static(
                "\nSelect a conversation from the list on the left to view messages.",
                classes="help-text",
                markup=False,
            )
            return

        # Only fetch messages if conversation_id is valid (> 0)
        messages = []
        try:
            messages = api.get_conversation_messages(self.conversation_id)
        except Exception:
            messages = []

        # Resolve current user once for use in message rendering
        current_user = get_username() or api.handle or "yourname"

        # Build a sender->index resolver using a global map on the app so colors persist
        def _sender_idx(sender: str) -> int:
            s = (sender or "").lower()
            global_map = getattr(self.app, "_sender_map_global", {})
            if s in global_map:
                return global_map[s]
            next_idx = getattr(self.app, "_sender_map_next_idx", 0)
            idx = next_idx % 5
            global_map[s] = idx
            setattr(self.app, "_sender_map_global", global_map)
            setattr(self.app, "_sender_map_next_idx", next_idx + 1)
            return idx

        # Persist read-state for this conversation (centralized so all open flows mark read)
        if getattr(self, "conversation_id", 0):
            try:
                # Tell backend this conversation was read by current user
                try:
                    api.mark_conversation_read(int(self.conversation_id))
                except Exception:
                    # Non-fatal: if the API call fails, continue and still update UI locally
                    pass

                # Also update the locally-stored conversations list so the header/unread dot refreshes
                try:
                    convs_list = self.app.query_one("#conversations", ConversationsList)
                    if (
                        hasattr(convs_list, "_conversations")
                        and convs_list._conversations is not None
                    ):
                        for c in convs_list._conversations:
                            if int(c.id) == int(self.conversation_id):
                                c.unread = False
                                break
                        unread_count = len(
                            [
                                c
                                for c in convs_list._conversations
                                if getattr(c, "unread", False)
                            ]
                        )
                        try:
                            header = convs_list.query_one(".panel-header", Static)
                            header.update(f"conversations | {unread_count} unread")
                        except Exception:
                            pass
                except Exception:
                    pass
            except Exception:
                pass

        yield Static(
            f"@{self.conversation_username} | conversation", classes="panel-header"
        )
        for msg in messages:
            idx = _sender_idx(msg.sender)
            sender_class = f"sender-{idx}"
            cls = f"chat-message {sender_class}"
            yield ChatMessage(msg, current_user=current_user, classes=cls)
        yield Static("-- INSERT --", classes="mode-indicator")
        yield Input(
            placeholder="Type message and press Enter… (Esc to cancel)",
            classes="message-input",
            id="message-input",
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "message-input":
            return
        text = event.value.strip()
        if not text:
            return

        # Only send if conversation_id is valid
        if self.conversation_id <= 0:
            return

        try:
            new_msg = api.send_message(self.conversation_id, text)
            # Determine sender class for the new message (use app-global map)
            current_user = get_username() or api.handle or ""
            sender = new_msg.sender or new_msg.sender_handle or current_user
            # Ensure global map exists
            if not hasattr(self.app, "_sender_map_global"):
                setattr(self.app, "_sender_map_global", {})
                setattr(self.app, "_sender_map_next_idx", 0)
            global_map = getattr(self.app, "_sender_map_global")
            if sender.lower() not in global_map:
                next_idx = getattr(self.app, "_sender_map_next_idx", 0)
                global_map[sender.lower()] = next_idx % 5
                setattr(self.app, "_sender_map_next_idx", next_idx + 1)
                setattr(self.app, "_sender_map_global", global_map)
            idx = global_map[sender.lower()]
            sender_class = f"sender-{idx}"
            classes = f"chat-message sent {sender_class}"
            self.mount(
                ChatMessage(new_msg, current_user=current_user, classes=classes),
                before=event.input,
            )
            event.input.value = ""
            event.input.focus()
            self.scroll_end(animate=False)
        except Exception as e:
            # Handle error silently or show notification
            pass

    def watch_cursor_position(self, old_position: int, new_position: int) -> None:
        """Update the cursor when position changes"""
        # Remove cursor from old position
        messages = self.query(".chat-message")
        if old_position < len(messages):
            old_msg = messages[old_position]
            if "vim-cursor" in old_msg.classes:
                old_msg.remove_class("vim-cursor")

        # Add cursor to new position
        if new_position < len(messages):
            new_msg = messages[new_position]
            new_msg.add_class("vim-cursor")

            self.scroll_to_widget(new_msg)

    def focus_last_message(self) -> None:
        """Focus and select the last message in the chat after messages have mounted."""
        try:

            def _do_focus_last():
                try:
                    msgs = list(self.query(".chat-message"))
                    if not msgs:
                        return
                    # Instead of focusing the last message, select the input
                    # which is positioned after the last message (index == len(msgs)).
                    inp_idx = len(msgs)
                    # Set cursor position which triggers the watch_cursor_position
                    # logic to visually mark the input without entering insert mode.
                    self.cursor_position = inp_idx
                except Exception:
                    pass

            # Schedule after the layout refresh so children exist
            try:
                self.call_after_refresh(_do_focus_last)
            except Exception:
                # Fallback small timer
                try:
                    self.set_timer(0.02, _do_focus_last)
                except Exception:
                    _do_focus_last()
        except Exception:
            pass

    def key_j(self) -> None:
        """Vim-style down navigation"""
        if self.app.command_mode:
            return
        messages = list(self.query(".chat-message"))
        # allow moving into the input (index == len(messages))
        if self.cursor_position < len(messages):
            self.cursor_position += 1

    def key_k(self) -> None:
        """Vim-style up navigation"""
        if self.app.command_mode:
            return
        # Move up through messages and from the input back into messages
        if self.cursor_position > 0:
            # If currently on the input and input_active, exit insert mode first
            if (
                self.cursor_position == len(list(self.query(".chat-message")))
                and self.input_active
            ):
                try:
                    inp = self.query_one("#message-input", Input)
                    try:
                        inp.blur()
                    except Exception:
                        pass
                    self.input_active = False
                except Exception:
                    pass
            self.cursor_position -= 1

    def key_i(self) -> None:
        """Enter insert mode on the input when cursor is over it."""
        if self.app.command_mode:
            return
        messages = list(self.query(".chat-message"))
        if self.cursor_position == len(messages):
            try:
                inp = self.query_one("#message-input", Input)
                inp.focus()
                self.input_active = True
            except Exception:
                pass

    def key_enter(self) -> None:
        """If cursor is over input, start input (same as 'i')."""
        if self.app.command_mode:
            return
        messages = list(self.query(".chat-message"))
        if self.cursor_position == len(messages):
            try:
                inp = self.query_one("#message-input", Input)
                inp.focus()
                self.input_active = True
            except Exception:
                pass

    def key_g(self) -> None:
        """Vim-style go to top"""
        if self.app.command_mode:
            return
        self.cursor_position = 0

    def key_G(self) -> None:
        """Vim-style go to bottom"""
        if self.app.command_mode:
            return
        messages = self.query(".chat-message")
        self.cursor_position = max(0, len(messages) - 1)


class MessagesScreen(Container):
    def __init__(self, username: str = None, **kwargs):
        super().__init__(**kwargs)
        self.dm_username = username
        self._switching = False

    def compose(self) -> ComposeResult:
        yield Sidebar(current="messages", id="sidebar")
        yield ConversationsList(id="conversations")

        # If a specific username is provided, open chat with them
        if self.dm_username:
            # Get or create conversation with this user
            try:
                conv = api.get_or_create_dm(self.dm_username)
                yield ChatView(
                    conversation_id=conv.id, username=self.dm_username, id="chat"
                )
            except Exception:
                # Fallback if API call fails
                yield ChatView(conversation_id=0, username=self.dm_username, id="chat")
        else:
            yield ChatView(id="chat")

    def on_mount(self) -> None:
        """Add border to conversations list and update chat if DM"""
        conversations = self.query_one("#conversations", ConversationsList)
        conversations.border_title = "[6] Messages"

        # If opening a DM, update the chat header
        if self.dm_username:
            try:
                chat = self.query_one("#chat", ChatView)
                # Update the header to show we're chatting with this user
                header = chat.query_one(".panel-header", Static)
                header.update(f"@{self.dm_username} | new conversation")

                # Focus the message input
                self.call_after_refresh(self._focus_message_input)
            except:
                pass
        else:
            # No DM open: focus the conversations list and ensure first item selected
            try:
                # Use call_after_refresh to avoid races with initial compose
                def _focus_conversations():
                    try:
                        conversations.cursor_position = 0
                        conversations._update_cursor()
                        conversations.focus()
                    except Exception:
                        pass

                self.call_after_refresh(_focus_conversations)
            except Exception:
                pass

    def _focus_message_input(self):
        """Focus the message input for new DM"""
        try:
            msg_input = self.query_one("#message-input", Input)
            msg_input.focus()
        except:
            pass

    def _open_chat_view(self, conversation_id: int, username: str) -> None:
        """Open or update the chat view with a specific conversation"""
        # Prevent concurrent switches
        if self._switching:
            return

        try:
            # Remove empty state if it exists
            try:
                empty_state = self.query_one("#chat-empty-state")
                empty_state.remove()
            except:
                pass

            # Check if any chat view already exists
            existing_chats = list(self.query("ChatView"))

            if existing_chats:
                # Check if we're already viewing this conversation
                for chat_view in existing_chats:
                    if chat_view.conversation_id == conversation_id:
                        # Already viewing this conversation, do nothing
                        return

                # Different conversation - need to switch
                self._switching = True
                # Remove all existing chat views
                for chat_view in existing_chats:
                    chat_view.remove()
                # Use set_timer with delay to ensure removal completes before mounting
                self.set_timer(0.1, lambda: self._mount_new_chat(conversation_id, username))
            else:
                # No chat view exists, create it
                chat_view = ChatView(conversation_id=conversation_id, username=username, id="chat")
                self.mount(chat_view)
        except Exception as e:
            # Handle error silently
            self._switching = False
            pass

    def _mount_new_chat(self, conversation_id: int, username: str) -> None:
        """Mount a new chat view after old one has been removed"""
        try:
            # Remove any existing chat views (should already be gone, but double check)
            for existing in self.query("ChatView"):
                existing.remove()

            # Create new chat view with standard "chat" ID for CSS
            new_chat_view = ChatView(conversation_id=conversation_id, username=username, id="chat")
            self.mount(new_chat_view)
            # Scroll to bottom to show latest messages
            self.call_after_refresh(lambda: new_chat_view.scroll_end(animate=False))
        except Exception as e:
            self.app.notify(f"Error creating chat: {e}", timeout=2)
        finally:
            # Reset switching flag
            self._switching = False


class SettingsPanel(VerticalScroll):
    cursor_position = reactive(0)
    settings_loaded = reactive(False)

    def compose(self) -> ComposeResult:
        """Build settings content synchronously so items are real children
        of the VerticalScroll (matching Timeline/Discover). This makes
        scroll_to_widget and vim-style navigation work identically.
        """
        self.border_title = "Settings"

        try:
            settings = api.get_user_settings()
        except Exception:
            # If the API call fails, provide a lightweight fallback so the
            # screen still composes and shows an error message that can be
            # replaced once on_mount runs.
            settings = None

        # Header
        yield Static("settings.profile | line 1", classes="panel-header")

        # Profile Picture section
        yield Static("\n→ Profile Picture (ASCII)", classes="settings-section-header")
        yield Static("Make ASCII Profile Picture from image file")
        yield Button(
            "Upload file",
            id="upload-profile-picture",
            classes="upload-profile-picture",
        )

        # Display current ascii avatar if available
        avatar_text = (
            getattr(settings, "ascii_pic", "") if settings else "(not available)"
        )
        yield Static(avatar_text, id="profile-picture-display", classes="ascii-avatar")

        # Account information
        yield Static("\n→ Account Information", classes="settings-section-header")
        username = get_username()
        if username is None and settings:
            username = getattr(settings, "username", "yourname")
        yield Static(f"  Username:\n  @{username}", classes="settings-field")
        if settings:
            yield Static(
                f"\n  Display Name:\n  {settings.display_name}",
                classes="settings-field",
            )
            yield Static(f"\n  Bio:\n  {settings.bio}", classes="settings-field")
        else:
            yield Static("\n  Display Name:\n  (loading)", classes="settings-field")
            yield Static("\n  Bio:\n  (loading)", classes="settings-field")

        # OAuth connections - use Buttons so they are navigable
        yield Static("\n→ OAuth Connections", classes="settings-section-header")
        github_status = (
            "Connected"
            if settings and getattr(settings, "github_connected", False)
            else "[:c] Connect"
        )
        gitlab_status = (
            "Connected"
            if settings and getattr(settings, "gitlab_connected", False)
            else "[:c] Connect"
        )
        google_status = (
            "Connected"
            if settings and getattr(settings, "google_connected", False)
            else "[:c] Connect"
        )
        discord_status = (
            "Connected"
            if settings and getattr(settings, "discord_connected", False)
            else "[:c] Connect"
        )
        yield Button(
            f"  [🟢] GitHub                                              {github_status}",
            id="oauth-github",
            classes="oauth-item",
        )
        yield Button(
            f"  [⚪] GitLab                                              {gitlab_status}",
            id="oauth-gitlab",
            classes="oauth-item",
        )
        yield Button(
            f"  [⚪] Google                                              {google_status}",
            id="oauth-google",
            classes="oauth-item",
        )
        yield Button(
            f"  [⚪] Discord                                             {discord_status}",
            id="oauth-discord",
            classes="oauth-item",
        )

        # Preferences
        yield Static("\n→ Preferences", classes="settings-section-header")
        email_check = (
            "✅"
            if settings and getattr(settings, "email_notifications", False)
            else "⬜"
        )
        online_check = (
            "✅"
            if settings and getattr(settings, "show_online_status", False)
            else "⬜"
        )
        private_check = (
            "✅" if settings and getattr(settings, "private_account", False) else "⬜"
        )
        yield Button(
            f"  {email_check} Email notifications",
            id="pref-email_notifications",
            classes="checkbox-item",
        )
        yield Button(
            f"  {online_check} Show online status",
            id="pref-show_online_status",
            classes="checkbox-item",
        )
        yield Button(
            f"  {private_check} Private account",
            id="pref-private_account",
            classes="checkbox-item",
        )

        # Session / Sign out
        yield Static("\n→ Session", classes="settings-section-header")
        yield Button("Sign Out", id="settings-signout", classes="danger")

    def on_mount(self) -> None:
        """Fetch settings after mount to ensure API handle is set."""
        try:
            # Ensure we have the latest settings; compose built a best-effort view
            try:
                latest = api.get_user_settings()
                # If compose used a placeholder, update widgets now
                try:
                    avatar = self.query_one("#profile-picture-display", Static)
                    avatar.update(getattr(latest, "ascii_pic", ""))
                except Exception:
                    pass
            except Exception:
                pass

            # Mark loaded and initialize cursor/focus so navigation works
            self.settings_loaded = True
            try:
                self.cursor_position = 0
            except Exception:
                pass
            try:
                # Focus the panel so it receives vim key events
                self.focus()
            except Exception:
                pass
            # Ensure first selectable item shows the cursor visually
            try:
                selectable_classes = [
                    ".upload-profile-picture",
                    ".oauth-item",
                    ".checkbox-item",
                    ".danger",
                ]
                items = []
                for cls in selectable_classes:
                    items.extend(list(self.query(cls)))
                if items:
                    first = items[0]
                    first.add_class("vim-cursor")
                    try:
                        if isinstance(first, Button):
                            first.add_class("action-selected")
                    except Exception:
                        pass
            except Exception:
                pass

        except Exception as e:
            # Handle API error gracefully
            try:
                self.query_one("#settings-loading").remove()
            except Exception:
                pass

            container = self.query_one("#settings-content", Container)
            container.mount(
                Static(
                    f"⚠️ Failed to load settings\n\nError: {str(e)}\n\nAPI Handle: {api.handle}",
                    classes="panel-header",
                )
            )
            container.mount(
                Static(
                    "\nThis is likely a server-side issue. The username was sent correctly.",
                    classes="settings-field",
                )
            )
            container.mount(Static("\n→ Session", classes="settings-section-header"))
            container.mount(Button("Sign Out", id="settings-signout", classes="danger"))

            try:
                self.app.log_auth_event(
                    f"SettingsPanel: ERROR loading settings - {str(e)}"
                )
            except Exception:
                pass

            # Show notification
            try:
                self.app.notify(
                    f"Failed to load settings: {str(e)}", severity="error", timeout=5
                )
            except Exception:
                pass

    def watch_cursor_position(self, old_position: int, new_position: int) -> None:
        """Update the cursor when position changes"""
        # We'll consider settings items that can be selected for cursor movement:
        selectable_classes = [
            ".upload-profile-picture",
            ".oauth-item",
            ".checkbox-item",
            ".danger",
        ]

        items = []
        for cls in selectable_classes:
            items.extend(list(self.query(cls)))

        # Remove cursor from old position
        if old_position < len(items):
            old_item = items[old_position]
            if "vim-cursor" in old_item.classes:
                old_item.remove_class("vim-cursor")
                try:
                    # If the old item was a Button, remove any button-specific
                    # selection class so the visual state matches other panels.
                    if isinstance(old_item, Button):
                        old_item.remove_class("action-selected")
                except Exception:
                    pass

        # Add cursor to new position
        if new_position < len(items):
            new_item = items[new_position]
            new_item.add_class("vim-cursor")
            try:
                # If the selected item is a Button, add a visible selection
                # class used elsewhere (e.g. Drafts) so the sign-out button
                # and other Buttons show the expected focus state.
                if isinstance(new_item, Button):
                    new_item.add_class("action-selected")
            except Exception:
                pass
            # Scroll so the selected item is visible and keep focus on the panel
            self.scroll_to_widget(new_item)
            try:
                # Keep focus on the panel so vim navigation (j/k) is handled here
                self.focus()
            except Exception:
                pass

    def key_j(self) -> None:
        """Vim-style down navigation"""
        if self.app.command_mode:
            return
        selectable_classes = [
            ".upload-profile-picture",
            ".oauth-item",
            ".checkbox-item",
            ".danger",
        ]
        items = []
        for cls in selectable_classes:
            items.extend(list(self.query(cls)))

        if self.cursor_position < len(items) - 1:
            self.cursor_position += 1

    def key_k(self) -> None:
        """Vim-style up navigation"""
        if self.app.command_mode:
            return
        if self.cursor_position > 0:
            self.cursor_position -= 1

    def key_g(self) -> None:
        """Vim-style go to top"""
        if self.app.command_mode:
            return
        self.cursor_position = 0

    def key_G(self) -> None:
        """Vim-style go to bottom"""
        if self.app.command_mode:
            return
        selectable_classes = [
            ".upload-profile-picture",
            ".oauth-item",
            ".checkbox-item",
            ".danger",
        ]
        items = []
        for cls in selectable_classes:
            items.extend(list(self.query(cls)))
        self.cursor_position = max(0, len(items) - 1)

    def on_focus(self) -> None:
        """When the panel gets focus, ensure cursor is initialized and visible."""
        try:
            # If settings not yet loaded, _on_mount will initialize
            if self.settings_loaded:
                self.cursor_position = max(0, self.cursor_position)
                try:
                    self.focus()
                except Exception:
                    pass
        except Exception:
            pass

    def key_enter(self) -> None:
        """Activate the currently-selected settings item when Enter is pressed.

        We keep focus on the panel so vim keys are handled here; Enter will
        trigger the underlying Button if present.
        """
        if self.app.command_mode:
            return
        selectable_classes = [
            ".upload-profile-picture",
            ".oauth-item",
            ".checkbox-item",
            ".danger",
        ]
        items = []
        for cls in selectable_classes:
            items.extend(list(self.query(cls)))

        if 0 <= self.cursor_position < len(items):
            item = items[self.cursor_position]
            try:
                # If the item is a Button, call its press method to trigger handlers
                if hasattr(item, "press"):
                    item.press()
                else:
                    # Fallback: try to call on_click or simulate a button press event
                    try:
                        item.on_click()
                    except Exception:
                        pass
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = getattr(event.button, "id", "")

        # Upload profile picture
        if btn_id == "upload-profile-picture":
            try:
                root = tk.Tk()
                root.withdraw()
                file_path = filedialog.askopenfilename(
                    title="Select an Image",
                    filetypes=[("Image files", "*.png *.jpg *.jpeg")],
                )
                root.destroy()

                if not file_path:
                    return

                script_path = Path("asciifer/asciifer.py")
                if not script_path.exists():
                    return

                output_text = "output.txt"
                output_image = "output.png"
                font_path = "/System/Library/Fonts/Monaco.ttf"

                cmd = [
                    sys.executable,
                    str(script_path),
                    "--output-text",
                    output_text,
                    "--output-image",
                    output_image,
                    "--font",
                    font_path,
                    "--font-size",
                    "24",
                    file_path,
                ]

                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    return

                if Path(output_text).exists():
                    with open(output_text, "r") as f:
                        lines = f.read().splitlines()

                    max_width = max((len(line) for line in lines), default=0)
                    max_lines = int(max_width / 2)
                    lines = lines[:max_lines]
                    ascii_art = "\n".join(lines)

                    settings = api.get_user_settings()
                    settings.ascii_pic = ascii_art
                    api.update_user_settings(settings)

                    try:
                        avatar = self.query_one("#profile-picture-display", Static)
                        avatar.update(ascii_art)
                        self.app.notify("Profile picture updated!", severity="success")
                    except Exception as e:
                        try:
                            self.app.notify(f"Widget not found: {e}", severity="error")
                        except Exception:
                            pass
                else:
                    try:
                        self.app.notify("Output file not generated", severity="error")
                    except Exception:
                        pass
            except Exception:
                pass

        # Sign out
        elif btn_id == "settings-signout":
            try:
                from .auth import clear_credentials

                try:
                    clear_credentials()
                except Exception:
                    # best-effort fallback: try centralized clear_tokens, then legacy deletes
                    try:
                        from .auth_storage import clear_tokens

                        clear_tokens()
                    except Exception:
                        try:
                            keyring.delete_password(serviceKeyring, "refresh_token")
                        except Exception:
                            pass
                        try:
                            keyring.delete_password(serviceKeyring, "username")
                        except Exception:
                            pass
                        try:
                            keyring.delete_password(serviceKeyring, "oauth_tokens.json")
                        except Exception:
                            pass

                # Clear API auth header and reset handle
                try:
                    from .api_interface import api

                    try:
                        api.session.headers.pop("Authorization", None)
                    except Exception:
                        pass
                    try:
                        api.handle = "yourname"
                    except Exception:
                        pass
                except Exception:
                    pass

                try:
                    self.app.notify(
                        "Signing out and exiting application...", severity="info"
                    )
                except Exception:
                    pass

                # small sleep to allow any UI notifications to flush
                try:
                    import time as _time

                    _time.sleep(0.05)
                except Exception:
                    pass

                try:
                    self.app.exit()
                except Exception:
                    try:
                        import sys as _sys

                        _sys.exit(0)
                    except Exception:
                        pass
            except Exception:
                pass

        # OAuth connection buttons (focusable)
        elif btn_id and btn_id.startswith("oauth-"):
            provider = btn_id.split("-", 1)[1]
            try:
                self.app.notify(
                    f"OAuth action: {provider} (not implemented)", severity="info"
                )
            except Exception:
                pass

        # Preference toggles
        elif btn_id and btn_id.startswith("pref-"):
            pref_key = btn_id.split("-", 1)[1]
            try:
                current = api.get_user_settings()
                cur_val = getattr(current, pref_key, None)
                if isinstance(cur_val, bool):
                    setattr(current, pref_key, not cur_val)
                    api.update_user_settings(current)
                    try:
                        new_check = "✅" if getattr(current, pref_key) else "⬜"
                        btn = event.button
                        label_parts = btn.label.split(" ", 2)
                        # keep everything after the checkbox
                        if len(label_parts) >= 3:
                            # label_parts[2] is the rest after two spaces
                            btn.label = f"  {new_check} {label_parts[2]}"
                        elif len(label_parts) == 2:
                            btn.label = f"  {new_check} {label_parts[1]}"
                    except Exception:
                        pass
            except Exception:
                try:
                    self.app.notify("Failed to update preference", severity="error")
                except Exception:
                    pass


class SettingsScreen(Container):
    def compose(self) -> ComposeResult:
        yield Sidebar(current="settings", id="sidebar")
        yield SettingsPanel(id="settings-panel")

    def on_mount(self) -> None:
        """When the SettingsScreen is mounted, ensure the settings panel is focused
        so vim navigation and scrolling behave like other screens."""
        try:
            panel = self.query_one("#settings-panel", SettingsPanel)
            # Initialize cursor and focus so j/k navigation works immediately
            try:
                panel.cursor_position = 0
            except Exception:
                pass
            try:
                panel.focus()
            except Exception:
                pass
        except Exception:
            pass

    def on_focus(self) -> None:
        """When screen receives focus, ensure the SettingsPanel is ready and focused."""
        try:
            panel = self.query_one("#settings-panel", SettingsPanel)
            try:
                panel.cursor_position = 0
            except Exception:
                pass
            try:
                panel.focus()
            except Exception:
                pass
        except Exception:
            pass


class ProfilePanel(VerticalScroll):
    cursor_position = reactive(0)

    def compose(self) -> ComposeResult:
        self.border_title = "Profile"
        user = api.get_current_user()
        settings = api.get_user_settings()

        yield Static("profile | @yourname | line 1", classes="panel-header")

        profile_container = Container(classes="profile-center-container")

        with profile_container:
            yield Static(settings.ascii_pic, classes="profile-avatar-large")
            username = get_username()
            if username is None:
                username = settings.username
            yield Static(f"@{username}", classes="profile-username-display")

            stats_row = Container(classes="profile-stats-row")
            with stats_row:
                yield Static(f"{user.posts_count}\nPosts", classes="profile-stat-item")
                yield Static(
                    f"{user.following}\nFollowing", classes="profile-stat-item"
                )
                yield Static(
                    f"{user.followers}\nFollowers", classes="profile-stat-item"
                )
            yield stats_row

            bio_container = Container(classes="profile-bio-container")
            bio_container.border_title = "Bio"
            with bio_container:
                yield Static(f"{settings.bio}", classes="profile-bio-display")
            yield bio_container

        yield profile_container
        yield Static(
            "\n[j/k] Navigate  [:e] Edit Profile  [Esc] Back",
            classes="help-text",
            markup=False,
        )

    def key_j(self) -> None:
        """Scroll down with j key"""
        if self.app.command_mode:
            return
        self.scroll_down()

    def key_k(self) -> None:
        """Scroll up with k key"""
        if self.app.command_mode:
            return
        self.scroll_up()

    def key_g(self) -> None:
        """Go to top with gg"""
        if self.app.command_mode:
            return
        pass  # Handled in on_key for double-press

    def key_G(self) -> None:
        """Go to bottom with G"""
        if self.app.command_mode:
            return
        self.scroll_end(animate=False)

    def key_ctrl_d(self) -> None:
        """Half page down"""
        self.scroll_page_down()

    def key_ctrl_u(self) -> None:
        """Half page up"""
        self.scroll_page_up()

    def on_key(self, event) -> None:
        """Handle g+g key combination for top and escape from input"""
        if event.key == "escape":
            # If message input has focus, unfocus it and return focus to chat
            try:
                msg_input = self.query_one("#message-input", Input)
                if msg_input.has_focus:
                    self.focus()
                    event.prevent_default()
                    event.stop()
                    return
            except Exception:
                pass
            # Otherwise prevent escape from unfocusing the chat view
            event.prevent_default()
            event.stop()
            return
        if event.key == "g":
            now = time.time()
            if hasattr(self, "last_g_time") and now - self.last_g_time < 0.5:
                self.scroll_home(animate=False)
                event.prevent_default()
                delattr(self, "last_g_time")
            else:
                self.last_g_time = now


class ProfileScreen(Container):
    def compose(self) -> ComposeResult:
        yield Sidebar(current="profile", id="sidebar")
        yield ProfilePanel(id="profile-panel")


class UserProfileViewPanel(VerticalScroll):
    """Panel for viewing another user's profile."""

    is_following = reactive(False)

    def __init__(self, username: str, **kwargs):
        super().__init__(**kwargs)
        self.username = username

    def compose(self) -> ComposeResult:
        self.border_title = f"@{self.username}"

        # Get user data from the dummy users or generate fake data
        user_data = self._get_user_data()

        yield Static(f"profile | @{self.username} | line 1", classes="panel-header")

        profile_container = Container(classes="profile-center-container")

        with profile_container:
            yield Static(user_data["ascii_pic"], classes="profile-avatar-large")
            yield Static(f"{user_data['display_name']}", classes="profile-name-large")
            yield Static(f"@{self.username}", classes="profile-username-display")

            stats_row = Container(classes="profile-stats-row")
            with stats_row:
                yield Static(
                    f"{user_data['posts_count']}\nPosts", classes="profile-stat-item"
                )
                yield Static(
                    f"{user_data['following']}\nFollowing", classes="profile-stat-item"
                )
                yield Static(
                    f"{user_data['followers']}\nFollowers", classes="profile-stat-item"
                )
            yield stats_row

            bio_container = Container(classes="profile-bio-container")
            bio_container.border_title = "Bio"
            with bio_container:
                yield Static(f"{user_data['bio']}", classes="profile-bio-display")
            yield bio_container

            # Action buttons
            buttons_container = Container(classes="profile-action-buttons")
            with buttons_container:
                follow_btn = Button(
                    "👥 Follow", id="follow-user-btn", classes="profile-action-btn"
                )
                yield follow_btn
                yield Button(
                    "💬 Message", id="message-user-btn", classes="profile-action-btn"
                )
            yield buttons_container

        yield profile_container

        # Recent posts section
        yield Static("\n→ Recent Posts", classes="section-header")
        posts = self._get_user_posts()
        for post in posts:
            yield PostItem(post, classes="post-item")

        yield Static(
            "\n[Esc] Back  [:f] Follow  [:m] Message", classes="help-text", markup=False
        )

    def _get_user_data(self) -> Dict:
        """Get or generate user data."""
        # Check if this is one of our dummy users
        try:
            discover_feed = self.app.query_one("#discover-feed", DiscoverFeed)

            for name, data in discover_feed._dummy_users.items():
                if data["username"] == self.username:
                    return {
                        "display_name": data["display_name"],
                        "bio": data["bio"],
                        "followers": data["followers"],
                        "following": data["following"],
                        "ascii_pic": data["ascii_pic"],
                        "posts_count": 42,  # Fake post count
                    }
        except:
            pass

        # Generate fake data for other users
        return {
            "display_name": self.username.replace("_", " ").title(),
            "bio": f"Hi! I'm {self.username}. Welcome to my profile! 👋",
            "followers": 156,
            "following": 89,
            "ascii_pic": "  [👀]\n  |◠ ◡ ◠|\n  |▓███▓|",
            "posts_count": 28,
        }

    def _get_user_posts(self) -> List:
        """Get fake posts from this user."""
        from .api_interface import Post

        # Generate 3 fake posts
        posts = []
        for i in range(3):
            post = Post(
                id=f"fake-{self.username}-{i}",
                author=self.username,
                content=f"This is a sample post from @{self.username}! Post #{i + 1}",
                timestamp=datetime.now(),
                likes=10 + i * 5,
                reposts=2 + i,
                comments=3 + i,
                liked_by_user=False,
                reposted_by_user=False,
            )
            posts.append(post)

        return posts

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        btn_id = event.button.id

        if btn_id == "follow-user-btn":
            # Toggle follow state
            self.is_following = not self.is_following

            # Update button text and styling
            try:
                follow_btn = self.query_one("#follow-user-btn", Button)
                if self.is_following:
                    follow_btn.label = "✓ Following"
                    follow_btn.add_class("following")
                    # Increment following count in user profile
                    current_user = api.get_current_user()
                    current_user.following += 1
                    self.app.notify(
                        f"✓ Following @{self.username}!", severity="success"
                    )
                else:
                    follow_btn.label = "👥 Follow"
                    follow_btn.remove_class("following")
                    # Decrement following count in user profile
                    current_user = api.get_current_user()
                    current_user.following -= 1
                    self.app.notify(f"Unfollowed @{self.username}", severity="info")
            except:
                pass
        elif btn_id == "message-user-btn":
            # Open DM with this user
            self.app.action_open_dm(self.username)


class UserProfileViewScreen(Container):
    """Screen for viewing another user's profile."""

    def __init__(self, username: str, **kwargs):
        super().__init__(**kwargs)
        self.username = username

    def compose(self) -> ComposeResult:
        yield Sidebar(current="discover", id="sidebar")
        yield UserProfileViewPanel(username=self.username, id="user-profile-panel")


class DraftsPanel(VerticalScroll):
    """Main panel for viewing all drafts."""

    cursor_position = reactive(0)
    selected_action = reactive("open")  # "open" or "delete"

    def compose(self) -> ComposeResult:
        self.border_title = "Drafts"
        drafts = load_drafts()

        yield Static(
            f"drafts.all | {len(drafts)} saved | line 1", classes="panel-header"
        )

        if not drafts:
            yield Static(
                "\n📝 No drafts saved yet\n\nPress :n to create a new post",
                classes="no-drafts-message",
            )
        else:
            # Show most recent first
            for i, draft in enumerate(reversed(drafts)):
                actual_index = len(drafts) - 1 - i
                box = self._create_draft_box(draft, actual_index)
                if i == 0:
                    box.add_class("vim-cursor")
                yield box

        yield Static(
            "\n[j/k] Navigate [h/l] Select Action [Enter] Execute [:o#/:x#] Direct [Esc] Back",
            classes="help-text",
            markup=False,
        )

    def on_mount(self) -> None:
        """Watch for cursor position changes"""
        self.watch(self, "cursor_position", self._update_cursor)
        self.watch(self, "selected_action", self._update_action_highlight)

    def _update_cursor(self) -> None:
        """Update the cursor position"""
        try:
            items = list(self.query(".draft-box"))
            for item in items:
                item.remove_class("vim-cursor")

            if 0 <= self.cursor_position < len(items):
                item = items[self.cursor_position]
                item.add_class("vim-cursor")
                self.scroll_to_widget(item)
                # Update action highlight for new position
                self._update_action_highlight()
        except Exception:
            pass

    def _update_action_highlight(self) -> None:
        """Update which action button is highlighted"""
        try:
            # Get all action buttons
            open_buttons = list(self.query(".draft-action-btn"))
            delete_buttons = list(self.query(".draft-action-btn-delete"))

            # Remove highlight from all buttons
            for btn in open_buttons + delete_buttons:
                btn.remove_class("action-selected")

            # Add highlight to selected button in current draft
            if 0 <= self.cursor_position < len(open_buttons):
                if self.selected_action == "open":
                    open_buttons[self.cursor_position].add_class("action-selected")
                else:
                    delete_buttons[self.cursor_position].add_class("action-selected")
        except Exception:
            pass

    def key_j(self) -> None:
        """Move down with j key"""
        if self.app.command_mode:
            return
        items = list(self.query(".draft-box"))
        if self.cursor_position < len(items) - 1:
            self.cursor_position += 1
            self.selected_action = "open"  # Reset to open when moving

    def key_k(self) -> None:
        """Move up with k key"""
        if self.app.command_mode:
            return
        if self.cursor_position > 0:
            self.cursor_position -= 1
            self.selected_action = "open"  # Reset to open when moving

    def key_g(self) -> None:
        """Go to top with gg"""
        if self.app.command_mode:
            return
        pass  # Handled in on_key for double-press

    def key_G(self) -> None:
        """Go to bottom with G"""
        if self.app.command_mode:
            return
        items = list(self.query(".draft-box"))
        self.cursor_position = len(items) - 1

    def key_ctrl_d(self) -> None:
        """Half page down"""
        if self.app.command_mode:
            return
        items = list(self.query(".draft-box"))
        self.cursor_position = min(self.cursor_position + 5, len(items) - 1)

    def key_ctrl_u(self) -> None:
        """Half page up"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 5, 0)

    def key_w(self) -> None:
        """Word forward - move down by 3"""
        if self.app.command_mode:
            return
        items = list(self.query(".draft-box"))
        self.cursor_position = min(self.cursor_position + 3, len(items) - 1)

    def key_b(self) -> None:
        """Word backward - move up by 3"""
        if self.app.command_mode:
            return
        self.cursor_position = max(self.cursor_position - 3, 0)

    def key_h(self) -> None:
        """Select 'open' action with h key"""
        if self.app.command_mode:
            return
        self.selected_action = "open"

    def key_l(self) -> None:
        """Select 'delete' action with l key"""
        if self.app.command_mode:
            return
        self.selected_action = "delete"

    def on_key(self, event) -> None:
        """Handle g+g key combination for top, enter for actions, and escape for command mode"""
        if event.key == "escape":
            # If in command mode, let the app handle it (don't stop propagation)
            if self.app.command_mode:
                # Don't prevent or stop - let it bubble up to app's on_key
                return
            # Otherwise prevent escape from unfocusing the drafts panel
            event.prevent_default()
            event.stop()
            return
        if event.key == "enter":
            if self.app.command_mode:
                return
            event.prevent_default()
            event.stop()
            try:
                drafts = load_drafts()
                if 0 <= self.cursor_position < len(drafts):
                    actual_index = len(drafts) - 1 - self.cursor_position
                    if self.selected_action == "open":
                        self.app.action_open_draft(actual_index)
                    else:
                        self.app.push_screen(DeleteDraftDialog(actual_index))
            except Exception:
                pass
            return
        if event.key == "g":
            now = time.time()
            if hasattr(self, "last_g_time") and now - self.last_g_time < 0.5:
                self.cursor_position = 0
                event.prevent_default()
                delattr(self, "last_g_time")
            else:
                self.last_g_time = now

    def _create_draft_box(self, draft: Dict, index: int) -> Container:
        """Create a nice box for displaying a draft."""
        box = Container(classes="draft-box")
        box.border = "round"
        box.border_title = f"💾 Draft {index + 1}"

        # Header with timestamp
        time_ago = format_time_ago(draft["timestamp"])
        box.mount(Static(f"⏰ Saved {time_ago}", classes="draft-timestamp"))

        # Content preview
        content = draft["content"]
        preview = content if len(content) <= 200 else content[:200] + "..."
        box.mount(Static(preview, classes="draft-content-preview"))

        # Attachments info
        attachments = draft.get("attachments", [])
        if attachments:
            attach_text = f"📎 {len(attachments)} attachment(s)"
            box.mount(Static(attach_text, classes="draft-attachments-info"))

        # Action buttons
        actions_container = Container(classes="draft-actions")
        actions_container.mount(
            Button(f"✏️ Open", id=f"open-draft-{index}", classes="draft-action-btn")
        )
        actions_container.mount(
            Button(
                f"🗑️ Delete",
                id=f"delete-draft-{index}",
                classes="draft-action-btn-delete",
            )
        )
        box.mount(actions_container)

        return box

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle draft action buttons."""
        btn_id = event.button.id

        if btn_id and btn_id.startswith("open-draft-"):
            index = int(btn_id.split("-")[-1])
            self.app.action_open_draft(index)
        elif btn_id and btn_id.startswith("delete-draft-"):
            index = int(btn_id.split("-")[-1])
            self.app.push_screen(DeleteDraftDialog(index))

    def on_drafts_updated(self, message: DraftsUpdated) -> None:
        """Handle drafts updated message - refresh the panel."""
        # Remove all children and re-compose
        self.remove_children()
        drafts = load_drafts()

        self.mount(
            Static(f"drafts.all | {len(drafts)} saved | line 1", classes="panel-header")
        )

        if not drafts:
            self.mount(
                Static(
                    "\n📝 No drafts saved yet\n\nPress :n to create a new post",
                    classes="no-drafts-message",
                )
            )
        else:
            # Show most recent first
            for i, draft in enumerate(reversed(drafts)):
                actual_index = len(drafts) - 1 - i
                box = self._create_draft_box(draft, actual_index)
                if i == 0:
                    box.add_class("vim-cursor")
                self.mount(box)

        self.mount(
            Static(
                "\n[j/k] Navigate [h/l] Select Action [Enter] Execute [:o#/:x#] Direct [Esc] Back",
                classes="help-text",
                markup=False,
            )
        )

        # Reset cursor position
        self.cursor_position = 0


class DraftsScreen(Container):
    """Screen for viewing and managing all drafts."""

    def compose(self) -> ComposeResult:
        yield Sidebar(current="drafts", id="sidebar")
        yield DraftsPanel(id="drafts-panel")


class Proj101App(App):
    CSS_PATH = "main.tcss"

    # Disable dark mode toggle - we use our own colors
    ENABLE_COMMAND_PALETTE = False

    # Use MODES for seamless screen transitions
    # Modes automatically handle initial screen display
    MODES = {"auth": AuthScreen, "main": MainUIScreen}

    BINDINGS = [
        # Basic app controls
        Binding("q", "quit", "Quit", show=False),
        Binding("i", "insert_mode", "Insert", show=True),
        Binding("escape", "normal_mode", "Normal", show=False),
        # Screen navigation
        Binding("0", "focus_main_content", "Main Content", show=False),
        Binding("1", "show_timeline", "Timeline", show=False),
        Binding("2", "show_discover", "Discover", show=False),
        Binding("3", "show_notifications", "Notifications", show=False),
        Binding("4", "show_messages", "Messages", show=False),
        Binding("5", "show_settings", "Settings", show=False),
        Binding("p", "show_profile", "Profile", show=False),
        Binding("d", "show_drafts", "Drafts", show=False),
        Binding("6", "focus_messages", "Messages List", show=False),
        Binding("shift+n", "focus_navigation", "Nav Focus", show=False),
        Binding("colon", "show_command_bar", "Command", show=False),
        # Vim-style navigation bindings
        Binding("j", "vim_down", "Down", show=False),
        Binding("k", "vim_up", "Up", show=False),
        Binding("h", "vim_left", "Left", show=False),
        Binding("l", "vim_right", "Right", show=False),
        Binding("w", "vim_word_forward", "Word Forward", show=False),
        Binding("b", "vim_word_backward", "Word Backward", show=False),
        Binding("G", "vim_bottom", "Bottom", show=False),
        Binding("ctrl+d", "vim_half_page_down", "Half Page Down", show=False),
        Binding("ctrl+u", "vim_half_page_up", "Half Page Up", show=False),
        Binding("ctrl+f", "vim_page_down", "Page Down", show=False),
        Binding("ctrl+b", "vim_page_up", "Page Up", show=False),
        Binding("$", "vim_line_end", "End of Line", show=False),
        Binding("^", "vim_line_start", "Start of Line", show=False),
    ]

    current_screen_name = reactive("timeline")
    command_mode = reactive(False)
    command_text = reactive("")
    _switching = False  # Flag to prevent concurrent screen switches

    def watch_command_text(self, new_text: str) -> None:
        """Update command bar whenever command_text changes"""
        try:
            command_bar = self.query_one("#command-bar", Static)
            command_bar.update(new_text)
        except:
            pass

    def show_main_app(self, credentials=None) -> None:
        """Transition to authenticated main UI screen.

        This method is safe to call from threads - it schedules the mode switch
        on the main thread using call_later.

        Args:
            credentials: Optional dict with 'username' and 'tokens' from authenticate().
                        If not provided, will read from disk (slower, may have timing issues).
        """
        try:
            # Use provided credentials or load from disk
            username = "yourname"
            try:
                if credentials and isinstance(credentials, dict):
                    # Use credentials passed directly from authenticate() - faster and avoids file I/O
                    # NOTE: Token and handle should already be set in the worker thread before this is called
                    username = credentials.get("username") or "yourname"
                    tokens = credentials.get("tokens")
                    # Require access_token explicitly (do not accept id_token)
                    if tokens and isinstance(tokens, dict) and "access_token" in tokens:
                        # Double-check token is set (should already be set in worker thread)
                        if not api.token:
                            api.set_token(tokens["access_token"])
                else:
                    # Fallback: read from disk
                    from .auth import get_stored_credentials

                    creds = get_stored_credentials()
                    if creds and isinstance(creds, dict):
                        username = creds.get("username") or "yourname"
                        tokens = creds.get("tokens")
                        # Require access_token from stored tokens
                        if (
                            tokens
                            and isinstance(tokens, dict)
                            and "access_token" in tokens
                        ):
                            api.set_token(tokens["access_token"])

                # Ensure API handle is set (should already be set in worker thread for first login)
                if not api.handle or api.handle == "yourname":
                    api.handle = username

                # Verify user exists in DB (should already be done in worker thread)
                try:
                    user_profile = api.get_current_user()
                except Exception:
                    pass
            except Exception:
                pass

            # Directly switch mode - thread safety handled by call_from_thread wrapper
            try:
                self.switch_mode("main")

                # Force the screen to update by triggering a layout refresh
                try:
                    current_screen = self.screen
                    # Force a refresh
                    current_screen.refresh(layout=True)
                    self.refresh(layout=True)
                except Exception:
                    pass

                # Final refresh to ensure the UI updates
                try:
                    self.refresh()
                except Exception:
                    pass

                # Ensure the initial content is focused (timeline feed) so vim navigation works immediately
                try:
                    # Schedule focusing after layout settles
                    self.call_after_refresh(self._focus_initial_content)
                except Exception:
                    pass

            except Exception:
                pass

        except Exception:
            pass

    def show_auth_screen(self) -> None:
        """Transition to unauthenticated auth screen."""
        try:
            self.log_auth_event("show_auth_screen: Switching to auth mode")

            # Clear API state
            api.session.headers.pop("Authorization", None)
            api.handle = "yourname"

            # Switch to the auth mode
            self.switch_mode("auth")
            self.log_auth_event("show_auth_screen: ✓ Switched to auth mode")
        except Exception as e:
            self.log_auth_event(f"show_auth_screen: ERROR - {e}")

    def ensure_auth_overlay(self) -> None:
        """Alias for show_auth_screen - used by sign-out."""
        self.show_auth_screen()

    def log_auth_event(self, msg: str) -> None:
        """Write a short auth-lifecycle message to the in-TUI RichLog if present,
        otherwise fall back to the standard logging facility.

        This is intentionally lightweight and tolerant of any failures so it
        doesn't interfere with the auth flow.
        """
        if os.getenv("TUITTER_DEBUG"):
            try:
                rl = self.query_one("#auth-log", RichLog)
                rl.write(msg)
                return
            except Exception:
                pass
        # Fallback to module logging
        try:
            logging.getLogger("tuitter.auth").info(msg)
        except Exception:
            pass

    def on_authentication_completed(self, message: AuthenticationCompleted) -> None:
        """App-level handler for successful authentication to ensure UI transitions.

        Some environments dispatch messages to the App rather than the Screen; having
        this here ensures we always transition to the main app when auth succeeds.

        NOTE: We don't call show_main_app() here anymore because the worker thread
        handles it directly with the correct credentials to avoid race conditions.
        """
        try:
            # Resolve username once (prefer the message payload, then keyring, then a default)
            username = (
                (message.username if getattr(message, "username", None) else None)
                or get_username()
                or "yourname"
            )
            # If header exists, update it
            try:
                hdr = self.query_one("#app-header", Static)
                hdr.update(f"tuitter [timeline] @{username}")
            except Exception:
                pass
            # NOTE: Don't call show_main_app() here - the worker thread already did it with credentials
        except Exception:
            pass

    def on_mount(self) -> None:
        """App startup - decide which mode to show based on stored credentials."""
        import sys

        try:
            self.log_auth_event("App.on_mount CALLED")
        except Exception:
            pass
        try:
            # First, attempt a proactive restore using the API helper which
            # will attempt refresh if a refresh token is present. This avoids
            # composing UI with an expired token and prevents 401s from
            # bubbling into Textual lifecycle methods.
            restored = False
            # Try a few quick attempts to restore session to avoid races with
            # another process writing the fallback token file (small window at startup).

            # Clock to limit total restore time, and try to restore during that range
            allow_restore_time = 2.0  # seconds
            start_time = time.time()
            while time.time() - start_time < allow_restore_time:
                try:
                    restored = api.try_restore_session()
                except Exception as e:
                    try:
                        self.log_auth_event(f"try_restore_session error: {e}")
                    except Exception:
                        pass
                if restored:
                    break
                # small backoff between attempts
                try:
                    time.sleep(0.1)
                except Exception:
                    pass

            if restored:
                try:
                    self.log_auth_event(
                        "Session successfully restored; switching to main mode"
                    )
                except Exception:
                    pass
                # Ensure handle is set (may be persisted in keyring by auth flow)
                try:
                    api.handle = get_username() or api.handle
                except Exception:
                    pass

                self.switch_mode("main")
                self.log_auth_event("on_mount: Switched to main mode")
                return

            # If restore failed, fall back to showing the auth screen
            try:
                self.log_auth_event("No session to restore; switching to AUTH mode")
            except Exception:
                pass
            self.switch_mode("auth")
            self.log_auth_event("on_mount: Switched to auth mode")

        except Exception as e:
            # On error, show auth screen
            try:
                self.log_auth_event(f"on_mount: ERROR - {e}, showing auth")
            except Exception:
                pass
            self.switch_mode("auth")

    def _focus_initial_content(self) -> None:
        """Helper to focus the timeline feed after initial render"""
        try:
            timeline_feed = self.query_one("#timeline-feed", TimelineFeed)
            timeline_feed.add_class("vim-mode-active")
            timeline_feed.focus()
            # Ensure the first post has the cursor
            timeline_feed.cursor_position = 0
        except Exception:
            pass

    def switch_screen(self, screen_name: str, **kwargs):
        # Prevent concurrent screen switches
        if self._switching:
            return
        if screen_name == self.current_screen_name and not kwargs:
            return
        screen_map = {
            "timeline": (
                TimelineScreen,
                "[1-5] Screens [p] Profile [d] Drafts [j/k] Navigate [:n] New Post [:q] Quit",
            ),
            "discover": (
                DiscoverScreen,
                "[1-5] Screens [p] Profile [d] Drafts [j/k] Navigate [/] Search [:n] New Post [:q] Quit",
            ),
            "notifications": (
                NotificationsScreen,
                "[1-5] Screens [p] Profile [d] Drafts [j/k] Navigate [:q] Quit",
            ),
            "messages": (
                MessagesScreen,
                "[0] Chat [6] Messages [1-5] Screens [p] Profile [d] Drafts [j/k] Navigate [:n] New Message [:q] Quit",
            ),
            "profile": (
                ProfileScreen,
                "[1-5] Screens [d] Drafts [j/k] Navigate [:q] Quit",
            ),
            "settings": (
                SettingsScreen,
                "[1-5] Screens [p] Profile [d] Drafts [j/k] Navigate [:q] Quit",
            ),
            "drafts": (
                DraftsScreen,
                "[1-5] Screens [p] Profile [j/k] Navigate [h/l] Select [Enter] Execute [:q] Quit",
            ),
            "user_profile": (
                UserProfileViewScreen,
                "[1-5] Screens [p] Profile [d] Drafts [:m] Message [:q] Quit",
            ),
        }
        if screen_name in screen_map:
            self._switching = True  # Set flag to prevent concurrent switches
            current_screen = self.screen

            for container in current_screen.query("#screen-container"):
                container.remove()
            ScreenClass, footer_text = screen_map[screen_name]

            def mount_new_screen():
                current_screen.mount(ScreenClass(id="screen-container", **kwargs))
            
            self.call_after_refresh(mount_new_screen)

            def update_ui():
                try:
                    header = current_screen.query_one("#app-header", Static)
                    if screen_name == "user_profile" and "username" in kwargs:
                        header.update(f"tuitter [@{kwargs['username']}] @yourname")
                    elif screen_name == "messages" and "username" in kwargs:
                        header.update(f"tuitter [dm:@{kwargs['username']}] @yourname")
                    else:
                        header.update(f"tuitter [{screen_name}] @yourname")
                except Exception:
                    pass

                # Update footer
                try:
                    current_screen.query_one("#app-footer", Static).update(footer_text)
                except Exception:
                    pass

                # Update top navbar
                try:
                    current_screen.query_one("#top-navbar", TopNav).update_active(screen_name)
                except Exception:
                    pass

                # Update sidebar (if it exists)
                try:
                    sidebar = current_screen.query_one("#sidebar", Sidebar)
                    # For user profile view, highlight discover in sidebar
                    if screen_name == "user_profile":
                        sidebar.update_active("discover")
                    elif screen_name == "messages":
                        sidebar.update_active("messages")
                    else:
                        sidebar.update_active(screen_name)
                except Exception:
                    pass
                
                self.current_screen_name = screen_name
                
                # Focus the main content area after screen switch
                self._focus_main_content_for_screen(screen_name)

            self.call_after_refresh(update_ui)

            self.set_timer(0.1, lambda: setattr(self, "_switching", False))

    def _focus_main_content_for_screen(self, screen_name: str) -> None:
        """Focus the main content feed/panel for the current screen"""
        try:
            # Map screen names to their main content widget IDs
            content_map = {
                "timeline": "#timeline-feed",
                "discover": "#discover-feed",
                "notifications": "#notifications-feed",
                "messages": "#chat",
                "profile": "#profile-panel",
                "settings": "#settings-panel",
                "drafts": "#drafts-panel",
                "user_profile": "#user-profile-panel",
            }

            if screen_name in content_map:
                widget_id = content_map[screen_name]
                widget = self.query_one(widget_id)
                widget.focus()

                # Reset cursor position to 0 for feeds with cursor navigation
                if hasattr(widget, "cursor_position"):
                    widget.cursor_position = 0
        except Exception:
            pass

    def action_quit(self) -> None:
        # Clean up OAuth server if on auth screen
        try:
            auth_screen = self.query_one(AuthScreen)
            auth_screen._cleanup_oauth_server()
        except Exception:
            pass
        self.exit()

    def action_insert_mode(self) -> None:
        try:
            self.query_one("#message-input", Input).focus()
        except Exception:
            pass

    def action_normal_mode(self) -> None:
        self.screen.focus_next()

    def action_show_timeline(self) -> None:
        self.switch_screen("timeline")

    def action_show_discover(self) -> None:
        self.switch_screen("discover")

    def action_show_notifications(self) -> None:
        self.switch_screen("notifications")

    def action_show_messages(self) -> None:
        self.switch_screen("messages")

    def action_show_settings(self) -> None:
        self.switch_screen("settings")

    def action_show_profile(self) -> None:
        """Show the user's own profile screen."""
        self.switch_screen("profile")

    def action_show_drafts(self) -> None:
        """Show the drafts screen."""
        self.switch_screen("drafts")

    def action_view_user_profile(self, username: str) -> None:
        """View another user's profile."""
        self.switch_screen("user_profile", username=username)

    def action_open_dm(self, username: str) -> None:
        """Open a DM with a specific user."""
        try:
            self.notify(f"💬 Opening chat with @{username}...", severity="info")
        except:
            pass

        # Switch to messages screen with this specific user
        self.switch_screen("messages", username=username)

        # Focus will be set in MessagesScreen.on_mount()

    def action_focus_navigation(self) -> None:
        try:
            topnav = self.query_one("#top-navbar", TopNav)
            # Prefer direct attribute if TopNav exposed its Tabs instance
            tabs = getattr(topnav, "tabs", None)
            if tabs is None:
                tabs = topnav.query_one("#top-tabs", Tabs)
            tabs.focus()
        except Exception:
            pass

    def action_focus_main_content(self) -> None:
        """Focus the main content area when pressing 0"""
        try:
            target_id = None
            if self.current_screen_name == "timeline":
                target_id = "#timeline-feed"
            elif self.current_screen_name == "discover":
                target_id = "#discover-feed"
            elif self.current_screen_name == "notifications":
                target_id = "#notifications-feed"
            elif self.current_screen_name == "messages":
                target_id = "#chat"
            elif self.current_screen_name == "settings":
                target_id = "#settings-panel"
            elif self.current_screen_name == "profile":
                target_id = "#profile-panel"
            elif self.current_screen_name == "drafts":
                target_id = "#drafts-panel"
            elif self.current_screen_name == "user_profile":
                target_id = "#user-profile-panel"

            if target_id:
                panel = self.query_one(target_id)
                panel.add_class("vim-mode-active")
                panel.focus()

        except Exception:
            pass

    def action_focus_messages(self) -> None:
        """Focus the messages list when pressing 6"""
        try:
            if self.current_screen_name == "messages":
                conversations = self.query_one("#conversations", ConversationsList)
                conversations.border_title = "[6] Messages"
                conversations.add_class("vim-mode-active")
                conversations.focus()
        except Exception:
            pass

    # Vim-style navigation actions - these forward to focused widget
    def action_vim_down(self) -> None:
        """Move down (j key)"""
        # The key will be handled by the focused widget's key_j method if it exists
        pass

    def action_vim_up(self) -> None:
        """Move up (k key)"""
        # The key will be handled by the focused widget's key_k method if it exists
        pass

    def action_vim_left(self) -> None:
        """Move left (h key)"""
        # The key will be handled by the focused widget's key_h method if it exists
        pass

    def action_vim_right(self) -> None:
        """Move right (l key)"""
        # The key will be handled by the focused widget's key_l method if it exists
        pass

    def action_vim_word_forward(self) -> None:
        """Move forward one word (w key)"""
        # The key will be handled by the focused widget's key_w method if it exists
        pass

    def action_vim_word_backward(self) -> None:
        """Move backward one word (b key)"""
        # The key will be handled by the focused widget's key_b method if it exists
        pass

    def action_vim_top(self) -> None:
        """Move to the top (gg key)"""
        # This is handled by the on_key method for the double-g press
        pass

    def action_vim_bottom(self) -> None:
        """Move to the bottom (G key)"""
        focused = self.focused
        if focused and hasattr(focused, "key_G"):
            focused.key_G()

    def action_vim_half_page_down(self) -> None:
        """Move half page down (Ctrl+d)"""
        # The key will be handled by the focused widget's key_ctrl_d method if it exists
        pass

    def action_vim_half_page_up(self) -> None:
        """Move half page up (Ctrl+u)"""
        # The key will be handled by the focused widget's key_ctrl_u method if it exists
        pass

    def action_vim_page_down(self) -> None:
        """Move one page down (Ctrl+f)"""
        # The key will be handled by the focused widget's key_ctrl_f method if it exists
        pass

    def action_vim_page_up(self) -> None:
        """Move one page up (Ctrl+b)"""
        # The key will be handled by the focused widget's key_ctrl_b method if it exists
        pass

    def action_vim_line_start(self) -> None:
        """Go to start of line (^ key)"""
        # Will be implemented in the content panels
        pass

    def action_vim_line_end(self) -> None:
        """Go to end of line ($ key)"""
        # Will be implemented in the content panels
        pass

    def action_show_command_bar(self) -> None:
        try:
            command_bar = self.query_one("#command-bar", Static)
            command_bar.styles.display = "block"
            self.command_text = ":"
            self.command_mode = True
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        # Don't interfere with command input typing
        pass

    def action_new_post(self) -> None:
        """Show the new post dialog."""

        def check_refresh(result):
            if result:
                if self.current_screen_name == "timeline":
                    self.switch_screen("timeline")

        self.push_screen(NewPostDialog(), check_refresh)

    def action_open_draft(self, draft_index: int) -> None:
        """Open a draft in the new post dialog."""
        try:
            drafts = load_drafts()
            if 0 <= draft_index < len(drafts):
                draft = drafts[draft_index]

                def check_refresh(result):
                    if result:
                        # Post was published, delete the draft
                        delete_draft(draft_index)
                        try:
                            # Post message to refresh drafts everywhere
                            self.post_message(DraftsUpdated())
                        except:
                            pass
                        if self.current_screen_name == "timeline":
                            self.switch_screen("timeline")
                        elif self.current_screen_name == "drafts":
                            self.switch_screen("drafts")
                    else:
                        # Dialog was closed without posting, refresh drafts in case it was saved
                        try:
                            # Post message to refresh drafts everywhere
                            self.post_message(DraftsUpdated())
                        except:
                            pass
                        # Refresh drafts screen if we're on it
                        if self.current_screen_name == "drafts":
                            self.switch_screen("drafts")

                self.push_screen(
                    NewPostDialog(
                        draft_content=draft["content"],
                        draft_attachments=draft.get("attachments", []),
                    ),
                    check_refresh,
                )
            else:
                self.notify("Draft not found", severity="error")
        except Exception as e:
            self.notify(f"Error opening draft: {str(e)}", severity="error")

    def on_key(self, event) -> None:
        if self.command_mode:
            # CRITICAL: Stop event propagation IMMEDIATELY when in command mode
            event.prevent_default()
            event.stop()

            if event.key == "escape":
                try:
                    command_bar = self.query_one("#command-bar", Static)
                    command_bar.styles.display = "none"
                except:
                    pass
                self.command_text = ""
                self.command_mode = False
            elif event.key == "enter":
                command = self.command_text.strip()
                try:
                    command_bar = self.query_one("#command-bar", Static)
                    command_bar.styles.display = "none"
                except:
                    pass
                self.command_mode = False

                # Process command
                if command.startswith(":"):
                    command = command[1:]
                elif command.startswith("/"):
                    command = command[1:]

                screen_map = {
                    "1": "timeline",
                    "2": "discover",
                    "3": "notifications",
                    "4": "messages",
                    "5": "settings",
                }
                if command in screen_map:
                    self.switch_screen(screen_map[command])
                elif command in ("q", "quit"):
                    self.exit()
                elif command.upper() == "P":
                    self.switch_screen("profile")
                elif command == "n":
                    # Open dialog to prompt for a username to message
                    try:

                        def _after(result):
                            # result is the username string on success, False/None otherwise
                            try:
                                if result:
                                    # Switch to messages with that username (action_open_dm handles notification)
                                    self.action_open_dm(result)
                            except Exception:
                                pass

                        self.push_screen(NewMessageDialog(), _after)
                    except Exception:
                        # Fallback: focus message input
                        try:
                            msg_input = self.query_one("#message-input", Input)
                            msg_input.focus()
                        except:
                            pass
                    # Don't do anything for other screens (like drafts)
                elif command.upper() == "D":
                    self.action_show_drafts()
                elif command == "l":
                    # Like the currently focused post in timeline or discover
                    if self.current_screen_name == "timeline":
                        try:
                            timeline_feed = self.query_one("#timeline-feed")
                            items = list(timeline_feed.query(".post-item"))
                            idx = getattr(timeline_feed, "cursor_position", 0)
                            if 0 <= idx < len(items):
                                post_item = items[idx]
                                post = getattr(post_item, "post", None)
                                if post:
                                    try:
                                        currently_liked = bool(
                                            getattr(post_item, "liked_by_user", False)
                                            or getattr(post, "liked_by_user", False)
                                        )
                                        if currently_liked:
                                            # Unlike
                                            try:
                                                api.unlike_post(post.id)
                                            except Exception:
                                                logging.exception(
                                                    "api.unlike_post failed"
                                                )
                                            try:
                                                post_item.liked_by_user = False
                                            except Exception:
                                                pass
                                            self.notify(
                                                "Post unliked!", severity="success"
                                            )
                                        else:
                                            try:
                                                api.like_post(post.id)
                                            except Exception:
                                                logging.exception(
                                                    "api.like_post failed"
                                                )
                                            try:
                                                post_item.liked_by_user = True
                                            except Exception:
                                                pass
                                            self.notify(
                                                "Post liked!", severity="success"
                                            )
                                    except Exception:
                                        logging.exception("Error toggling like")
                        except Exception:
                            pass
                    elif self.current_screen_name == "discover":
                        try:
                            discover_feed = self.query_one("#discover-feed")
                            items = list(discover_feed.query(".post-item"))
                            idx = getattr(discover_feed, "cursor_position", 0)
                            if 0 <= idx < len(items):
                                post_item = items[idx]
                                post = getattr(post_item, "post", None)
                                if post:
                                    try:
                                        currently_liked = bool(
                                            getattr(post_item, "liked_by_user", False)
                                            or getattr(post, "liked_by_user", False)
                                        )
                                        if currently_liked:
                                            try:
                                                api.unlike_post(post.id)
                                            except Exception:
                                                logging.exception(
                                                    "api.unlike_post failed"
                                                )
                                            try:
                                                post_item.liked_by_user = False
                                            except Exception:
                                                pass
                                            self.notify(
                                                "Post unliked!", severity="success"
                                            )
                                        else:
                                            try:
                                                api.like_post(post.id)
                                            except Exception:
                                                logging.exception(
                                                    "api.like_post failed"
                                                )
                                            try:
                                                post_item.liked_by_user = True
                                            except Exception:
                                                pass
                                            self.notify(
                                                "Post liked!", severity="success"
                                            )
                                    except Exception:
                                        logging.exception("Error toggling like")
                        except Exception:
                            pass
                elif command == "c":
                    logging.debug(":c command received in Proj101App.on_key")
                    # Open comment screen for the currently focused post in timeline or discover
                    if self.current_screen_name == "timeline":
                        try:
                            timeline_feed = self.query_one("#timeline-feed")
                            items = list(timeline_feed.query(".post-item"))
                            idx = getattr(timeline_feed, "cursor_position", 0)
                            logging.debug(
                                f"timeline_feed.cursor_position={idx}, items={len(items)}"
                            )
                            if 0 <= idx < len(items):
                                post_item = items[idx]
                                post = getattr(post_item, "post", None)
                                logging.debug(
                                    f"Opening comment screen for post id={getattr(post, 'id', None)} author={getattr(post, 'author', None)}"
                                )
                                if post:
                                    self.push_screen(CommentScreen(post))
                            else:
                                logging.debug("Invalid cursor position for :c command")
                        except Exception as e:
                            logging.exception("Exception in :c command:")
                    elif self.current_screen_name == "discover":
                        try:
                            discover_feed = self.query_one("#discover-feed")
                            items = list(discover_feed.query(".post-item"))
                            idx = getattr(discover_feed, "cursor_position", 0)
                            logging.debug(
                                f"discover_feed.cursor_position={idx}, items={len(items)}"
                            )
                            if 0 <= idx < len(items):
                                post_item = items[idx]
                                post = getattr(post_item, "post", None)
                                logging.debug(
                                    f"Opening comment screen for post id={getattr(post, 'id', None)} author={getattr(post, 'author', None)}"
                                )
                                if post:
                                    self.push_screen(CommentScreen(post))
                            else:
                                logging.debug("Invalid cursor position for :c command")
                        except Exception as e:
                            logging.exception("Exception in :c command:")
                elif command == "rt":
                    # Repost the currently focused post in timeline or discover
                    if self.current_screen_name == "timeline":
                        try:
                            timeline_feed = self.query_one("#timeline-feed")
                            items = list(timeline_feed.query(".post-item"))
                            idx = getattr(timeline_feed, "cursor_position", 0)
                            if 0 <= idx < len(items):
                                post_item = items[idx]
                                post = getattr(post_item, "post", None)
                                if post:
                                    try:
                                        currently_reposted = bool(
                                            getattr(
                                                post_item, "reposted_by_user", False
                                            )
                                            or getattr(post, "reposted_by_user", False)
                                        )
                                        if currently_reposted:
                                            try:
                                                api.unrepost(post.id)
                                            except Exception:
                                                logging.exception("api.unrepost failed")
                                            try:
                                                post_item.reposted_by_user = False
                                            except Exception:
                                                pass
                                            self.notify(
                                                "Post unreposted!", severity="success"
                                            )
                                        else:
                                            try:
                                                api.repost(post.id)
                                            except Exception:
                                                logging.exception("api.repost failed")
                                            try:
                                                post_item.reposted_by_user = True
                                            except Exception:
                                                pass
                                            # Also insert a reposted copy at the top of the timeline for visibility
                                            from copy import deepcopy

                                            repost_copy = deepcopy(post)
                                            repost_copy.timestamp = datetime.now()
                                            timeline_feed.reposted_posts = [
                                                (repost_copy, repost_copy.timestamp)
                                            ] + [
                                                p
                                                for p in getattr(
                                                    timeline_feed, "reposted_posts", []
                                                )
                                            ]
                                            self.notify(
                                                "Post reposted!", severity="success"
                                            )
                                    except Exception:
                                        logging.exception("Error toggling repost")
                        except Exception:
                            pass
                    elif self.current_screen_name == "discover":
                        try:
                            discover_feed = self.query_one("#discover-feed")
                            items = list(discover_feed.query(".post-item"))
                            idx = getattr(discover_feed, "cursor_position", 0)
                            if 0 <= idx < len(items):
                                post_item = items[idx]
                                post = getattr(post_item, "post", None)
                                if post:
                                    try:
                                        currently_reposted = bool(
                                            getattr(
                                                post_item, "reposted_by_user", False
                                            )
                                            or getattr(post, "reposted_by_user", False)
                                        )
                                        if currently_reposted:
                                            try:
                                                api.unrepost(post.id)
                                            except Exception:
                                                logging.exception("api.unrepost failed")
                                            try:
                                                post_item.reposted_by_user = False
                                            except Exception:
                                                pass
                                            self.notify(
                                                "Post unreposted!", severity="success"
                                            )
                                        else:
                                            try:
                                                api.repost(post.id)
                                            except Exception:
                                                logging.exception("api.repost failed")
                                            try:
                                                post_item.reposted_by_user = True
                                            except Exception:
                                                pass
                                            self.notify(
                                                "Post reposted!", severity="success"
                                            )
                                    except Exception:
                                        logging.exception("Error toggling repost")
                        except Exception:
                            pass
                elif command.startswith("o") and len(command) > 1:
                    try:
                        draft_number = int(command[1:])  # User enters 1-indexed
                        draft_index = draft_number - 1  # Convert to 0-indexed for array
                        self.action_open_draft(draft_index)
                    except:
                        pass
                elif command.startswith("x") and len(command) > 1:
                    try:
                        draft_number = int(command[1:])  # User enters 1-indexed
                        draft_index = draft_number - 1  # Convert to 0-indexed for array
                        self.push_screen(DeleteDraftDialog(draft_index))
                    except:
                        pass

                self.command_text = ""
            elif event.key == "backspace":
                if len(self.command_text) > 1:
                    self.command_text = self.command_text[:-1]
            elif len(event.key) == 1 and event.key.isprintable():
                self.command_text += event.key
            # All other keys are already stopped at the top of command_mode block
            return


def main():
    logging.debug("inside __main__ guard, about to run app")
    try:
        Proj101App().run()
    except Exception as e:
        import traceback

        logging.exception("Exception occurred while running Proj101App:")


if __name__ == "__main__":
    pid_file = Path(".main_app_pid")
    pid_file.write_text(str(os.getpid()))
    try:
        app = Proj101App()
        app.run()
    finally:
        try:
            pid_file.unlink()
        except Exception:
            pass
