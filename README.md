# Tuitter

Terminal social client.

Tuitter is a keyboard-first, terminal-native social client built for people who prefer speed, privacy, and staying in the flow of their terminal workflows. Whether you're a developer, sysadmin, designer, or just love efficient tools, Tuitter gives you a lightweight way to follow timelines, compose posts, and share expressive ASCII art without leaving your shell.

## Installation

This project supports two recommended install flows: (A) pipx / pip install, and (B) prebuilt native executables distributed via Releases. Prefer pinned release artifacts and checksum verification.

### Prerequisites

- Python 3.8+ (required for `pip`/`pipx` installs)
- Optional system tools: `ffmpeg` (video → ASCII), and OS packages providing `tkinter` for file dialogs.

### A) Install via pipx / pip (recommended for developers)

Install from PyPI (keeps CLI managed and isolated):

```bash
pipx install tuitter
```

Or with pip into a venv:

```bash
python -m venv .venv
.venv/bin/pip install tuitter
```

You can also install a specific wheel from Releases:

```bash
pipx install https://github.com/tuitter/tuitter/releases/download/v0.1.0/tuitter-<os>-<arch>.whl
```

### B) Prebuilt native executables (single-file binaries)

We publish per-platform single-file executables built with PyInstaller to GitHub Releases. Choose the binary matching your OS/arch and download it from the Releases page.

Example (Linux x86_64):

```bash
curl -LO https://github.com/tuitter/tuitter/releases/download/v0.1.0/tuitter-linux-x86_64
chmod +x tuitter-linux-x86_64
sudo mv tuitter-linux-x86_64 /usr/local/bin/tuitter
```

Example (Windows): download `tuitter-windows-x86_64.exe` and place it on your PATH, or run directly.

Verify checksums when provided (recommended):

```bash
curl -LO https://github.com/tuitter/tuitter/releases/download/v0.1.0/tuitter-linux-x86_64.sha256
sha256sum -c tuitter-linux-x86_64.sha256
```

## Security notes

- Never run a remote install script blindly — inspect or pin the exact release URL and verify its SHA256/GPG signature.
- Binaries may require platform-specific signing (macOS notarization or Windows code signing) to avoid OS warnings.

## Troubleshooting

- If video conversion fails, ensure `ffmpeg` is installed and on PATH.
- If file dialogs fail, install your OS's `tkinter` package (eg. `sudo apt install python3-tk` on Debian/Ubuntu).

## Why people love Tuitter

- Speed & focus — keyboard-first controls and lightweight rendering make it fast to scan timelines and compose replies.
- Minimal context switching — keep your hands on the keyboard and stay inside your terminal workflows.
- Privacy-forward — tokens are kept locally and the client communicates with the official hosted backend operated by the Tuitter team.
- Fun & expressive — convert images and videos to ASCII art and create playful profile pictures with the built-in generator.

## Who should try it

- Terminal-first professionals and power users
- People who prefer small, focused tools over bloated GUIs
- Communities that value privacy

## Key features

- Keyboard-first navigation (1–5 screens, vim controls)
- Timeline, Discover, Messages, Notifications, and Settings screens
- Direct messages and threaded conversations
- ASCII avatar generator and image/video → ASCII conversion

## Authentication & reference backend

Tuitter communicates with an HTTP backend using OIDC ID tokens (the reference deployment uses AWS Cognito). The packaged client works with the official hosted backend operated by the Tuitter team. Tokens are stored locally using `keyring` when available or a DPAPI-encrypted fallback on Windows.

Reference backend architecture (brief): the example backend is a FastAPI application packaged to run on AWS Lambda (an adapter like Mangum is used), exposed through API Gateway, and backed by an RDS PostgreSQL database for persistent data.

## Privacy & security

-- Tokens remain on your device and are not sent to third-party services.
-- The hosted backend and data retention policies are managed by the Tuitter team; if you have questions about data handling, contact us via issues.

## Troubleshooting (common user issues)

- "No module named tkinter": install the OS package that provides tkinter (Debian/Ubuntu: `sudo apt install python3-tk`).
- "No ffmpeg" when converting video: install ffmpeg and ensure it's on PATH.
  -- 401 Unauthorized after login: usually a backend configuration mismatch — please file an issue so the Tuitter team can investigate; end users do not host backends themselves.

## Getting help & community

- File issues or feature requests: https://github.com/tuitter/tuitter/issues
- When asking for help, include the app version (`tuitter --version`) and your platform (OS and Python version).
  -- Want to contribute? Open an issue or PR and we can help you get started.
