# Backup the BucketIO SQLite database (safe while the app is running: uses
# sqlite3's online backup API, so WAL writers are not disturbed).
#
#   .\scripts\backup.ps1
#   .\scripts\backup.ps1 -DbPath .\bucketio.db -OutDir .\backups
param(
    [string]$DbPath = ".\bucketio.db",
    [string]$OutDir = ".\backups"
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $DbPath)) {
    Write-Host "[backup] no database at $DbPath"
    exit 1
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$target = Join-Path $OutDir "bucketio-$stamp.db"
uv run python -c "import sqlite3, sys; src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2]); src.backup(dst); dst.close(); src.close(); print('backed up ->', sys.argv[2])" $DbPath $target
