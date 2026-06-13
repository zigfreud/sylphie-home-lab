param(
    [ValidateSet("restart-lighting", "restart-stack", "restore-logitech-lamparray")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "sylphie_agent_common.ps1")

function Write-ArmouryActionLog {
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
            Write-ArmouryActionLog "Launching Armoury path: $candidate"
            Start-Process -FilePath $candidate -ErrorAction SilentlyContinue
            return
        }
    }
    Write-ArmouryActionLog "Armoury launch path not found."
}

$ProjectRoot = Get-SylphieProjectRoot
$script:LogPath = Join-Path $ProjectRoot "logs\armoury_actions.log"

try {
    Write-ArmouryActionLog "action=$Action started"
    if ($Action -eq "restart-lighting") {
        $svc = Get-Service -Name "LightingService" -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Write-ArmouryActionLog "LightingService not found"
        } else {
            Restart-Service -Name "LightingService" -Force
            Write-ArmouryActionLog ("LightingService status=" + (Get-Service -Name "LightingService").Status)
        }
    } elseif ($Action -eq "restart-stack") {
        $svc = Get-Service -Name "LightingService" -ErrorAction SilentlyContinue
        if ($null -ne $svc -and $svc.Status -ne "Stopped") {
            Stop-Service -Name "LightingService" -Force
            $svc.WaitForStatus("Stopped", (New-TimeSpan -Seconds 10))
            Write-ArmouryActionLog "LightingService stopped"
        }
        Start-Service -Name "LightingService" -ErrorAction SilentlyContinue
        Write-ArmouryActionLog "LightingService start requested"
        Start-ArmouryIfKnown
    } elseif ($Action -eq "restore-logitech-lamparray") {
        $svc = Get-Service -Name "logi_lamparray_service" -ErrorAction SilentlyContinue
        if ($null -eq $svc) {
            Write-ArmouryActionLog "logi_lamparray_service not found"
        } else {
            Set-Service -Name "logi_lamparray_service" -StartupType Automatic
            Start-Service -Name "logi_lamparray_service"
            Write-ArmouryActionLog ("logi_lamparray_service status=" + (Get-Service -Name "logi_lamparray_service").Status)
        }
    }
    Write-ArmouryActionLog "action=$Action completed"
} catch {
    Write-ArmouryActionLog ("action=$Action ERROR " + $_.Exception.Message)
    exit 1
}
