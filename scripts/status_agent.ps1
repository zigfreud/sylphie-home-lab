param(
    [string]$TaskName = "SylphieAgent"
)

. (Join-Path $PSScriptRoot "sylphie_agent_common.ps1")

$ProjectRoot = Get-SylphieProjectRoot
$ExePath = Get-SylphieAgentExePath -ProjectRoot $ProjectRoot
$PipeName = Get-SylphieAgentPipeName
$LogPath = Join-Path $ProjectRoot "logs\agent.log"

Write-Host "Sylphie agent status"
Write-Host "Executable: $ExePath"
Write-Host "Pipe: $PipeName"
Write-Host "Log: $LogPath"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Scheduled Task: not installed"
} else {
    Write-Host ("Scheduled Task: {0}" -f $task.TaskName)
    Write-Host ("Task State: {0}" -f $task.State)
}

Write-SylphieAgentProcesses

try {
    $ping = Invoke-SylphieAgentClient -ProjectRoot $ProjectRoot -Arguments @("ping") -TimeoutSeconds 2
    Write-Host "Ping: ok"
    Write-Host $ping

    $status = Invoke-SylphieAgentClient -ProjectRoot $ProjectRoot -Arguments @("status") -TimeoutSeconds 2
    Write-Host "Status:"
    Write-Host $status

    $takeover = Invoke-SylphieAgentClient -ProjectRoot $ProjectRoot -Arguments @("takeover-check") -TimeoutSeconds 5
    Write-Host "Takeover check:"
    Write-Host $takeover
} catch {
    Write-Host ("Ping/status failed: {0}" -f $_.Exception.Message)
}
