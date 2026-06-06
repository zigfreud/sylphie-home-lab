$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$State = Join-Path $Root ".sylphie\capture_state.json"

if (-not (Test-Path -LiteralPath $State)) {
    Write-Host "Capture: no state file"
    exit 0
}

$Data = Get-Content -LiteralPath $State -Raw | ConvertFrom-Json
$Process = Get-Process -Id $Data.pid -ErrorAction SilentlyContinue
if ($null -eq $Process) {
    Write-Host "Capture process is not running."
    Remove-Item -LiteralPath $State -Force -ErrorAction SilentlyContinue
    exit 0
}

if ($Process.ProcessName -notlike "sylphie_piix4_*capture*") {
    Write-Warning "PID $($Data.pid) does not look like a Sylphie capture probe. Not stopping."
    exit 1
}

Stop-Process -Id $Data.pid -Force
Remove-Item -LiteralPath $State -Force -ErrorAction SilentlyContinue
Write-Host "Stopped capture PID $($Data.pid)"
