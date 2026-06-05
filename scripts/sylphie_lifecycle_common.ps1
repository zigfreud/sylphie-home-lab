$SylphieCommonLoaded = $true

function Get-SylphieProjectRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Get-SylphieSavedUrl {
    param(
        [string]$ProjectRoot,
        [int]$DefaultPort = 8765
    )

    $urlPath = Join-Path $ProjectRoot ".sylphie\server.url"
    if (Test-Path -LiteralPath $urlPath) {
        $url = (Get-Content -LiteralPath $urlPath -Raw).Trim()
        if (-not [string]::IsNullOrWhiteSpace($url)) {
            return $url
        }
    }
    return "http://127.0.0.1:$DefaultPort/"
}

function Get-SylphiePortFromUrl {
    param(
        [string]$Url,
        [int]$DefaultPort = 8765
    )

    try {
        $uri = [Uri]$Url
        if ($uri.Port -gt 0) {
            return [int]$uri.Port
        }
    } catch {
        return $DefaultPort
    }
    return $DefaultPort
}

function Get-SylphieSavedPid {
    param([string]$ProjectRoot)

    $pidPath = Join-Path $ProjectRoot ".sylphie\server.pid"
    if (-not (Test-Path -LiteralPath $pidPath)) {
        return $null
    }

    $pidText = (Get-Content -LiteralPath $pidPath -Raw).Trim()
    if ($pidText -match "^\d+$") {
        return [int]$pidText
    }
    return $null
}

function Get-SylphieProcessInfo {
    param([int]$ProcessId)

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $null
    }

    $commandLine = ""
    try {
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction Stop
        $commandLine = [string]$cim.CommandLine
    } catch {
        $commandLine = ""
    }

    return [pscustomobject]@{
        PID = [int]$ProcessId
        ProcessName = [string]$process.ProcessName
        CommandLine = [string]$commandLine
    }
}

function Get-SylphiePortOwnerPid {
    param([int]$Port)

    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $connection) {
            return [int]$connection.OwningProcess
        }
    } catch {
        return $null
    }
    return $null
}

function Test-SylphieProcessSignature {
    param(
        [object]$ProcessInfo,
        [int]$Port,
        [int]$PortOwnerPid
    )

    if ($null -eq $ProcessInfo) {
        return $false
    }

    $commandLine = [string]$ProcessInfo.CommandLine
    if ($commandLine -match "sylphie_server\.py") {
        return $true
    }
    if ($commandLine -match "sylphie-home-lab") {
        return $true
    }
    if (($commandLine -match [regex]::Escape([string]$Port)) -and ($ProcessInfo.PID -eq $PortOwnerPid)) {
        return $true
    }
    if ($ProcessInfo.PID -eq $PortOwnerPid) {
        return $true
    }

    return $false
}

function Write-SylphieProcessInfo {
    param(
        [string]$Label,
        [object]$ProcessInfo
    )

    if ($null -eq $ProcessInfo) {
        Write-Host "$Label none"
        return
    }

    Write-Host "$Label"
    Write-Host ("  PID: {0}" -f $ProcessInfo.PID)
    Write-Host ("  ProcessName: {0}" -f $ProcessInfo.ProcessName)
    Write-Host ("  CommandLine: {0}" -f $ProcessInfo.CommandLine)
}

function Wait-SylphiePortOwnerPid {
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 5
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $ownerPid = Get-SylphiePortOwnerPid -Port $Port
        if ($null -ne $ownerPid) {
            return $ownerPid
        }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)

    return $null
}
