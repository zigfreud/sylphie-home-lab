param(
    [switch]$NoPayloadCapture
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Exe = Join-Path $Root "bin\sylphie_piix4_armoury_ui_capture.exe"
$StateDir = Join-Path $Root ".sylphie"
$CaptureDir = Join-Path $Root "research\captures"

if (-not (Test-Path -LiteralPath $Exe)) {
    throw "Missing probe executable: $Exe"
}

New-Item -ItemType Directory -Force -Path $StateDir, $CaptureDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$Log = Join-Path $CaptureDir "armoury_ui_${Stamp}_master.log"
$Args = @("--base", "0B20", "--output", $Log, "--segment-logs")
if (-not $NoPayloadCapture) {
    $Args += "--capture-block-payload"
}

$Process = Start-Process -FilePath $Exe -ArgumentList $Args -WorkingDirectory $Root -PassThru -WindowStyle Hidden
@{
    type = "armoury-ui"
    pid = $Process.Id
    log = $Log
    started_at = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $StateDir "capture_state.json") -Encoding UTF8

Write-Host "Started Armoury UI capture PID $($Process.Id)"
Write-Host "Log: $Log"
