# tuitter installer for Windows (PowerShell)
# Downloads a prebuilt .exe â€” no Python, git, or pip required.
#
# Usage (run in PowerShell as normal user):
#   irm https://raw.githubusercontent.com/tuitter/tuitter/main/install.ps1 | iex
#
# If you get a security error, run first:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

$ErrorActionPreference = "Stop"

$Repo   = "tuitter/tuitter"
$Asset  = "tuitter-windows-x86_64.exe"
$BinDir = "$env:LOCALAPPDATA\Microsoft\WindowsApps"
$Dest   = "$BinDir\tuitter.exe"

function Write-Green($msg)  { Write-Host $msg -ForegroundColor Green }
function Write-Yellow($msg) { Write-Host $msg -ForegroundColor Yellow }
function Write-Red($msg)    { Write-Host $msg -ForegroundColor Red }
function Write-Bold($msg)   { Write-Host $msg -ForegroundColor Cyan }

Write-Bold "tuitter installer for Windows"
Write-Host ""

# â”€â”€ 1. Try prebuilt binary (preferred â€” no Python required) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
try {
    Write-Green "Fetching latest release info..."
    $api = "https://api.github.com/repos/$Repo/releases/latest"
    $release = Invoke-RestMethod -Uri $api -UseBasicParsing
    $asset = $release.assets | Where-Object { $_.name -eq $Asset } | Select-Object -First 1

    if ($asset) {
        Write-Green "Downloading $Asset..."
        New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
        Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $Dest -UseBasicParsing
        Write-Host ""
        Write-Green "âœ“ tuitter installed to $Dest"

        # Verify it's on PATH
        if (-not ($env:PATH -split ';' | Where-Object { $_ -eq $BinDir })) {
            $addPath = '[Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";' + $BinDir + '", "User")'
            Write-Yellow ""
            Write-Yellow "  $BinDir may not be on your PATH."
            Write-Yellow "  Run this in a new PowerShell window to add it permanently:"
            Write-Yellow "    $addPath"
        }

        Write-Host ""
        Write-Bold "Run: tuitter"
        exit 0
    } else {
        Write-Yellow "Prebuilt binary not found in latest release â€” falling back to pip install."
    }
} catch {
    Write-Yellow "Could not download binary ($_) â€” falling back to pip install."
}

# â”€â”€ 2. Fallback: pip / pipx install (requires Python 3.10+) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
Write-Yellow ""
Write-Yellow "Falling back to pip-based install (requires Python 3.10+)."
Write-Host ""

$python = $null
foreach ($cmd in @("python3.13","python3.12","python3.11","python3.10","python3","python","py")) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver -match "^3\.([0-9]+)$" -and [int]$Matches[1] -ge 10) {
            $python = $cmd; break
        }
    } catch {}
}

if (-not $python) {
    Write-Red "Python 3.10+ not found."
    Write-Host ""
    Write-Host "Install Python from https://www.python.org/downloads/"
    Write-Host "  (check 'Add Python to PATH' during install)"
    Write-Host "or:  winget install Python.Python.3.12"
    Write-Host ""
    Write-Host "Or download the binary directly from:"
    Write-Host "  https://github.com/$Repo/releases/latest"
    exit 1
}

Write-Green "âœ“ Found Python: $( & $python --version )"

$pkg = "git+https://github.com/$Repo.git"
$usePipx = $false
try { & pipx --version | Out-Null; $usePipx = $true } catch {}
try { & $python -m pipx --version | Out-Null; $usePipx = $true } catch {}

if ($usePipx) {
    try { & pipx install $pkg --force } catch { & $python -m pipx install $pkg --force }
} else {
    Write-Yellow "pipx not found â€” installing into dedicated venv..."
    $venv = "$env:LOCALAPPDATA\tuitter\.venv"
    & $python -m venv $venv
    & "$venv\Scripts\pip.exe" install --quiet --upgrade pip
    & "$venv\Scripts\pip.exe" install $pkg
    $launcher = "$BinDir\tuitter.cmd"
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    Set-Content -Path $launcher -Value "@echo off`r`n`"$venv\Scripts\tuitter.exe`" %*"
}

Write-Host ""
Write-Green "âœ“ tuitter installed!"
Write-Bold "Run: tuitter"

