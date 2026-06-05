param()

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$StateDir = Join-Path $ProjectRoot ".sylphie"
$PidPath = Join-Path $StateDir "server.pid"

if (-not (Test-Path -LiteralPath $PidPath)) {
    Write-Host "No Sylphie server PID file found."
    exit 0
}

$pidText = (Get-Content -LiteralPath $PidPath -Raw).Trim()
if (-not ($pidText -match "^\d+$")) {
    Remove-Item -LiteralPath $PidPath -ErrorAction SilentlyContinue
    Write-Host "Invalid PID file removed."
    exit 0
}

$serverPid = [int]$pidText
$process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Remove-Item -LiteralPath $PidPath -ErrorAction SilentlyContinue
    Write-Host "Sylphie server process is not running. PID file removed."
    exit 0
}

$commandLine = ""
try {
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid" -ErrorAction Stop
    $commandLine = [string]$cim.CommandLine
} catch {
    $commandLine = ""
}

if ($commandLine -notmatch "sylphie_server\.py") {
    Write-Host "PID $serverPid does not look like Sylphie server. Not stopping it."
    exit 1
}

Stop-Process -Id $serverPid -Force
Remove-Item -LiteralPath $PidPath -ErrorAction SilentlyContinue
Write-Host "Stopped Sylphie server pid $serverPid."
