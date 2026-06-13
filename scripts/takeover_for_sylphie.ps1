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

    $stateDir = Join-Path $ProjectRoot ".sylphie"
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    [pscustomobject]@{
        mode = "sylphie"
        reason = "takeover-for-sylphie completed"
        include_armoury_core = [bool]$IncludeArmouryCore
        updated_at = (Get-Date).ToString("o")
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $stateDir "ownership_mode.json") -Encoding UTF8

    Write-OwnershipLog "takeover-for-sylphie completed"
} catch {
    Write-OwnershipLog ("takeover-for-sylphie ERROR " + $_.Exception.Message)
    exit 1
}
