param(
    [string]$TaskName = "SylphieAgent",
    [switch]$EnableAutostart
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
    Write-Error "install_agent_task.ps1 must be run from an elevated PowerShell because the SylphieAgent task uses highest privileges. Open PowerShell as Administrator, cd to the project root, then run .\scripts\install_agent_task.ps1"
    exit 1
}

if (-not (Test-Path -LiteralPath $ExePath)) {
    Write-Error "Cannot install Scheduled Task because sylphie_agent.exe was not found: $ExePath"
    exit 1
}

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction `
    -Execute $ExePath `
    -Argument "--pipe `"$PipeName`"" `
    -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal `
    -UserId $user `
    -LogonType Interactive `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Sylphie Home Lab elevated hardware agent" `
    -Force | Out-Null

if ($EnableAutostart) {
    Enable-ScheduledTask -TaskName $TaskName | Out-Null
} else {
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
}

Write-Host "Installed Scheduled Task: $TaskName"
Write-Host "Run level: highest privileges"
Write-Host ("Autostart: {0}" -f ($(if ($EnableAutostart) { "enabled" } else { "disabled" })))
Write-Host "User: $user"
Write-Host "Executable: $ExePath"
Write-Host "Working directory: $ProjectRoot"
Write-Host "Pipe: $PipeName"
Write-Host ""
Write-Host "Start it with:"
Write-Host ".\scripts\start_agent.ps1"
