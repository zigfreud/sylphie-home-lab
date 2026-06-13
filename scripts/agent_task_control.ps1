param(
    [ValidateSet("status", "install", "enable", "disable", "uninstall", "start-now", "stop")]
    [string]$Action = "status",
    [string]$TaskName = "SylphieAgent",
    [switch]$EnableAutostart,
    [switch]$StopAgent
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "sylphie_agent_common.ps1")

function Test-IsAdministrator {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-AgentStatusObject {
    param(
        [string]$ProjectRoot,
        [string]$TaskName
    )

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $processes = @(Get-SylphieAgentProcesses)
    $pingOk = $false
    $agentState = $null
    $agentError = $null

    try {
        $statusRaw = Invoke-SylphieAgentClient -ProjectRoot $ProjectRoot -Arguments @("status") -TimeoutSeconds 2
        $status = $statusRaw | ConvertFrom-Json
        $pingOk = [bool]$status.ok
        $agentState = $status.response.state
    } catch {
        $agentError = $_.Exception.Message
    }

    $taskInfo = $null
    if ($null -ne $task) {
        $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    }

    return [pscustomobject]@{
        ok = $true
        captured_at = (Get-Date).ToString("o")
        task_name = $TaskName
        task_exists = $null -ne $task
        task_enabled = ($null -ne $task -and $task.State -ne "Disabled")
        task_state = $(if ($null -ne $task) { [string]$task.State } else { "not_installed" })
        task_last_run_time = $(if ($null -ne $taskInfo) { $taskInfo.LastRunTime.ToString("o") } else { $null })
        task_last_result = $(if ($null -ne $taskInfo) { $taskInfo.LastTaskResult } else { $null })
        running = ($pingOk -or $processes.Count -gt 0)
        agent_process_running = ($pingOk -or $processes.Count -gt 0)
        pipe_responding = $pingOk
        task_running = ($null -ne $task -and $task.State -eq "Running")
        pids = @($processes | ForEach-Object { $_.ProcessId })
        elevated = $(if ($null -ne $agentState) { [bool]$agentState.is_elevated } else { $null })
        agent_ping = $pingOk
        agent_state = $agentState
        agent_error = $agentError
    }
}

$ProjectRoot = Get-SylphieProjectRoot

if ($Action -eq "status") {
    Get-AgentStatusObject -ProjectRoot $ProjectRoot -TaskName $TaskName | ConvertTo-Json -Depth 8
    exit 0
}

if (-not (Test-IsAdministrator)) {
    Write-Error "agent_task_control.ps1 action '$Action' must run elevated."
    exit 1
}

if ($Action -eq "install") {
    $installArgs = @("-TaskName", $TaskName)
    if ($EnableAutostart) {
        $installArgs += "-EnableAutostart"
    }
    & (Join-Path $PSScriptRoot "install_agent_task.ps1") @installArgs
} elseif ($Action -eq "enable") {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        throw "Scheduled Task not found: $TaskName"
    }
    Enable-ScheduledTask -TaskName $TaskName | Out-Null
    Write-Host "Enabled Sylphie agent autostart: $TaskName"
} elseif ($Action -eq "disable") {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        Write-Host "Scheduled Task not found: $TaskName"
    } else {
        Disable-ScheduledTask -TaskName $TaskName | Out-Null
        Write-Host "Disabled Sylphie agent autostart: $TaskName"
    }
} elseif ($Action -eq "uninstall") {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($StopAgent -and $null -ne $task -and $task.State -eq "Running") {
        & (Join-Path $PSScriptRoot "stop_agent.ps1") -TaskName $TaskName
    }
    & (Join-Path $PSScriptRoot "uninstall_agent_task.ps1") -TaskName $TaskName
} elseif ($Action -eq "start-now") {
    & (Join-Path $PSScriptRoot "start_agent_now.ps1") -TaskName $TaskName
} elseif ($Action -eq "stop") {
    & (Join-Path $PSScriptRoot "stop_agent.ps1") -TaskName $TaskName
}

Get-AgentStatusObject -ProjectRoot $ProjectRoot -TaskName $TaskName | ConvertTo-Json -Depth 8
