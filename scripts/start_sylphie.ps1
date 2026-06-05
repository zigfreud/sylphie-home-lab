param(
    [int]$Port = 8765,
    [Alias("Host")]
    [string]$BindHost = "127.0.0.1",
    [switch]$NoBrowser,
    [switch]$Restart,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ExePath = Join-Path $ProjectRoot "bin\sylphie_rgb.exe"
$DllPath = Join-Path $ProjectRoot "bin\inpout32.dll"
$ServerPath = Join-Path $ProjectRoot "src\server\sylphie_server.py"
$LogsDir = Join-Path $ProjectRoot "logs"
$StateDir = Join-Path $ProjectRoot ".sylphie"
$LogPath = Join-Path $LogsDir "server.log"
$ErrLogPath = Join-Path $LogsDir "server.err.log"
$PidPath = Join-Path $StateDir "server.pid"
$UrlPath = Join-Path $StateDir "server.url"
$Url = "http://$BindHost`:$Port/"

function Fail($Message) {
    Write-Error $Message
    exit 1
}

function Get-ListeningPid($Port) {
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $connection) {
            return [int]$connection.OwningProcess
        }
    } catch {
        return $null
    }
    return $null
}

function Warn-AsusProcesses {
    $names = @("LightingService", "ArmouryCrate", "ArmourySocketServer", "ArmourySwAgent", "asus_framework", "Aura")
    $matches = @()
    foreach ($name in $names) {
        $matches += Get-Process -Name $name -ErrorAction SilentlyContinue
    }
    if ($matches.Count -gt 0) {
        Write-Warning "ASUS/Aura processes detected. Close or stop them before hardware writes:"
        foreach ($process in $matches | Sort-Object ProcessName -Unique) {
            Write-Warning ("  {0} pid={1}" -f $process.ProcessName, $process.Id)
        }
    }
}

function Get-SavedServerProcess {
    if (-not (Test-Path -LiteralPath $PidPath)) {
        return $null
    }
    $pidText = (Get-Content -LiteralPath $PidPath -Raw).Trim()
    if (-not ($pidText -match "^\d+$")) {
        return $null
    }
    return Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
}

if ($Restart) {
    Write-Host "Restart requested. Stopping existing Sylphie server if present..."
    & (Join-Path $PSScriptRoot "stop_sylphie.ps1")
}

if ($BindHost -ne "127.0.0.1") {
    Write-Warning "Binding to $BindHost exposes the API beyond localhost. 0.0.0.0 is not recommended without auth."
}

if (-not (Test-Path -LiteralPath $ExePath)) { Fail "Missing backend executable: $ExePath" }
if (-not (Test-Path -LiteralPath $DllPath)) { Fail "Missing inpout32.dll next to executable: $DllPath" }
if (-not (Test-Path -LiteralPath $ServerPath)) { Fail "Missing server script: $ServerPath" }

$Python = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $Python) { Fail "python is not available in PATH" }

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

Warn-AsusProcesses

Write-Host "Running doctor..."
$doctorOutput = & $ExePath doctor 2>&1 | Out-String
if ($Verbose) { Write-Host $doctorOutput }
if ($LASTEXITCODE -ne 0) {
    Fail "sylphie_rgb.exe doctor failed. Output:`n$doctorOutput"
}

$savedProcess = Get-SavedServerProcess
if ($null -ne $savedProcess) {
    Write-Host "Sylphie server already running from saved PID $($savedProcess.Id)."
    Set-Content -LiteralPath $UrlPath -Value $Url -Encoding ASCII
    Write-Host "URL: $Url"
    Write-Host "Exe: $ExePath"
    Write-Host "Log: $LogPath"
    if (-not $NoBrowser) { Start-Process $Url }
    exit 0
}

$existingPid = Get-ListeningPid $Port
if ($null -ne $existingPid) {
    Write-Host "Port $Port is already listening (pid $existingPid). Not starting another server."
    Set-Content -LiteralPath $UrlPath -Value $Url -Encoding ASCII
    Write-Host "URL: $Url"
    Write-Host "Exe: $ExePath"
    Write-Host "Log: $LogPath"
    if (-not $NoBrowser) { Start-Process $Url }
    exit 0
}

$arguments = @(
    "src\server\sylphie_server.py",
    "--host", $BindHost,
    "--port", [string]$Port,
    "--exe", "bin\sylphie_rgb.exe"
)

Write-Host "Starting Sylphie server at $Url"
$process = Start-Process `
    -FilePath $Python.Source `
    -ArgumentList $arguments `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $LogPath `
    -RedirectStandardError $ErrLogPath `
    -WindowStyle Hidden `
    -PassThru

Set-Content -LiteralPath $PidPath -Value ([string]$process.Id) -Encoding ASCII
Set-Content -LiteralPath $UrlPath -Value $Url -Encoding ASCII

Start-Sleep -Milliseconds 700
if ($process.HasExited) {
    Remove-Item -LiteralPath $PidPath -ErrorAction SilentlyContinue
    Fail "Sylphie server exited immediately. Check $LogPath and $ErrLogPath"
}

Write-Host "Sylphie server started. PID: $($process.Id)"
Write-Host "URL: $Url"
Write-Host "Exe: $ExePath"
Write-Host "Log: $LogPath"

if (-not $NoBrowser) {
    Start-Process $Url
}
