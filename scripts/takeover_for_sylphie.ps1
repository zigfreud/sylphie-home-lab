param(
    [string]$TaskName = "SylphieAgent",
    [switch]$IncludeArmouryCore
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "sylphie_agent_common.ps1")

function Write-OwnershipLog {
    param([string]$Message)
    $line = ("{0} {1}" -f (Get-Date).ToString("o"), $Message)
    Add-Content -LiteralPath $script:LogPath -Value $line
    Write-Host $Message
}

$ProjectRoot = Get-SylphieProjectRoot
$script:LogPath = Join-Path $ProjectRoot "logs\ownership_actions.log"
$RgbExe = Join-Path $ProjectRoot "bin\sylphie_rgb.exe"

Write-OwnershipLog "takeover-for-sylphie started"

try {
    if (-not (Test-Path -LiteralPath $RgbExe)) {
        throw "Missing sylphie_rgb.exe: $RgbExe"
    }

    Write-OwnershipLog "Executing takeover; LightingService is stopped first by the native takeover flow"
    $takeoverArgs = @("takeover", "--execute", "--i-accept-stopping-lighting-services")
    if ($IncludeArmouryCore) {
        $takeoverArgs += "--include-armoury-core"
    }
    & $RgbExe @takeoverArgs | ForEach-Object { Write-OwnershipLog $_ }

    Write-OwnershipLog "Starting Sylphie agent manually without enabling autostart"
    & (Join-Path $PSScriptRoot "start_agent_now.ps1") -TaskName $TaskName | ForEach-Object { Write-OwnershipLog $_ }

    Write-OwnershipLog "Running read-only doctor"
    & $RgbExe doctor | ForEach-Object { Write-OwnershipLog $_ }

    Write-OwnershipLog "Running read-only bus-status"
    & $RgbExe bus-status | ForEach-Object { Write-OwnershipLog $_ }

    $takeoverStatePath = Join-Path $ProjectRoot ".sylphie\takeover_state.json"
    $takeoverState = $null
    if (Test-Path -LiteralPath $takeoverStatePath) {
        $takeoverState = Get-Content -LiteralPath $takeoverStatePath -Raw | ConvertFrom-Json
    }
    $stoppedCount = @($takeoverState.stopped_services).Count
    $terminatedCount = @($takeoverState.terminated_process_pids).Count

    $tier1Services = @("LightingService", "Aura Wallpaper Service")
    $tier2Services = @("ArmouryCrateService", "ArmouryCrate.Service", "asComSvc")
    $tier1Processes = @("LightingService", "AuraWallpaperService", "ArmourySocketServer", "ArmourySwAgent", "ArmouryHtmlDebugServer", "OpenRGB", "OpenAuraSDK")
    $tier2Processes = @("ArmouryCrate", "ArmouryCrate.Service", "ArmouryCrate.UserSessionHelper", "asus_framework")
    $runningTier1Services = @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object { ($tier1Services -contains $_.Name -or $tier1Services -contains $_.DisplayName) -and ($_.State -eq "Running" -or $_.ProcessId -gt 0) })
    $runningTier2Services = @(Get-CimInstance Win32_Service -ErrorAction SilentlyContinue | Where-Object { ($tier2Services -contains $_.Name -or $tier2Services -contains $_.DisplayName) -and ($_.State -eq "Running" -or $_.ProcessId -gt 0) })
    $runningTier1Processes = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $tier1Processes -contains $_.ProcessName })
    $runningTier2Processes = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $tier2Processes -contains $_.ProcessName })
    $ownershipAlreadyClean = ($runningTier1Services.Count + $runningTier2Services.Count + $runningTier1Processes.Count + $runningTier2Processes.Count) -eq 0

    $ownershipMode = if (($stoppedCount + $terminatedCount) -eq 0 -and $ownershipAlreadyClean) {
        "sylphie_candidate"
    } elseif (($stoppedCount + $terminatedCount) -eq 0) {
        "takeover_noop"
    } elseif ($IncludeArmouryCore) {
        "sylphie_candidate"
    } else {
        "soft_takeover"
    }
    $ownershipReason = if (($stoppedCount + $terminatedCount) -eq 0 -and $ownershipAlreadyClean) {
        "takeover-for-sylphie found ownership already clean"
    } elseif ($ownershipMode -eq "takeover_noop") {
        "takeover-for-sylphie made no changes"
    } elseif ($ownershipMode -eq "sylphie_candidate") {
        "full takeover completed; visual sanity test still required for verified mode"
    } else {
        "soft takeover completed; Armoury core may still be running"
    }

    $stateDir = Join-Path $ProjectRoot ".sylphie"
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    [pscustomobject]@{
        mode = $ownershipMode
        reason = $ownershipReason
        include_armoury_core = [bool]$IncludeArmouryCore
        stopped_services = $stoppedCount
        terminated_process_pids = $terminatedCount
        ownership_already_clean = $ownershipAlreadyClean
        updated_at = (Get-Date).ToString("o")
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $stateDir "ownership_mode.json") -Encoding UTF8

    if (($stoppedCount + $terminatedCount) -eq 0 -and $ownershipAlreadyClean) {
        Write-OwnershipLog "No changes required; ownership already clean."
        Write-OwnershipLog "Ownership is clean. Run direct sanity test to verify visual control."
    } elseif ($ownershipMode -eq "takeover_noop") {
        Write-OwnershipLog "Takeover made no changes"
        if (($runningTier2Services.Count + $runningTier2Processes.Count) -gt 0) {
            Write-OwnershipLog "Armoury core still running"
        }
        Write-OwnershipLog "RGB writes remain blocked until full takeover or manual override"
    }
    Write-OwnershipLog ("takeover-for-sylphie completed mode=" + $ownershipMode)
} catch {
    Write-OwnershipLog ("takeover-for-sylphie ERROR " + $_.Exception.Message)
    exit 1
}
