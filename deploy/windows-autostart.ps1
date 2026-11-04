<#
 Start ad-arta at boot on Windows, before anyone logs in.

 Registers a scheduled task that runs `ad-arta run` under your account
 without storing your password (logon type S4U), so it can read the TV token
 and the Apple TV pairing in your user profile. It restarts the bridge if it
 stops and logs to ad-arta.log next to config.toml.

 Needs an elevated PowerShell (Run as administrator), from the project folder:

   powershell -ExecutionPolicy Bypass -File deploy\windows-autostart.ps1

 Remove it again with:

   powershell -ExecutionPolicy Bypass -File deploy\windows-autostart.ps1 -Remove
#>
param(
    # Project folder with .venv and config.toml. Defaults to this script's repo.
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    # Account to run as. Pass it when the admin prompt uses another account.
    [string]$User = "$env:USERDOMAIN\$env:USERNAME",
    [string]$TaskName = "ad-arta",
    [switch]$Remove
)
$ErrorActionPreference = "Stop"

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw "Run this from an elevated PowerShell (Run as administrator)." }

# Stop a running copy so the new settings take over. Also stop bridge
# processes left over from older versions of this task, which ran the bridge
# under a wrapper that Stop-ScheduledTask didn't take down with it.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName
}
$venv = Join-Path $Root ".venv"
Get-CimInstance Win32_Process |
    Where-Object { $_.ExecutablePath -like "$venv\*" -and $_.CommandLine -match '\brun\b' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'."
    return
}

$exe = Join-Path $Root ".venv\Scripts\ad-arta.exe"
$config = Join-Path $Root "config.toml"
$log = Join-Path $Root "ad-arta.log"
foreach ($path in $exe, $config) {
    if (-not (Test-Path $path)) { throw "Not found: $path" }
}

# Run the bridge itself (no shell wrapper), so stopping the task stops it.
$action = New-ScheduledTaskAction -Execute $exe `
    -Argument "--config `"$config`" --log-file `"$log`" run" `
    -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtStartup
$trigger.Delay = "PT30S"  # give the network a moment after boot
$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Scheduled task '$TaskName' installed (starts at boot as $User) and started."
Write-Host "Log: $log"
