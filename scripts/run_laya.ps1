$env:USE_TF = "0"
$env:LAYA_HOST = "127.0.0.1"
$env:LAYA_PORT = "8001"
$env:LAYA_PRELOAD = "1"
$env:LAYA_DEVICE = "cpu"
if (-not $env:LAYA_API_KEY) { $env:LAYA_API_KEY = "change-me" }

Write-Host "BucketIO Laya sidecar -> http://127.0.0.1:8001 (Ctrl+C to stop)"
Write-Host 'Needs the server extras: uv pip install "laya[serve]"'

laya-serve
