<#
.SYNOPSIS
  Install the recomp-profiler agent on a Windows test machine.
.DESCRIPTION
  Installs Python + profiling tools via winget, creates a venv, generates the
  token/TLS cert, registers a logon task (the agent must run in the interactive
  session to launch games) and prints connection.json.
  Run from an elevated PowerShell only for -OpenFirewall; otherwise as the desktop user.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -OpenFirewall
#>
param(
    [int]$Port = 47800,
    [string]$Name = $env:COMPUTERNAME,
    [string]$Address = "",
    [string]$Source = (Resolve-Path "$PSScriptRoot\..\.."),
    [switch]$NoPackages,
    [switch]$NoTask,
    [switch]$OpenFirewall
)
$ErrorActionPreference = "Stop"
$Prefix = Join-Path $env:LOCALAPPDATA "recomp-profiler"

if (-not $NoPackages) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget not found. Install 'App Installer' from the Microsoft Store, then rerun."
    }
    # Everything the agent needs comes from here; no manual installs.
    $pkgs = @(
        "Python.Python.3.12",
        "Git.Git",
        "Microsoft.WinDbg",
        "Microsoft.WindowsADK",            # WPR/WPA (Windows Performance Toolkit)
        "Microsoft.Sysinternals.Suite"
    )
    foreach ($p in $pkgs) {
        winget install --id $p --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { Write-Warning "winget could not install $p" }
    }
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")

    # PresentMon (frame times) has no winget id: take the console build from the latest GitHub release.
    $tools = Join-Path $Prefix "tools"
    New-Item -ItemType Directory -Force -Path $tools | Out-Null
    try {
        $rel = Invoke-RestMethod "https://api.github.com/repos/GameTechDev/PresentMon/releases/latest"
        $asset = $rel.assets | Where-Object { $_.name -match '^PresentMon-.*-x64\.exe$' } | Select-Object -First 1
        Invoke-WebRequest $asset.browser_download_url -OutFile (Join-Path $tools "PresentMon.exe")
        Write-Host "==> PresentMon $($rel.tag_name) -> $tools"
    } catch {
        Write-Warning "could not download PresentMon: $_"
    }
}

Write-Host "==> creating venv in $Prefix\venv"
py -3 -m venv "$Prefix\venv"
& "$Prefix\venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$Prefix\venv\Scripts\pip.exe" install -q "$Source"
$agent = "$Prefix\venv\Scripts\recomp-agent.exe"

$initArgs = @("init", "--port", $Port, "--name", $Name)
if ($Address) { $initArgs += @("--host-address", $Address) }
& $agent @initArgs | Out-Null

if ($OpenFirewall) {
    New-NetFirewallRule -DisplayName "recomp-agent" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private | Out-Null
}

if (-not $NoTask) {
    $action = New-ScheduledTaskAction -Execute $agent -Argument "serve --port $Port"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName "recomp-agent" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName "recomp-agent"
}

$conn = Join-Path $env:APPDATA "recomp-profiler\agent\connection.json"
Write-Host "`n==> agent installed. Connection info ($conn):"
Get-Content $conn
Write-Host "`n==> IPv4 addresses:"
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne "127.0.0.1" } | ForEach-Object { "    $($_.InterfaceAlias)  $($_.IPAddress)" }
Write-Host "`nOn the dev machine: recomp-profiler add-host connection.json  (file contains the token; transfer privately)"
