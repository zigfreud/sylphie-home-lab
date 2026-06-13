param(
    [ValidateSet("gui-cold-launch", "service-only")]
    [string]$Mode = "gui-cold-launch",
    [string]$MarkerLog = ""
)

$ErrorActionPreference = "Stop"

function Add-Marker {
    param(
        [string]$Marker,
        [string]$Note = ""
    )
    if (-not $MarkerLog) {
        return
    }
    $suffix = if ($Note) { " note=$Note" } else { "" }
    $line = "{0} MARKER {1}{2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss.fff"), $Marker, $suffix
    Add-Content -LiteralPath $MarkerLog -Value $line -Encoding UTF8
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

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

if ($Mode -eq "service-only") {
    Start-Service -Name "LightingService" -ErrorAction Stop
    Add-Marker "SERVICE_STARTED" "start_armoury_stack.ps1"
    Write-Host "LightingService start requested."
    exit 0
}

$target = Find-ArmouryLaunchTarget
if ($target) {
    Start-Process -FilePath $target | Out-Null
    Add-Marker "ARMOURY_LAUNCHED" "target=$target"
    Write-Host "Armoury launch requested: $target"
    exit 0
}

Add-Marker "ARMOURY_LAUNCH_TARGET_NOT_FOUND"
throw "Armoury launch target not found. Open Armoury manually and add ARMOURY_LAUNCHED marker from the Capture Lab."
