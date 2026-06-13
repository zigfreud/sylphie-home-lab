param(
    [switch]$DisableAutostart,
    [switch]$LaunchArmoury,
    [string]$TaskName = "SylphieAgent"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "sylphie_agent_common.ps1")

function Write-OwnershipLog {
    param([string]$Message)
    $line = ("{0} {1}" -f (Get-Date).ToString("o"), $Message)
    Add-Content -LiteralPath $script:LogPath -Value $line
    Write-Host $Message
}

function Start-ArmouryIfKnown {
    $candidates = @(
        (Join-Path $env:ProgramFiles "ASUS\ARMOURY CRATE Service\ArmouryCrate.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "ASUS\ARMOURY CRATE Service\ArmouryCrate.exe"),
        (Join-Path $env:ProgramFiles "ASUS\ARMOURY CRATE Service\ArmouryCrate.UserSessionHelper.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "ASUS\ARMOURY CRATE Service\ArmouryCrate.UserSessionHelper.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            Write-OwnershipLog "Launching Armoury path: $candidate"
            Start-Process -FilePath $candidate -ErrorAction SilentlyContinue
            return $candidate
        }
    }

    Write-OwnershipLog "Armoury launch path not found."
    return $null
}

$ProjectRoot = Get-SylphieProjectRoot
$script:LogPath = Join-Path $ProjectRoot "logs\ownership_actions.log"

Write-OwnershipLog "return-to-armoury started"

try {
    & (Join-Path $PSScriptRoot "stop_agent.ps1") -TaskName $TaskName

    if ($DisableAutostart) {
        & (Join-Path $PSScriptRoot "agent_task_control.ps1") -Action disable -TaskName $TaskName
    }

    $rgbExe = Join-Path $ProjectRoot "bin\sylphie_rgb.exe"
    if (Test-Path -LiteralPath $rgbExe) {
        Write-OwnershipLog "Restoring services recorded by Sylphie takeover state"
        & $rgbExe restore-services | ForEach-Object { Write-OwnershipLog $_ }
    } else {
        Write-OwnershipLog "sylphie_rgb.exe not found; skipping restore-services"
    }

    $lighting = Get-Service -Name "LightingService" -ErrorAction SilentlyContinue
    if ($null -ne $lighting) {
        Write-OwnershipLog "Starting LightingService"
        Start-Service -Name "LightingService" -ErrorAction SilentlyContinue
    } else {
        Write-OwnershipLog "LightingService not found"
    }

    $launched = $null
    if ($LaunchArmoury) {
        $launched = Start-ArmouryIfKnown
    }

    $health = [pscustomobject]@{
        ok = $true
        action = "return-to-armoury"
        captured_at = (Get-Date).ToString("o")
        disable_autostart = [bool]$DisableAutostart
        launch_armoury = [bool]$LaunchArmoury
        launched_armoury_path = $launched
        lighting_service = Get-CimInstance Win32_Service -Filter "Name='LightingService'" -ErrorAction SilentlyContinue
        agent_task = (& (Join-Path $PSScriptRoot "agent_task_control.ps1") -Action status -TaskName $TaskName | ConvertFrom-Json)
    }
    Write-OwnershipLog ($health | ConvertTo-Json -Depth 8)
    Write-OwnershipLog "return-to-armoury completed"
} catch {
    Write-OwnershipLog ("return-to-armoury ERROR " + $_.Exception.Message)
    exit 1
}
