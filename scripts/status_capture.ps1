$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$State = Join-Path $Root ".sylphie\capture_state.json"

if (-not (Test-Path -LiteralPath $State)) {
    Write-Host "Capture: no state file"
    exit 0
}

$Data = Get-Content -LiteralPath $State -Raw | ConvertFrom-Json
$Process = Get-Process -Id $Data.pid -ErrorAction SilentlyContinue
Write-Host "Capture type: $($Data.type)"
Write-Host "PID: $($Data.pid)"
Write-Host "Running: $($null -ne $Process)"
Write-Host "Log: $($Data.log)"
Write-Host "Started: $($Data.started_at)"
