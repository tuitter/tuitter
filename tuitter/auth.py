"""
Simplified authentication module using system keyring and dynamic port allocation.
Handles OAuth flow securely and manages token storage.
"""
import http.server
import socketserver
import webbrowser
import threading
import requests
import keyring
from .auth_storage import save_tokens_full, load_tokens, clear_tokens
import json
import sys
import logging
import os
import platform
from pathlib import Path
from urllib.parse import urlencode, parse_qs, urlparse
import socket
from typing import Dict, Optional
import time

# OAuth configuration constants
COGNITO_DOMAIN = "https://us-east-2xzzmuowl9.auth.us-east-2.amazoncognito.com"
COGNITO_AUTH_URL = f"{COGNITO_DOMAIN}/login"
COGNITO_TOKEN_URL = f"{COGNITO_DOMAIN}/oauth2/token"
COGNITO_USERINFO_URL = f"{COGNITO_DOMAIN}/oauth2/userInfo"
CLIENT_ID = "7109b3p9beveapsmr806freqnn"
CLIENT_SECRET = "1t46ik23730a5fbboiimdbh8ffkicnm69c40ifbg9jou401pft02"
REDIRECT_PORT = 5173  # Fixed redirect port as configured in Cognito
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SERVICE_NAME = "tuitter"  # Keyring service name
SCOPES = ["email", "openid", "phone"]
FALLBACK_TOKEN_FILE = Path.home() / ".tuitter_tokens.json"

class AuthError(Exception):
    """Authentication related errors"""
    pass

