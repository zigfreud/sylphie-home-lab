param(
    [string]$TaskName = "SylphieAgent"
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Scheduled Task not found: $TaskName"
    exit 0
}

if ($task.State -eq "Running") {
    Write-Host "Stopping Scheduled Task: $TaskName"
    Stop-ScheduledTask -TaskName $TaskName
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Uninstalled Scheduled Task: $TaskName"
