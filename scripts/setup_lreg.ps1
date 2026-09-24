# Lreg setup (Windows) - Laya + treg + BucketIO in one command.
#
#   .\scripts\setup_lreg.ps1              # full setup, then serve the web UI
#   .\scripts\setup_lreg.ps1 -NoStart     # set everything up, do not start anything
#   .\scripts\setup_lreg.ps1 -SkipLaya    # BucketIO only (no model download)
#
[CmdletBinding()]
param(
    [switch]$SkipLaya,
    [switch]$NoStart,
    [string]$LayaPort = "8001",
    [string]$WebPort = "8080"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Info($m) { Write-Host "[lreg] $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "[lreg] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[lreg] $m" -ForegroundColor Red; exit 1 }

# --- 1. prerequisites -------------------------------------------------------
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Fail "uv is required (Python 3.11-3.13). Install: irm https://astral.sh/uv/install.ps1 | iex"
}
if (-not (Test-Path ".python-version")) { "3.13" | Set-Content -Encoding ascii .python-version }

# --- 2. application environment --------------------------------------------
Info "syncing BucketIO environment (uv sync --extra dev)"
uv sync --extra dev
if ($LASTEXITCODE -ne 0) { Fail "uv sync failed" }

# --- 3. .env ----------------------------------------------------------------
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Info "created .env from .env.example (TREG_MODE=mock, LAYA_MODE=off -> will be set below)"
}
$envText = Get-Content ".env" -Raw

# shared secret for the local sidecar: reuse env/.env, else generate a random one
$LayaKey = $env:LAYA_API_KEY
if (-not $LayaKey) {
    $existing = Select-String -Path ".env" -Pattern '^LAYA_API_KEY=(.+)$' -ErrorAction SilentlyContinue
    if ($existing) { $LayaKey = $existing.Matches[0].Groups[1].Value.Trim() }
}
if (-not $LayaKey -or $LayaKey -eq "change-me") {
    $LayaKey = -join ((48..57) + (97..102) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
    Info "generated a random LAYA_API_KEY for the local sidecar"
}

if (-not $SkipLaya) {
    $envText = $envText -replace "(?m)^LAYA_MODE=.*$", "LAYA_MODE=shadow"
    $envText = $envText -replace "(?m)^LAYA_URL=.*$", "LAYA_URL=http://127.0.0.1:$LayaPort"
    $envText = $envText -replace "(?m)^LAYA_TIMEOUT_S=.*$", "LAYA_TIMEOUT_S=4.0"
    $envText = $envText -replace "(?m)^LAYA_API_KEY=.*$", "LAYA_API_KEY=$LayaKey"
    Set-Content -Encoding ASCII ".env" -Value $envText
}
if (-not (Select-String -Path ".env" -Pattern "^TREG_MODE=" -Quiet)) {
    Add-Content ".env" "TREG_MODE=http"
}

# --- 4. Laya sidecar --------------------------------------------------------
if (-not $SkipLaya) {
    if (-not (Test-Path ".laya-venv")) {
        Info "creating .laya-venv (Python 3.13) - separate from the app venv"
        uv venv .laya-venv --python 3.13
        if ($LASTEXITCODE -ne 0) { Fail "uv venv failed" }
    }
    Info "installing laya[serve] (torch is large; first run also downloads ~1.5 GB of weights)"
    uv pip install --python ".laya-venv\Scripts\python.exe" "laya[serve]>=0.3.20"
    if ($LASTEXITCODE -ne 0) { Fail "laya install failed" }
}

# --- 5. database ------------------------------------------------------------
Info "applying schema"
uv run bucketio init
if ($LASTEXITCODE -ne 0) { Warn "bucketio init failed - run it manually after fixing the error" }

# --- 6. start ---------------------------------------------------------------
if ($SkipLaya -or $NoStart) {
    Info "setup complete. Next:"
    if (-not $SkipLaya) { Info "  .\scripts\run_laya.ps1        # start the Laya sidecar" }
    Info "  uv run bucketio serve --port $WebPort"
    exit 0
}

New-Item -ItemType Directory -Force -Path ".lreg\logs" | Out-Null
$env:LAYA_API_KEY = $LayaKey
Info "starting Laya sidecar on 127.0.0.1:$LayaPort (weights download on first run)"
$p = Start-Process -FilePath "$root\.laya-venv\Scripts\laya-serve.exe" `
    -WorkingDirectory $root `
    -RedirectStandardOutput "$root\.lreg\logs\laya.out.log" `
    -RedirectStandardError "$root\.lreg\logs\laya.err.log" `
    -PassThru -WindowStyle Hidden `
    -Environment @{
        USE_TF = "0"; LAYA_HOST = "127.0.0.1"; LAYA_PORT = $LayaPort
        LAYA_PRELOAD = "1"; LAYA_DEVICE = "cpu"; LAYA_API_KEY = $env:LAYA_API_KEY
    } 2>$null
if (-not $p) {
    Warn "Start-Process -Environment needs PowerShell 7+; falling back to inherited env"
    $env:USE_TF = "0"; $env:LAYA_HOST = "127.0.0.1"; $env:LAYA_PORT = $LayaPort
    $env:LAYA_PRELOAD = "1"; $env:LAYA_DEVICE = "cpu"
    $p = Start-Process -FilePath "$root\.laya-venv\Scripts\laya-serve.exe" `
        -WorkingDirectory $root `
        -RedirectStandardOutput "$root\.lreg\logs\laya.out.log" `
        -RedirectStandardError "$root\.lreg\logs\laya.err.log" `
        -PassThru -WindowStyle Hidden
}
$p.Id | Set-Content ".lreg\laya.pid"
Info "Laya pid $($p.Id) (logs: .lreg\logs\laya.*.log)"

Info "starting BucketIO on http://127.0.0.1:$WebPort"
uv run bucketio serve --host 127.0.0.1 --port $WebPort

