param()

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StateDir = Join-Path $ProjectRoot ".sylphie"
$PidPath = Join-Path $StateDir "server.pid"
$UrlPath = Join-Path $StateDir "server.url"
$LogPath = Join-Path $ProjectRoot "logs\server.log"

$url = "http://127.0.0.1:8765/"
if (Test-Path -LiteralPath $UrlPath) {
    $url = (Get-Content -LiteralPath $UrlPath -Raw).Trim()
}

Write-Host "Sylphie status"
Write-Host "URL: $url"
Write-Host "Log: $LogPath"

if (-not (Test-Path -LiteralPath $PidPath)) {
    Write-Host "PID: none"
    Write-Host "Running: false"
    exit 0
}

$pidText = (Get-Content -LiteralPath $PidPath -Raw).Trim()
Write-Host "PID: $pidText"
if (-not ($pidText -match "^\d+$")) {
    Write-Host "Running: false (invalid PID file)"
    exit 1
}

$serverPid = [int]$pidText
$process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Write-Host "Running: false"
    exit 0
}

Write-Host "Running: true"
try {
    $healthUrl = $url.TrimEnd("/") + "/api/health"
    $health = Invoke-RestMethod -Method Get -Uri $healthUrl -TimeoutSec 6
    Write-Host ("Health ok: {0}" -f $health.ok)
    Write-Host ("Backend: {0}" -f $health.exe)
    Write-Host ("Backend exists: {0}" -f $health.exe_exists)
} catch {
    Write-Host ("Health check failed: {0}" -f $_.Exception.Message)
}
