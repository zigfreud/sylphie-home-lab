$SylphieAgentCommonLoaded = $true

function Get-SylphieProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-SylphieAgentExePath {
    param([string]$ProjectRoot)
    return Join-Path $ProjectRoot "bin\sylphie_agent.exe"
}

function Get-SylphieAgentPipeName {
    return "\\.\pipe\sylphie-hw"
}

function Invoke-SylphieAgentClient {
    param(
        [string]$ProjectRoot,
        [string[]]$Arguments,
        [int]$TimeoutSeconds = 5
    )

    $exe = Get-SylphieAgentExePath -ProjectRoot $ProjectRoot
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "Missing sylphie_agent.exe: $exe"
    }

    $job = Start-Job -ScriptBlock {
        param($ExePath, $ClientArguments)
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $ExePath
        $psi.Arguments = '--pipe "\\.\pipe\sylphie-hw" --client ' + ($ClientArguments -join ' ')
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $process = [System.Diagnostics.Process]::Start($psi)
        $stdout = $process.StandardOutput.ReadToEnd()
        $stderr = $process.StandardError.ReadToEnd()
        $process.WaitForExit()
        $output = ($stdout + $stderr).Trim()
        [pscustomobject]@{
            ExitCode = $process.ExitCode
            Output = $output
        }
    } -ArgumentList $exe, $Arguments

    if (-not (Wait-Job -Job $job -Timeout $TimeoutSeconds)) {
        Stop-Job -Job $job -Force -ErrorAction SilentlyContinue
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        throw "Timed out waiting for sylphie_agent.exe client response"
    }

    $result = Receive-Job -Job $job
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    if ($null -eq $result) {
        throw "sylphie_agent.exe client returned no result"
    }
    if ($result.ExitCode -ne 0) {
        throw $result.Output
    }
    return ([string]$result.Output).Trim()
}

function Test-SylphieAgentPing {
    param([string]$ProjectRoot)

    try {
        $response = Invoke-SylphieAgentClient -ProjectRoot $ProjectRoot -Arguments @("ping") -TimeoutSeconds 2
        return (-not [string]::IsNullOrWhiteSpace($response))
    } catch {
        return $false
    }
}

function Wait-SylphieAgentPing {
    param(
        [string]$ProjectRoot,
        [int]$TimeoutSeconds = 5
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-SylphieAgentPing -ProjectRoot $ProjectRoot) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Get-SylphieAgentProcesses {
    try {
        return Get-CimInstance Win32_Process -Filter "Name = 'sylphie_agent.exe'" -ErrorAction SilentlyContinue
    } catch {
        return @()
    }
}

function Write-SylphieAgentProcesses {
    $processes = Get-SylphieAgentProcesses
    if ($null -eq $processes -or $processes.Count -eq 0) {
        Write-Host "Agent process: none"
        return
    }

    foreach ($process in $processes) {
        Write-Host ("Agent process PID: {0}" -f $process.ProcessId)
        Write-Host ("CommandLine: {0}" -f $process.CommandLine)
    }
}
