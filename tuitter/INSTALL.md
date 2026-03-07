# Installation Guide for Tuitter

## Quick Setup (One Command)

```bash
git clone https://github.com/tuitter/tuitter.git
cd tuitter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

## Step-by-Step Setup

### 1. Clone the repository

```bash
git clone https://github.com/tuitter/tuitter.git
cd tuitter
```

**Important:** The `--recurse-submodules` flag automatically clones the asciifer submodule!

### 2. If you already cloned without submodules

```bash
git submodule update --init --recursive
```

### 3. Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Run the app

**Terminal mode:**

```bash
python3 main.py
```

**Web mode:**

```bash
textual-web --config serve.toml
```

### Install Poetry

```bash
pipx install poetry
poetry install
```

## Troubleshooting

### Submodule not cloned?

If the `asciifer/` folder is empty:

```bash
git submodule update --init --recursive
```

### Missing dependencies?

```bash
pip install textual textual-web requests Pillow
```

### Permission denied on setup.sh?

```bash
chmod +x setup.sh
./setup.sh
```

## What is the submodule?

- **asciifer** ([https://github.com/Refffy/asciifer](https://github.com/Refffy/asciifer)) - Converts images to ASCII art
- Used for profile picture generation in Settings
- MIT licensed

## Development

To update the asciifer submodule to latest:

```bash
cd asciifer
git pull origin master
cd ..
git add asciifer
git commit -m "Update asciifer submodule"
```

---

Need help? Open an issue on GitHub!
