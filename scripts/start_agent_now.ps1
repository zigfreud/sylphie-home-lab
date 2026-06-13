param(
    [string]$TaskName = "SylphieAgent"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "sylphie_agent_common.ps1")

function Test-IsAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

$ProjectRoot = Get-SylphieProjectRoot
$ExePath = Get-SylphieAgentExePath -ProjectRoot $ProjectRoot
$PipeName = Get-SylphieAgentPipeName

if (-not (Test-IsAdministrator)) {
    Write-Error "start_agent_now.ps1 must run elevated so the agent can own hardware safely."
    exit 1
}

if (-not (Test-Path -LiteralPath $ExePath)) {
    Write-Error "Missing sylphie_agent.exe: $ExePath"
    exit 1
}

if (Test-SylphieAgentPing -ProjectRoot $ProjectRoot) {
    Write-Host "Sylphie agent is already responding."
    & (Join-Path $PSScriptRoot "status_agent.ps1") -TaskName $TaskName
    exit 0
}

Write-Host "Starting Sylphie agent manually without enabling autostart."
Start-Process `
    -FilePath $ExePath `
    -ArgumentList @("--pipe", $PipeName) `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden

if (-not (Wait-SylphieAgentPing -ProjectRoot $ProjectRoot -TimeoutSeconds 5)) {
    Write-Error "Sylphie agent did not respond to ping within 5 seconds."
    Write-SylphieAgentProcesses
    exit 1
}

Write-Host "Sylphie agent started manually."
& (Join-Path $PSScriptRoot "status_agent.ps1") -TaskName $TaskName
