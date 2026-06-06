param(
    [ValidateSet("gui-cold-launch", "service-only")]
    [string]$Mode = "gui-cold-launch",
    [int]$CaptureSeconds = 120,
    [int]$PostStartObserveSeconds = 60,
    [int]$StackStopSettleSeconds = 3,
    [switch]$NoPayloadCapture,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-Log {
    param([string]$Message)
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Message
    Write-Host $line
    Add-Content -LiteralPath $AutomationLog -Value $line -Encoding UTF8
}

function Add-Marker {
    param(
        [string]$Marker,
        [string]$Note = ""
    )
    $suffix = if ($Note) { " note=$Note" } else { "" }
    $line = "{0} MARKER {1}{2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Marker, $suffix
    Add-Content -LiteralPath $MarkerLog -Value $line -Encoding UTF8
    Write-Log $line
}

function Get-StackSnapshot {
    $services = foreach ($name in $ServiceWhitelist) {
        $svc = Get-CimInstance Win32_Service -Filter ("Name='{0}'" -f $name.Replace("'", "''")) -ErrorAction SilentlyContinue
        if ($null -ne $svc) {
            [pscustomobject]@{
                name = $svc.Name
                state = $svc.State
                start_mode = $svc.StartMode
                process_id = $svc.ProcessId
                account = $svc.StartName
                path = $svc.PathName
            }
        }
    }

    $processes = foreach ($name in $ProcessWhitelist) {
        Get-CimInstance Win32_Process -Filter ("Name='{0}.exe'" -f $name.Replace("'", "''")) -ErrorAction SilentlyContinue |
            ForEach-Object {
                [pscustomobject]@{
                    name = $_.Name
                    pid = $_.ProcessId
                    command_line = $_.CommandLine
                }
            }
    }

    [pscustomobject]@{
        services = @($services)
        processes = @($processes)
    }
}

function Wait-ServiceStopped {
    param(
        [string]$Name,
        [int]$TimeoutSeconds = 10
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $svc = Get-CimInstance Win32_Service -Filter ("Name='{0}'" -f $Name.Replace("'", "''")) -ErrorAction SilentlyContinue
        if ($null -eq $svc -or $svc.State -eq "Stopped") {
            return $true
        }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Stop-ServiceIfPresent {
    param([string]$Name)
    $svc = Get-CimInstance Win32_Service -Filter ("Name='{0}'" -f $Name.Replace("'", "''")) -ErrorAction SilentlyContinue
    if ($null -eq $svc) {
        Write-Log "service $Name not found"
        return $false
    }
    if ($svc.State -eq "Stopped") {
        Write-Log "service $Name already stopped"
        return $false
    }

    Write-Log "stopping service $Name"
    Stop-Service -Name $Name -Force -ErrorAction Stop
    if (-not (Wait-ServiceStopped -Name $Name -TimeoutSeconds 10)) {
        Write-Log "ERROR service $Name did not stop within 10s"
    }
    return $true
}

function Stop-WhitelistedProcesses {
    foreach ($name in $ProcessWhitelist) {
        $processes = Get-CimInstance Win32_Process -Filter ("Name='{0}.exe'" -f $name.Replace("'", "''")) -ErrorAction SilentlyContinue
        foreach ($process in @($processes)) {
            Write-Log ("terminating whitelisted process {0} pid={1}" -f $process.Name, $process.ProcessId)
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}

function Find-ArmouryLaunchTarget {
    $programFilesX86 = [Environment]::GetFolderPath("ProgramFilesX86")
    $candidates = @(
        "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\ARMOURY CRATE.lnk",
        "$env:ProgramData\Microsoft\Windows\Start Menu\Programs\Armoury Crate.lnk",
        "$env:ProgramFiles\ASUS\ARMOURY CRATE Service\ArmouryCrate.exe",
        "$env:ProgramFiles\ASUS\ARMOURY CRATE Service\ArmouryCrate.UserSessionHelper.exe",
        "$programFilesX86\ASUS\ARMOURY CRATE Service\ArmouryCrate.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return $null
}

function Read-Continue {
    param([string]$Prompt)
    if ($NonInteractive) {
        Write-Log "non-interactive skip prompt: $Prompt"
        return
    }
    Read-Host $Prompt | Out-Null
}

function Select-RelevantEvents {
    param([string]$LogPath)
    if (-not (Test-Path -LiteralPath $LogPath)) {
        return @()
    }
    $patterns = @(
        "AURA read CMD=0x81",
        "AURA read CMD=0x90",
        "AURA select_register 0x8000",
        "AURA block_write last_selected_register=0x8000",
        "AURA block_write",
        "payload_reads",
        "d1_hint_register=0x8000",
        "d1_hint_register=0x80A0",
        "d1_hint_register=0x80F1",
        "d1_hint_register=0x8023",
        "d1_hint_register=0x8022",
        "value=0xFE"
    )
    Get-Content -LiteralPath $LogPath -ErrorAction SilentlyContinue |
        Where-Object {
            $line = $_
            foreach ($pattern in $patterns) {
                if ($line -like "*$pattern*") {
                    return $true
                }
            }
            return $false
        }
}

function Write-SanitizedSummary {
    $date = Get-Date -Format "yyyyMMdd"
    $summaryPath = Join-Path $ResearchDir "${date}_armoury_cold_start_summary.md"
    $events = @(Select-RelevantEvents -LogPath $MasterLog)
    $markers = if (Test-Path -LiteralPath $MarkerLog) { @(Get-Content -LiteralPath $MarkerLog) } else { @() }
    $payloads = $events | Where-Object { $_ -like "*payload_reads*" }
    $block8000 = $events | Where-Object { $_ -like "*last_selected_register=0x8000*" }

    $content = New-Object System.Collections.Generic.List[string]
    $content.Add("# Armoury Cold-Start Capture Summary - $date")
    $content.Add("")
    $content.Add('Raw captures remain local under `research/captures/` and are not committed.')
    $content.Add("")
    $content.Add("## Run")
    $content.Add("")
    $content.Add("- timestamp: " + '`' + $Stamp + '`')
    $content.Add("- mode: " + '`' + $Mode + '`')
    $content.Add("- uac_observed: unknown")
    $content.Add("- master_log: " + '`' + $MasterLog + '`')
    $content.Add("- marker_log: " + '`' + $MarkerLog + '`')
    $content.Add("")
    $content.Add("## Stack Stop")
    $content.Add("")
    $content.Add("- stopped_services: " + (($StoppedServices -join ", ") -replace "^$", "none"))
    $content.Add("- terminated_processes: " + (($TerminatedProcesses -join ", ") -replace "^$", "none"))
    $content.Add("- AsusCertService: warning-only, not stopped by this script")
    $content.Add("")
    $content.Add("## Markers")
    $content.Add("")
    foreach ($marker in $markers) {
        $content.Add("- " + '`' + $marker + '`')
    }
    $content.Add("")
    $content.Add("## Relevant SMBus Events")
    $content.Add("")
    if ($events.Count -eq 0) {
        $content.Add("- No relevant decoded SMBus events found in the master log.")
    } else {
        foreach ($event in $events) {
            $content.Add("- " + '`' + $event + '`')
        }
    }
    $content.Add("")
    $content.Add("## Payloads")
    $content.Add("")
    if ($payloads.Count -eq 0) {
        $content.Add("- No block payloads captured.")
    } else {
        foreach ($payload in $payloads) {
            $content.Add("- " + '`' + $payload + '`')
        }
    }
    $content.Add("")
    $content.Add("## 0x8000 Result")
    $content.Add("")
    if ($block8000.Count -eq 0) {
        $content.Add('- `block_write last_selected_register=0x8000 len=3` was not captured in this run.')
    } else {
        foreach ($item in $block8000) {
            $content.Add("- " + '`' + $item + '`')
        }
    }
    $content.Add("")
    $content.Add("## Recover-Full Hypothesis")
    $content.Add("")
    $content.Add('- Do not alter normal RGB writes: `0x8101`, payload `R G B`.')
    $content.Add('- Avoid `0x8100` and `0x8160`.')
    $content.Add('- Use captured service rearm events only after the `0x8000 len=3` payload is confirmed.')
    $content.Add('- Candidate rearm registers remain `0x8000`, `0x80A0`, `0x80F1`, `0x8023`, and `0x8022`.')

    $content | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    Write-Log "sanitized summary written: $summaryPath"
}

if (-not (Test-IsAdmin)) {
    throw "capture_armoury_cold_start.ps1 must run as Administrator so it can stop LightingService before killing whitelisted processes."
}

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Probe = Join-Path $Root "bin\sylphie_piix4_armoury_ui_capture.exe"
$CaptureDir = Join-Path $Root "research\captures"
$ResearchDir = Join-Path $Root "docs\research"
$StateDir = Join-Path $Root ".sylphie"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$MasterLog = Join-Path $CaptureDir "armoury_cold_start_${Stamp}_master.log"
$MarkerLog = Join-Path $CaptureDir "armoury_cold_start_${Stamp}_markers.log"
$AutomationLog = Join-Path $CaptureDir "armoury_cold_start_${Stamp}_automation.log"
$StatePath = Join-Path $StateDir "capture_cold_start_state.json"
$StoppedServices = New-Object System.Collections.Generic.List[string]
$TerminatedProcesses = New-Object System.Collections.Generic.List[string]

$ServiceWhitelist = @(
    "LightingService",
    "ArmouryCrate.Service",
    "ArmouryCrate.UserSessionHelper",
    "ArmourySocketServer",
    "ArmourySwAgent",
    "ArmouryHtmlDebugServer",
    "Aura"
)

$ProcessWhitelist = @(
    "ArmouryCrate",
    "ArmouryCrate.UserSessionHelper",
    "ArmourySocketServer",
    "ArmourySwAgent",
    "ArmouryHtmlDebugServer",
    "asus_framework",
    "LightingService",
    "Aura",
    "OpenRGB",
    "OpenAuraSDK"
)

if (-not (Test-Path -LiteralPath $Probe)) {
    throw "Missing probe executable: $Probe. Build it with tools\probes\build_armoury_ui_capture.bat"
}

New-Item -ItemType Directory -Force -Path $CaptureDir, $ResearchDir, $StateDir | Out-Null

Write-Log "starting Armoury cold-start capture mode=$Mode"
Write-Log "root=$Root"
Write-Log "master_log=$MasterLog"
Write-Log "marker_log=$MarkerLog"
Write-Log "probe is read-only; SMBus writes are not performed by the probe"

try {
    Write-Log "stopping Sylphie server and agent"
    & (Join-Path $Root "scripts\stop_sylphie.ps1") -ForcePortOwner | ForEach-Object { Write-Log "stop_sylphie: $_" }
    & (Join-Path $Root "scripts\stop_agent.ps1") | ForEach-Object { Write-Log "stop_agent: $_" }
} catch {
    Write-Log "warning stopping Sylphie runtime: $($_.Exception.Message)"
}

Write-Log "close dashboard/browser tabs if they are still open"
Read-Continue "Close dashboard/browser tabs if needed, then press Enter to start the probe"

$probeArgs = @("--base", "0B20", "--output", $MasterLog, "--segment-logs", "--duration-seconds", [string]$CaptureSeconds)
if (-not $NoPayloadCapture) {
    $probeArgs += "--capture-block-payload"
}
$ProbeProcess = Start-Process -FilePath $Probe -ArgumentList $probeArgs -WorkingDirectory $Root -PassThru -WindowStyle Hidden
@{
    type = "armoury-cold-start"
    mode = $Mode
    pid = $ProbeProcess.Id
    log = $MasterLog
    marker_log = $MarkerLog
    automation_log = $AutomationLog
    started_at = (Get-Date).ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath $StatePath -Encoding UTF8
Add-Marker "CAPTURE_STARTED" "pid=$($ProbeProcess.Id)"

Write-Log "capturing before stack stop"
$before = Get-StackSnapshot
$before | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $CaptureDir "armoury_cold_start_${Stamp}_stack_before.json") -Encoding UTF8

Add-Marker "STACK_STOP_BEGIN"
$lightingStopped = Stop-ServiceIfPresent "LightingService"
if ($lightingStopped) {
    $StoppedServices.Add("LightingService")
}
if (Wait-ServiceStopped -Name "LightingService" -TimeoutSeconds 10) {
    Add-Marker "SERVICE_STOPPED" "FULL_STACK_STOPPED_LIGHTINGSERVICE"
} else {
    Add-Marker "SERVICE_STOP_TIMEOUT" "LightingService"
}

foreach ($service in $ServiceWhitelist) {
    if ($service -eq "LightingService") {
        continue
    }
    if (Stop-ServiceIfPresent $service) {
        $StoppedServices.Add($service)
    }
}

Start-Sleep -Seconds 1
$preKillProcesses = @(foreach ($name in $ProcessWhitelist) {
    Get-CimInstance Win32_Process -Filter ("Name='{0}.exe'" -f $name.Replace("'", "''")) -ErrorAction SilentlyContinue
})
Stop-WhitelistedProcesses
foreach ($process in $preKillProcesses) {
    $TerminatedProcesses.Add(("{0} pid={1}" -f $process.Name, $process.ProcessId))
}

$afterStop = Get-StackSnapshot
$afterStop | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $CaptureDir "armoury_cold_start_${Stamp}_stack_after_stop.json") -Encoding UTF8
Add-Marker "STACK_STOPPED" "FULL_STACK_STOPPED"

Write-Log "settling after full stack stop for $StackStopSettleSeconds seconds"
Start-Sleep -Seconds $StackStopSettleSeconds

if ($Mode -eq "service-only") {
    Write-Log "starting LightingService"
    Start-Service -Name "LightingService" -ErrorAction Stop
    Add-Marker "SERVICE_STARTED"
} else {
    $target = Find-ArmouryLaunchTarget
    if ($target) {
        Write-Log "launching Armoury target: $target"
        Start-Process -FilePath $target | Out-Null
    } else {
        Write-Log "Armoury launch target not found; user must open Armoury manually"
    }
    Read-Continue "If UAC appeared, accept it. When Armoury is launching/open, press Enter"
    Add-Marker "UAC_ACCEPTED_BY_USER" "manual_confirmation"
    Add-Marker "ARMOURY_LAUNCHED"
}

Write-Log "observe for at least $PostStartObserveSeconds seconds after start; mark FIRST_LIGHT manually at prompt"
Read-Continue "When LEDs first light, press Enter to mark FIRST_LIGHT"
Add-Marker "FIRST_LIGHT"

Read-Continue "In Armoury, apply WHITE fixed color, handle OK/Apply if needed, then press Enter"
Add-Marker "WHITE_SELECTED"
Read-Continue "If color picker popup was used, press Enter after selecting with mouse"
Add-Marker "MOUSE_COLOR_SELECTED" "white_if_applicable"
Read-Continue "If OK was clicked, press Enter"
Add-Marker "OK_CLICKED" "white_if_applicable"
Read-Continue "If Apply was clicked, press Enter"
Add-Marker "APPLY_CLICKED" "white_if_applicable"

Read-Continue "In Armoury, apply RED fixed color, handle OK/Apply if needed, then press Enter"
Add-Marker "RED_SELECTED"
Read-Continue "If color picker popup was used for RED, press Enter"
Add-Marker "MOUSE_COLOR_SELECTED" "red_if_applicable"
Read-Continue "If OK was clicked for RED, press Enter"
Add-Marker "OK_CLICKED" "red_if_applicable"
Read-Continue "If Apply was clicked for RED, press Enter"
Add-Marker "APPLY_CLICKED" "red_if_applicable"

Write-Log "waiting for probe to finish or for remaining capture duration"
$ProbeProcess.WaitForExit([Math]::Max(1000, $CaptureSeconds * 1000)) | Out-Null
if (-not $ProbeProcess.HasExited) {
    Write-Log "probe still running after duration; stopping process"
    Stop-Process -Id $ProbeProcess.Id -Force -ErrorAction SilentlyContinue
    Add-Marker "CAPTURE_FORCE_STOPPED"
} else {
    Add-Marker "CAPTURE_STOPPED" "exit_code=$($ProbeProcess.ExitCode)"
}

$afterStart = Get-StackSnapshot
$afterStart | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $CaptureDir "armoury_cold_start_${Stamp}_stack_after_start.json") -Encoding UTF8

Write-SanitizedSummary
Write-Log "done"