def _make_handler(auth_event, auth_response):
    """Return a handler class bound to the given event and response dict.

    HTTPServer needs a class; this factory produces one that uses the
    shared auth_event/auth_response objects so the main thread can wait
    and read results.
    """
    class AuthCallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/tuitter-logo.png"):
                try:
                    p = os.path.join(os.path.dirname(__file__), "tuitter-logo.png")
                    with open(p, "rb") as fh:
                        data = fh.read()
                    self.send_response(200)
                    self.send_header("Content-type", "image/png")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception:
                    pass

            """Handle OAuth callback"""
            try:
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                code = params.get('code', [None])[0]

                if not code:
                    raise AuthError("No authorization code received")

                auth_response['code'] = code

                # Send success page
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                success_html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@700;800&family=Inter:wght@400;500&display=swap" rel="stylesheet">
  <title>tuitter — authenticated</title>
  <style>
    *{box-sizing:border-box}
    /* Dracula theme variables (local copy) */
    :root{--background:#12081a;--background-dark:#05020b;--card:#18151a;--foreground:#eff4ff;--muted:#6b728e;--primary:#ff79c6;--secondary:#bd93f9;--accent:#8be9fd;--success:#50fa7b;--danger:#ff5555;--border:rgba(255,255,255,.04)}
    body{margin:0;min-height:100vh;background:linear-gradient(180deg,var(--background-dark) 0%,var(--background) 100%);display:flex;align-items:center;justify-content:center;font-family:'Inter',sans-serif;color:var(--foreground)}
    .panel{width:440px;max-width:92vw;background:var(--card);border-radius:12px;padding:34px 36px 34px;color:var(--foreground);border:1px solid var(--border)}
    .chrome{height:6px;background:#1f2228;border-radius:6px 6px 0 0;margin:-34px -36px 18px;box-shadow:inset 0 -1px 0 rgba(255,255,255,.02)}
    .logo{display:block;margin:10px auto 6px;width:84px;height:84px;object-fit:contain;transform:translateY(6px)}
    .title{font-family:'Space Grotesk',sans-serif;color:var(--secondary);font-size:2.4rem;text-align:center;margin:6px 0 12px}
    .badge{display:inline-block;background:var(--success);color:#07211a;padding:6px 14px;border-radius:6px;font-weight:700;font-family:monospace;font-size:.78rem;margin:0 auto}
    .hint{color:var(--muted);text-align:center;font-size:.9rem;margin:18px 0 20px;line-height:1.6}
    .terminal{background:#0f1115;border-radius:8px;padding:10px 12px;font-family:monospace;font-size:.78rem;color:#99a0b7;display:flex;justify-content:space-between;align-items:center;border:1px solid var(--border)}
    .dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--success);margin-right:8px}
  </style>
</head>
<body>
  <div class="panel">
    <div class="chrome"></div>
    <img class="logo" src="/tuitter-logo.png" alt="tuitter logo">
    <div class="title">tuitter</div>
    <div style="text-align:center;margin-bottom:6px;"><span class="badge">AUTHENTICATED</span></div>
    <div class="hint">You’re signed in. Return to your terminal and enjoy the feed.</div>
    <div class="terminal"><div style="display:flex;align-items:center"><span class="dot"></span> auth session established</div><div style="opacity:.6">200 OK</div></div>
  </div>
</body>
</html>"""
                self.wfile.write(success_html.encode('utf-8'))
            except Exception as e:
                auth_response['error'] = str(e)
                self.send_response(400)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                error_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="color-scheme" content="dark">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@700;800&family=Inter:wght@400;500&display=swap" rel="stylesheet">
  <title>tuitter — auth failed</title>
  <style>
        *{{box-sizing:border-box}}
        :root{{--background:#12081a;--background-dark:#05020b;--card:#18151a;--foreground:#eff4ff;--muted:#6b728e;--primary:#ff79c6;--secondary:#bd93f9;--accent:#8be9fd;--success:#50fa7b;--danger:#ff5555;--border:rgba(255,255,255,.04)}}
        body{{margin:0;min-height:100vh;background:linear-gradient(180deg,var(--background-dark) 0%,var(--background) 100%);display:flex;align-items:center;justify-content:center;font-family:'Inter',sans-serif;color:var(--foreground)}}
        .panel{{width:440px;max-width:92vw;background:var(--card);border-radius:12px;padding:34px 36px 34px;color:var(--foreground);border:1px solid var(--border)}}
        .chrome{{height:6px;background:#1f2228;border-radius:6px 6px 0 0;margin:-34px -36px 18px;box-shadow:inset 0 -1px 0 rgba(255,255,255,.02)}}
        .logo{{display:block;margin:10px auto 6px;width:84px;height:84px;object-fit:contain;transform:translateY(6px)}}
        .title{{font-family:'Space Grotesk',sans-serif;color:var(--secondary);font-size:2.4rem;text-align:center;margin:6px 0 12px}}
        .badge{{display:inline-block;background:var(--danger);color:#fff;padding:6px 14px;border-radius:6px;font-weight:700;font-family:monospace;font-size:.78rem;margin:0 auto}}
        .hint{{color:var(--muted);text-align:center;font-size:.9rem;margin:18px 0 20px;line-height:1.6}}
        .terminal{{background:#0f1115;border-radius:8px;padding:10px 12px;font-family:monospace;font-size:.78rem;color:#99a0b7;display:flex;justify-content:space-between;align-items:center;border:1px solid var(--border)}}
        .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--danger);margin-right:8px}}
  </style>
</head>
<body>
  <div class="panel">
    <div class="chrome"></div>
    <img class="logo" src="/tuitter-logo.png" alt="tuitter logo">
    <div class="title">tuitter</div>
    <div style="text-align:center;margin-bottom:6px;"><span class="badge">AUTH FAILED</span></div>
    <div class="hint">Authentication failed. Please try again or check your network.</div>
    <div class="terminal"><div style="display:flex;align-items:center"><span class="dot"></span> {error}</div><div style="opacity:.6">400</div></div>
  </div>
</body>
</html>"""
                self.wfile.write(error_html.encode('utf-8'))
            finally:
                # Signal the main thread that the callback was received
                auth_event.set()

        def log_message(self, format, *args):
            # suppress console logging from BaseHTTPRequestHandler
            return

    return AuthCallbackHandler

def authenticate() -> Dict[str, str]:
    """Complete OAuth flow and store tokens in system keyring.
    Returns dict with username and tokens on success.
    Raises AuthError on failure.
    """
    # Create server with fixed port that matches Cognito configuration
    auth_event = threading.Event()
    auth_response: Dict[str, str] = {}

    # Configure logging for debug mode (enable by setting TUITTER_DEBUG=1)
    logger = logging.getLogger("tuitter.auth")
    if not logger.handlers:
        level = logging.DEBUG if os.getenv("TUITTER_DEBUG") else logging.WARNING
        logger.setLevel(level)
        fmt = logging.Formatter("[%(name)s] %(levelname)s: %(message)s")

        # Only write to a debug file when debugging is enabled. Do NOT add
        # a console/stream handler — logs should go to the file only when
        # TUITTER_DEBUG is set.
        if os.getenv("TUITTER_DEBUG"):
            try:
                log_file = Path.home() / ".tuitter_debug.log"
                fh = logging.FileHandler(log_file, encoding="utf-8")
                fh.setLevel(level)
                fh.setFormatter(fmt)
                logger.addHandler(fh)
            except Exception:
                # Never fail auth because logging setup couldn't write the file
                pass

    handler_class = _make_handler(auth_event, auth_response)
    try:
        # Allow immediate reuse of the address so restarting the auth flow
        # (sign-out -> sign-in) does not fail due to sockets in TIME_WAIT.
        socketserver.TCPServer.allow_reuse_address = True
        server = http.server.HTTPServer(('localhost', REDIRECT_PORT), handler_class)
        logger.debug(f"HTTP server listening on http://localhost:{REDIRECT_PORT}")
    except OSError as e:
        if e.errno == 98 or e.errno == 10048:  # Port already in use
            raise AuthError("Auth server port already in use. Please try again in a few moments.")
        raise

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    logger.debug("Auth server thread started (daemon)")

    try:
        # Build authorization URL with properly encoded parameters
        auth_params = {
            'client_id': CLIENT_ID,
            'response_type': 'code',
            'scope': ' '.join(SCOPES),
            'redirect_uri': REDIRECT_URI
        }
        auth_url = f"{COGNITO_AUTH_URL}?{urlencode(auth_params)}"

        # Open browser for auth
        logger.debug(f"Opening browser to: {auth_url}")
        try:
            webbrowser.open(auth_url)
        except Exception:
            # If browser.open fails, still proceed and let user open URL manually
            logger.warning("Failed to open browser automatically; please open the URL shown above.")

        # Wait for callback
        if not auth_event.wait(timeout=300):  # 5 minute timeout
            raise AuthError("Authentication timed out")

        if 'error' in auth_response:
            raise AuthError(auth_response['error'])

        if 'code' not in auth_response:
            raise AuthError("No authorization code received")

        # Exchange code for tokens
        logger.debug("Received callback code: %s", auth_response.get('code'))
        try:
            token_response = requests.post(
                COGNITO_TOKEN_URL,
                data={
                    'grant_type': 'authorization_code',
                    'client_id': CLIENT_ID,
                    'client_secret': CLIENT_SECRET,
                    'code': auth_response['code'],
                    'redirect_uri': REDIRECT_URI
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=15,
            )
        except Exception as e:
            logger.exception("Token exchange request failed")
            raise AuthError(f"Token exchange request failed: {e}")

        logger.debug("Token exchange HTTP %s", token_response.status_code)

        if not token_response.ok:
            raise AuthError(f"Token exchange failed: {token_response.text}")

        tokens = token_response.json()

        # Get user info
        try:
            user_response = requests.get(
                COGNITO_USERINFO_URL,
                headers={'Authorization': f"Bearer {tokens['access_token']}"},
                timeout=10,
            )
        except Exception as e:
            logger.exception("User info request failed")
            raise AuthError(f"User info request failed: {e}")

        if not user_response.ok:
            raise AuthError(f"Failed to get user info: {user_response.text}")

        user_info = user_response.json()
        username = user_info.get('username') or user_info.get('sub') or ''
        logger.debug("Retrieved user info: %s", user_info)

        # Delegate secure storage to centralized auth_storage which will
        # choose the appropriate backend (DPAPI on Windows, keyring on
        # other platforms). Persist the full token blob (contains refresh token).
        try:
            save_tokens_full(tokens, username)
        except Exception:
            logger.exception("Failed to save full tokens via auth_storage (non-fatal)")

        return {'username': username, 'tokens': tokens}


    finally:
        # Don't call server.shutdown() here (it blocks). The server thread is
        # daemon=True and will exit with the process. Close the listening socket
        # to free the port for subsequent sign-ins.
        try:
            if server:
                logger.debug("Closing auth server socket")
                server.server_close()
        except Exception:
            logger.exception("Failed to close auth server socket cleanly")

def get_stored_credentials() -> Optional[Dict[str, str]]:
    """Retrieve stored credentials from system keyring or DPAPI-encrypted file.
    Returns dict with username and tokens if found, None otherwise.
    """
    # Prefer using centralized auth_storage loader so there's a single
    # canonical path for reading stored credentials.
    try:
        from .auth_storage import load_tokens as _load
        found = _load()
        logger = logging.getLogger("tuitter.auth")
        logger.debug("get_stored_credentials: auth_storage.load_tokens() -> %s", type(found))

        if not found:
            return None

        # If we found a full token blob, return it directly
        if 'tokens' in found and isinstance(found['tokens'], dict):
            return {'username': found.get('username') or '', 'tokens': found['tokens']}

        # If we have only a refresh token, attempt to refresh
        if 'refresh_token' in found and found.get('refresh_token'):
            try:
                tokens = refresh_tokens(found['refresh_token'])
                # Persist refreshed tokens if we successfully obtained them so
                # subsequent restarts can use the fresh access/id tokens.
                try:
                    save_tokens_full(tokens, found.get('username') or None)
                except Exception:
                    logger = logging.getLogger("tuitter.auth")
                    logger.debug("get_stored_credentials: failed to persist refreshed tokens (non-fatal)")
                if tokens:
                    return {'username': found.get('username') or '', 'tokens': tokens}
            except Exception:
                # refresh failed; fall through to return None
                logger.debug("get_stored_credentials: refresh_tokens failed")

        return None
    except Exception:
        # If anything goes wrong, don't crash - return None so caller shows auth
        return None


def refresh_tokens(refresh_token: str) -> Dict[str, str]:
    """Use the OAuth2 refresh_token grant to obtain new tokens.

    Returns the token dict on success or raises AuthError on failure.
    """
    logger = logging.getLogger("tuitter.auth")
    try:
        resp = requests.post(
            COGNITO_TOKEN_URL,
            data={
                'grant_type': 'refresh_token',
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_SECRET,
                'refresh_token': refresh_token,
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=10,
        )
    except Exception as e:
        logger.exception("Refresh token request failed")
        raise AuthError(f"Refresh token request failed: {e}")

    if not resp.ok:
        logger.debug("Refresh token HTTP %s: %s", resp.status_code, resp.text)
        raise AuthError(f"Failed to refresh tokens: {resp.text}")

    return resp.json()

def clear_credentials():
    """Clear stored credentials from system keyring."""
    try:
        # Delegate clearing to centralized helper which also removes chunked parts
        try:
            clear_tokens()
        except Exception:
            # best-effort fallback: attempt to remove legacy keys
            try:
                keyring.delete_password(SERVICE_NAME, 'refresh_token')
            except Exception:
                pass
            try:
                keyring.delete_password(SERVICE_NAME, 'username')
            except Exception:
                pass
            try:
                keyring.delete_password(SERVICE_NAME, 'oauth_tokens.json')
            except Exception:
                pass
            try:
                if FALLBACK_TOKEN_FILE.exists():
                    FALLBACK_TOKEN_FILE.unlink()
            except Exception:
                pass
    except:
        pass  # Ignore errors deleting from keyring
