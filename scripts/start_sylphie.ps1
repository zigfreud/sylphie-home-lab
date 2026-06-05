param(
    [int]$Port = 8765,
    [Alias("Host")]
    [string]$BindHost = "127.0.0.1",
    [switch]$NoBrowser,
    [switch]$Restart,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "sylphie_lifecycle_common.ps1")

$ProjectRoot = Get-SylphieProjectRoot
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

if ($Restart) {
    Write-Host "Restart requested. Stopping existing Sylphie server if present..."
    & (Join-Path $PSScriptRoot "stop_sylphie.ps1") -Port $Port
    if ($LASTEXITCODE -ne 0) {
        Fail "Restart requested but stop_sylphie.ps1 did not stop the existing server."
    }
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

$existingOwnerPid = Get-SylphiePortOwnerPid -Port $Port
if ($null -ne $existingOwnerPid) {
    $existingInfo = Get-SylphieProcessInfo -ProcessId $existingOwnerPid
    Write-Host "Port $Port is already listening."
    Write-SylphieProcessInfo -Label "Port owner process:" -ProcessInfo $existingInfo

    $looksLikeSylphie = Test-SylphieProcessSignature `
        -ProcessInfo $existingInfo `
        -Port $Port `
        -PortOwnerPid $existingOwnerPid

    if ($looksLikeSylphie) {
        Set-Content -LiteralPath $PidPath -Value ([string]$existingOwnerPid) -Encoding ASCII
        Set-Content -LiteralPath $UrlPath -Value $Url -Encoding ASCII
        Write-Host "Existing Sylphie server detected. Not starting another."
        Write-Host "Server PID: $existingOwnerPid"
        Write-Host "URL: $Url"
        Write-Host "Exe: $ExePath"
        Write-Host "Log: $LogPath"
        if (-not $NoBrowser) { Start-Process $Url }
        exit 0
    }

    Fail "Port $Port is occupied by a process that does not look like Sylphie. Use status_sylphie.ps1 to inspect it."
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

Set-Content -LiteralPath $UrlPath -Value $Url -Encoding ASCII

$realOwnerPid = Wait-SylphiePortOwnerPid -Port $Port -TimeoutSeconds 5
if ($null -eq $realOwnerPid) {
    if ($process.HasExited) {
        Fail "Sylphie server exited immediately. Check $LogPath and $ErrLogPath"
    }
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    Fail "Sylphie server did not start listening on port $Port within 5 seconds. Check $LogPath and $ErrLogPath"
}

Set-Content -LiteralPath $PidPath -Value ([string]$realOwnerPid) -Encoding ASCII

$ownerInfo = Get-SylphieProcessInfo -ProcessId $realOwnerPid
$ownerLooksLikeSylphie = Test-SylphieProcessSignature `
    -ProcessInfo $ownerInfo `
    -Port $Port `
    -PortOwnerPid $realOwnerPid
if (-not $ownerLooksLikeSylphie) {
    Write-Warning "Process listening on port $Port does not match Sylphie signature."
    Write-SylphieProcessInfo -Label "Listener process:" -ProcessInfo $ownerInfo
}

Write-Host "Sylphie server started."
Write-Host "Server PID: $realOwnerPid"
Write-Host "URL: $Url"
Write-Host "Exe: $ExePath"
Write-Host "Log: $LogPath"

if (-not $NoBrowser) {
    Start-Process $Url
}
