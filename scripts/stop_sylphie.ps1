param(
    [int]$Port = 8765,
    [switch]$Force,
    [switch]$ForcePortOwner,
    [switch]$Verbose
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "sylphie_lifecycle_common.ps1")

$ProjectRoot = Get-SylphieProjectRoot
$StateDir = Join-Path $ProjectRoot ".sylphie"
$PidPath = Join-Path $StateDir "server.pid"
$Url = Get-SylphieSavedUrl -ProjectRoot $ProjectRoot -DefaultPort $Port
$ConfiguredPort = Get-SylphiePortFromUrl -Url $Url -DefaultPort $Port
if ($PSBoundParameters.ContainsKey("Port")) {
    $ConfiguredPort = $Port
}

function Stop-SylphiePid {
    param(
        [int]$TargetPid,
        [string]$Reason
    )

    $info = Get-SylphieProcessInfo -ProcessId $TargetPid
    Write-SylphieProcessInfo -Label "Stopping process ($Reason):" -ProcessInfo $info
    try {
        Stop-Process -Id $TargetPid -Force -ErrorAction Stop
    } catch {
        Write-Warning ("Stop-Process failed: {0}" -f $_.Exception.Message)
        Write-Host "Trying taskkill fallback for pid $TargetPid..."
        $oldErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $taskkillOutput = & cmd.exe /c "taskkill /PID $TargetPid /T /F 2>&1" | Out-String
        $taskkillExitCode = $LASTEXITCODE
        $ErrorActionPreference = $oldErrorActionPreference
        Write-Host $taskkillOutput
        if ($taskkillExitCode -ne 0) {
            Write-Host "taskkill exited with code $taskkillExitCode."
        }
    }
    Start-Sleep -Milliseconds 500

    $stillRunning = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
    if ($null -eq $stillRunning) {
        Remove-Item -LiteralPath $PidPath -ErrorAction SilentlyContinue
        Write-Host "Stopped Sylphie server pid $TargetPid."
    } else {
        Write-Host "Process $TargetPid is still running. Re-run from an elevated PowerShell if this process was started elevated."
        exit 1
    }
}

Write-Host "Sylphie stop"
Write-Host "URL: $Url"
Write-Host "Port: $ConfiguredPort"

$savedPid = Get-SylphieSavedPid -ProjectRoot $ProjectRoot
$portOwnerPid = Get-SylphiePortOwnerPid -Port $ConfiguredPort

if ($null -ne $savedPid) {
    $savedInfo = Get-SylphieProcessInfo -ProcessId $savedPid
    Write-SylphieProcessInfo -Label "Saved PID process:" -ProcessInfo $savedInfo
} else {
    Write-Host "Saved PID: none"
}

if ($null -ne $portOwnerPid) {
    $portOwnerInfo = Get-SylphieProcessInfo -ProcessId $portOwnerPid
    Write-SylphieProcessInfo -Label "Port owner process:" -ProcessInfo $portOwnerInfo
} else {
    Write-Host "Port owner: none"
}

if ($null -ne $savedPid) {
    $savedInfo = Get-SylphieProcessInfo -ProcessId $savedPid
    if ($null -eq $savedInfo) {
        Write-Host "Saved PID is not running. Removing PID file."
        Remove-Item -LiteralPath $PidPath -ErrorAction SilentlyContinue
    } else {
        $looksLikeSylphie = Test-SylphieProcessSignature `
            -ProcessInfo $savedInfo `
            -Port $ConfiguredPort `
            -PortOwnerPid $portOwnerPid `
            -AllowPortOwnerOnly

        if ($looksLikeSylphie) {
            Stop-SylphiePid -TargetPid $savedPid -Reason "saved PID matched Sylphie signature"
        } elseif ($Force) {
            Write-Warning "Force enabled. Stopping saved PID even though Sylphie signature did not match."
            Stop-SylphiePid -TargetPid $savedPid -Reason "forced saved PID"
        } elseif ($Verbose) {
            Write-Host "Saved PID did not match Sylphie signature."
        }
    }
}

$portOwnerPid = Get-SylphiePortOwnerPid -Port $ConfiguredPort
if ($null -ne $portOwnerPid) {
    $portOwnerInfo = Get-SylphieProcessInfo -ProcessId $portOwnerPid
    $ownerLooksLikeSylphie = Test-SylphieProcessSignature `
        -ProcessInfo $portOwnerInfo `
        -Port $ConfiguredPort `
        -PortOwnerPid $portOwnerPid

    if ($ownerLooksLikeSylphie) {
        Stop-SylphiePid -TargetPid $portOwnerPid -Reason "port owner matched Sylphie signature"
    } elseif ($ForcePortOwner) {
        Write-Warning "ForcePortOwner enabled. Stopping process that owns port $ConfiguredPort."
        Stop-SylphiePid -TargetPid $portOwnerPid -Reason "forced port owner"
    } else {
        Write-Host "Port $ConfiguredPort is still owned by a process that does not look like Sylphie."
        Write-SylphieProcessInfo -Label "Unknown port owner:" -ProcessInfo $portOwnerInfo
        Write-Host "Not stopping it by default. Re-run with -ForcePortOwner if this is intentional."
        exit 1
    }
}

$finalOwnerPid = Get-SylphiePortOwnerPid -Port $ConfiguredPort
if ($null -eq $finalOwnerPid) {
    Remove-Item -LiteralPath $PidPath -ErrorAction SilentlyContinue
    Write-Host "Port $ConfiguredPort is free."
    exit 0
}

Write-Host "Port $ConfiguredPort is still in use by pid $finalOwnerPid."
exit 1
