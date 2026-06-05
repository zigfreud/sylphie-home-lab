param(
    [int]$Port = 8765
)

. (Join-Path $PSScriptRoot "sylphie_lifecycle_common.ps1")

$ProjectRoot = Get-SylphieProjectRoot
$StateDir = Join-Path $ProjectRoot ".sylphie"
$PidPath = Join-Path $StateDir "server.pid"
$Url = Get-SylphieSavedUrl -ProjectRoot $ProjectRoot -DefaultPort $Port
$ConfiguredPort = Get-SylphiePortFromUrl -Url $Url -DefaultPort $Port
if ($PSBoundParameters.ContainsKey("Port")) {
    $ConfiguredPort = $Port
}
$LogPath = Join-Path $ProjectRoot "logs\server.log"

$savedPid = Get-SylphieSavedPid -ProjectRoot $ProjectRoot
$savedInfo = $null
if ($null -ne $savedPid) {
    $savedInfo = Get-SylphieProcessInfo -ProcessId $savedPid
}

$portOwnerPid = Get-SylphiePortOwnerPid -Port $ConfiguredPort
$portOwnerInfo = $null
if ($null -ne $portOwnerPid) {
    $portOwnerInfo = Get-SylphieProcessInfo -ProcessId $portOwnerPid
}

Write-Host "Sylphie status"
Write-Host "URL: $Url"
Write-Host "Configured port: $ConfiguredPort"
Write-Host "Log: $LogPath"

if ($null -eq $savedPid) {
    Write-Host "Saved PID: none"
} else {
    Write-Host "Saved PID: $savedPid"
}
Write-SylphieProcessInfo -Label "Saved PID process:" -ProcessInfo $savedInfo

if ($null -eq $portOwnerPid) {
    Write-Host "Port owner: none"
} else {
    Write-Host "Port owner PID: $portOwnerPid"
}
Write-SylphieProcessInfo -Label "Port owner process:" -ProcessInfo $portOwnerInfo

if (($null -ne $savedPid) -and ($null -ne $portOwnerPid)) {
    if ($savedPid -eq $portOwnerPid) {
        Write-Host "PID file matches port owner."
    } else {
        Write-Host "PID file does not match port owner"
    }
}

if ($null -eq $portOwnerPid) {
    Write-Host "Running: false"
    exit 0
}

Write-Host "Running: true"
try {
    $healthUrl = $Url.TrimEnd("/") + "/api/health"
    $health = Invoke-RestMethod -Method Get -Uri $healthUrl -TimeoutSec 6
    Write-Host ("Health ok: {0}" -f $health.ok)
    Write-Host ("Backend: {0}" -f $health.exe)
    Write-Host ("Backend exists: {0}" -f $health.exe_exists)
} catch {
    Write-Host ("Health check failed: {0}" -f $_.Exception.Message)
}
