param(
    [string]$TaskName = "SylphieAgent"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "sylphie_agent_common.ps1")

$ProjectRoot = Get-SylphieProjectRoot
$ExePath = Get-SylphieAgentExePath -ProjectRoot $ProjectRoot
$PipeName = Get-SylphieAgentPipeName

if (-not (Test-Path -LiteralPath $ExePath)) {
    Write-Error "Missing sylphie_agent.exe: $ExePath"
    exit 1
}

if (Test-SylphieAgentPing -ProjectRoot $ProjectRoot) {
    Write-Host "Sylphie agent is already responding."
    & (Join-Path $PSScriptRoot "status_agent.ps1") -TaskName $TaskName
    exit 0
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Error "Scheduled Task not found: $TaskName. Install it with .\scripts\install_agent_task.ps1"
    exit 1
}

Write-Host "Starting Scheduled Task: $TaskName"
Start-ScheduledTask -TaskName $TaskName

if (-not (Wait-SylphieAgentPing -ProjectRoot $ProjectRoot -TimeoutSeconds 5)) {
    Write-Error "Sylphie agent did not respond to ping within 5 seconds."
    Write-SylphieAgentProcesses
    exit 1
}

Write-Host "Sylphie agent started."
Write-Host "Executable: $ExePath"
Write-Host "Pipe: $PipeName"
Write-Host "Log: $(Join-Path $ProjectRoot 'logs\agent.log')"
& (Join-Path $PSScriptRoot "status_agent.ps1") -TaskName $TaskName
