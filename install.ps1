# tuitter installer for Windows (PowerShell)
# Downloads a prebuilt .exe - no Python, git, or pip required.
#
# Usage (run in PowerShell as normal user):
#   irm https://raw.githubusercontent.com/tuitter/tuitter/dev/install.ps1 | iex
#
# If you get a security error, run first:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"  # prevents terminal crash on large downloads

$Repo      = "tuitter/tuitter"
$AssetName = "tuitter-windows-x86_64.exe"
$BinDir    = "$env:LOCALAPPDATA\Microsoft\WindowsApps"
$Dest      = "$BinDir\tuitter.exe"

function Write-Green($msg)  { Write-Host $msg -ForegroundColor Green }
function Write-Yellow($msg) { Write-Host $msg -ForegroundColor Yellow }
function Write-Red($msg)    { Write-Host $msg -ForegroundColor Red }
function Write-Bold($msg)   { Write-Host $msg -ForegroundColor Cyan }

Write-Bold "tuitter installer for Windows"
Write-Host ""

# Find the download URL across stable and pre-releases
function Get-DownloadUrl {
    # Try stable release first
    try {
        $r = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest" -UseBasicParsing
        foreach ($a in $r.assets) {
            if ($a.name -eq $AssetName) { return [string]$a.browser_download_url }
        }
    } catch {}

    # Fall back to most recent release including pre-releases
    try {
        $list = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases" -UseBasicParsing
        foreach ($r in $list) {
            foreach ($a in $r.assets) {
                if ($a.name -eq $AssetName) { return [string]$a.browser_download_url }
            }
        }
    } catch {}

    return $null
}

Write-Green "Fetching release info..."
$downloadUrl = Get-DownloadUrl

if ($downloadUrl) {
    Write-Green "Downloading $AssetName..."
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    (New-Object System.Net.WebClient).DownloadFile($downloadUrl, $Dest)
    Write-Host ""
    Write-Green "tuitter installed to $Dest"
    if (-not ($env:PATH -split ';' | Where-Object { $_ -eq $BinDir })) {
        [Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";$BinDir", "User")
        Write-Yellow "Added $BinDir to your PATH. Restart your terminal."
    }
    Write-Host ""
    Write-Bold "Done! Open a new terminal and run: tuitter"
    exit 0
}

Write-Red "No prebuilt binary found."
Write-Host ""
Write-Host "Download it manually from:"
Write-Host "  https://github.com/$Repo/releases"
exit 1
