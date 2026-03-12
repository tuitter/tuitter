# Tuitter

Terminal social client.

Tuitter is a keyboard-first, terminal-native social client built for people who prefer speed, privacy, and staying in the flow of their terminal workflows.

## Installation

Requires **Python 3.10+**. The recommended way is `pipx`, which installs tuitter in its own isolated virtual environment and puts the `tuitter` command on your PATH.

### macOS / Linux / WSL — one-liner

```bash
curl -fsSL https://raw.githubusercontent.com/tuitter/tuitter/main/install.sh | bash
```

Or manually with pipx:

```bash
pipx install "git+https://github.com/tuitter/tuitter.git"
```

### Windows — PowerShell one-liner

```powershell
irm https://raw.githubusercontent.com/tuitter/tuitter/main/install.ps1 | iex
```

> If you get a security error run this first:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

Or manually with pipx:

```powershell
pipx install "git+https://github.com/tuitter/tuitter.git"
```

### Don't have pipx?

Install it first:

```bash
# macOS / Linux
python3 -m pip install --user pipx && python3 -m pipx ensurepath
# restart your terminal, then run the install command above
```

```powershell
# Windows
python -m pip install --user pipx; python -m pipx ensurepath
# restart your terminal, then run the install command above
```

### Alternative: plain pip into a venv

```bash
python3 -m venv tuitter-env
source tuitter-env/bin/activate        # Windows: tuitter-env\Scripts\activate
pip install "git+https://github.com/tuitter/tuitter.git"
tuitter
```

### Optional: video-to-ASCII support

The base install is lightweight (~50 MB). If you also want to convert video files to ASCII art, install the `video` extra (adds OpenCV + NumPy, ~450 MB):

```bash
pipx inject tuitter "git+https://github.com/tuitter/tuitter.git[video]"
# or during initial install:
pipx install "git+https://github.com/tuitter/tuitter.git[video]"
```

### Installing Python (if needed)

| Platform      | Command                                                                                |
| ------------- | -------------------------------------------------------------------------------------- |
| macOS         | `brew install python@3.12`                                                             |
| Ubuntu/Debian | `sudo apt install python3.12 python3.12-venv python3-pip`                              |
| Arch          | `sudo pacman -S python`                                                                |
| Fedora        | `sudo dnf install python3.12`                                                          |
| Windows       | `winget install Python.Python.3.12` or [python.org](https://www.python.org/downloads/) |

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

- **Keyboard-first navigation**: Native Vim-style controls (`j`, `k`, `h`, `l`, `gg`, `G`, `ctrl+d/u`) for seamless movement.
- **Command Mode**: Power users can use `:` (colon) to jump between screens (eg. `:1`, `:p`) or perform actions (eg. `:del` to delete, `:q` to quit).
- **Full-size Media Viewer**: Press `o` on any post with an image or video to open it in a full-resolution modal viewer.
- **Complete Feature Set**: Timeline, Discover, Following, Notifications, Messages, and Settings screens.
- **Advanced Drafting**: Robust in-memory drafts system with image preview and scaling.
- **Expressive ASCII**: Built-in ASCII avatar generator and high-quality image/video → braille art conversion.

## Keyboard controls

Tuitter is designed to be used entirely from the keyboard.

| Key             | Action                                      |
| --------------- | ------------------------------------------- |
| `1` - `6`       | Switch screens (Timeline, Discover, etc.)   |
| `j` / `k`       | Navigate down / up                          |
| `h` / `l`       | Navigate left / right (in panels or posts)  |
| `gg` / `G`      | Jump to top / bottom                        |
| `ctrl+d` / `u`  | Scroll half-page down / up                  |
| `o`             | Open media (full-size image/video viewer)   |
| `n`             | Compose new post                            |
| `:`             | Enter Command Mode (eg. `:q`, `:p`, `:1-6`) |
| `q`             | Close modal or quit (from timeline)         |
| `esc`           | Exit input/command mode or dismiss modals   |

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
- When asking for help, include your platform (OS and Python version).
  -- Want to contribute? Open an issue or PR and we can help you get started.
