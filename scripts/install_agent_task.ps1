param(
    [string]$TaskName = "SylphieAgent"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "sylphie_agent_common.ps1")

$ProjectRoot = Get-SylphieProjectRoot
$ExePath = Get-SylphieAgentExePath -ProjectRoot $ProjectRoot
$PipeName = Get-SylphieAgentPipeName

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
    -DisallowStartIfOnBatteries:$false `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Sylphie Home Lab elevated hardware agent" `
    -Force | Out-Null

Write-Host "Installed Scheduled Task: $TaskName"
Write-Host "Run level: highest privileges"
Write-Host "User: $user"
Write-Host "Executable: $ExePath"
Write-Host "Working directory: $ProjectRoot"
Write-Host "Pipe: $PipeName"
Write-Host ""
Write-Host "Start it with:"
Write-Host ".\scripts\start_agent.ps1"
