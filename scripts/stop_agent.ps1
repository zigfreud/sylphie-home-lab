param(
    [string]$TaskName = "SylphieAgent"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "sylphie_agent_common.ps1")

$ProjectRoot = Get-SylphieProjectRoot

Write-Host "Stopping Sylphie agent"

if (Test-SylphieAgentPing -ProjectRoot $ProjectRoot) {
    try {
        Write-Host "Requesting shutdown over IPC..."
        Invoke-SylphieAgentClient -ProjectRoot $ProjectRoot -Arguments @("shutdown") -TimeoutSeconds 3 | Write-Host
        Start-Sleep -Milliseconds 700
    } catch {
        Write-Warning ("IPC shutdown failed: {0}" -f $_.Exception.Message)
    }
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $task -and $task.State -eq "Running") {
    Write-Host "Stopping Scheduled Task: $TaskName"
    Stop-ScheduledTask -TaskName $TaskName
    Start-Sleep -Milliseconds 700
}

$processes = Get-SylphieAgentProcesses
foreach ($process in $processes) {
    if ($process.Name -ne "sylphie_agent.exe") {
        continue
    }

    Write-Host ("Stopping remaining sylphie_agent.exe PID {0}" -f $process.ProcessId)
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

if (Test-SylphieAgentPing -ProjectRoot $ProjectRoot) {
    Write-Error "Sylphie agent is still responding after stop attempt."
    exit 1
}

Write-Host "Sylphie agent stopped."
