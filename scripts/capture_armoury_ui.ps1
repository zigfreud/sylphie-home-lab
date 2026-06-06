param(
    [string]$Base = "0B20",
    [string]$Output,
    [switch]$NoSegmentLogs,
    [switch]$NoPayloadCapture
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Resolve-Path (Join-Path $scriptDir "..")
$exe = Join-Path $root "bin\sylphie_piix4_armoury_ui_capture.exe"

if (-not (Test-Path -LiteralPath $exe)) {
    throw "Probe executable not found: $exe. Build it with tools\probes\build_armoury_ui_capture.bat from an x86 VS developer shell."
}

$captureDir = Join-Path $root "research\captures"
New-Item -ItemType Directory -Force -Path $captureDir | Out-Null

if (-not $Output) {
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $Output = Join-Path $captureDir "armoury_ui_${stamp}_master.log"
}

Write-Host "Sylphie Armoury UI capture"
Write-Host "Output: $Output"
Write-Host ""
Write-Host "Marker keys:"
Write-Host "  1 SERVICE_STOPPED"
Write-Host "  2 SERVICE_STARTED"
Write-Host "  3 FIRST_LIGHT"
Write-Host "  m MOUSE_COLOR_SELECTED"
Write-Host "  o OK_CLICKED"
Write-Host "  a APPLY_CLICKED"
Write-Host "  w WHITE_SELECTED"
Write-Host "  r RED_SELECTED"
Write-Host "  g GREEN_SELECTED"
Write-Host "  b BLUE_SELECTED"
Write-Host "  q QUIT"
Write-Host ""

$argsList = @("--base", $Base, "--output", $Output)
if (-not $NoPayloadCapture) {
    $argsList += "--capture-block-payload"
}
if (-not $NoSegmentLogs) {
    $argsList += "--segment-logs"
}

& $exe @argsList
