<#
.SYNOPSIS
  Install / configure the recomp-profiler agent on a Windows test machine.
.DESCRIPTION
  No arguments: install Python via winget, create the venv, write connection info,
  then open the setup TUI (recomp-profiler tui).
  -All: everything headless (tools, venv, init, logon task, optional firewall).
  -Only <step>: one step: packages | venv | init | service | firewall
  The agent runs as a logon task in the interactive session so it can launch games.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -All -OpenFirewall
#>
param(
    [switch]$All,
    [ValidateSet("", "packages", "venv", "init", "service", "firewall")]
    [string]$Only = "",
    [int]$Port = 0,
    [string]$Name = "",
    [string]$Address = "",
    [string]$Source = "",
    [switch]$NoPackages,
    [switch]$NoTask,
    [switch]$OpenFirewall,
    [switch]$NoTui
)
$ErrorActionPreference = "Stop"
$Prefix = Join-Path $env:LOCALAPPDATA "recomp-profiler"
$Venv = Join-Path $Prefix "venv"
$Agent = Join-Path $Venv "Scripts\recomp-agent.exe"
$Cli = Join-Path $Venv "Scripts\recomp-profiler.exe"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

if (-not $Source) {
    if (Test-Path (Join-Path $RepoRoot "pyproject.toml")) { $Source = "$RepoRoot" }
    elseif (Test-Path $Cli) {
        $Source = & (Join-Path $Venv "Scripts\python.exe") -c "from recomp_profiler import settings; print(settings.load().install.source)"
    }
}

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Winget-Install([string[]]$ids) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget not found. Install 'App Installer' from the Microsoft Store, then rerun."
    }
    foreach ($id in $ids) {
        winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) { Write-Warning "winget could not install $id" }
    }
    Refresh-Path
}

function Step-Bootstrap {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { Winget-Install @("Python.Python.3.12") }
}

function Step-Packages {
    # Everything the agent needs comes from here; no manual installs.
    Winget-Install @(
        "Python.Python.3.12",
        "Git.Git",
        "Microsoft.WinDbg",
        "Microsoft.WindowsADK",            # WPR/WPA (Windows Performance Toolkit)
        "Microsoft.Sysinternals.Suite"
    )
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

function Step-Venv {
    if (-not $Source) { throw "no agent source known; pass -Source PATH|URL" }
    Write-Host "==> creating venv in $Venv"
    py -3 -m venv --clear $Venv
    & (Join-Path $Venv "Scripts\python.exe") -m pip install -q --upgrade pip
    & (Join-Path $Venv "Scripts\pip.exe") install -q "$Source"
    & $Cli config-set install.source "$Source"
}

function Step-Init {
    if ($Port) { & $Cli config-set agent.port $Port }
    if ($Name) { & $Cli config-set agent.name $Name }
    if ($Address) { & $Cli config-set agent.address $Address }
    & $Agent init | Out-Null
}

function Agent-Port {
    if ($Port) { return $Port }
    return [int](& (Join-Path $Venv "Scripts\python.exe") -c "from recomp_profiler import settings; print(settings.load().agent.port)")
}

function Step-Firewall {
    # Needs an elevated shell.
    $p = Agent-Port
    Remove-NetFirewallRule -DisplayName "recomp-agent" -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "recomp-agent" -Direction Inbound -Protocol TCP -LocalPort $p -Action Allow -Profile Private | Out-Null
    Write-Host "==> firewall: TCP $p allowed on private networks"
}

function Step-Service {
    # bind/port/allowlist come from config.toml
    $action = New-ScheduledTaskAction -Execute $Agent -Argument "serve"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0 -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName "recomp-agent" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    Stop-ScheduledTask -TaskName "recomp-agent" -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName "recomp-agent"
}

function Report {
    $conn = Join-Path $env:APPDATA "recomp-profiler\agent\connection.json"
    Write-Host "`n==> connection info ($conn):"
    Get-Content $conn
    Write-Host "`n==> IPv4 addresses:"
    Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne "127.0.0.1" } | ForEach-Object { "    $($_.InterfaceAlias)  $($_.IPAddress)" }
    Write-Host "`nOn the dev machine: recomp-profiler add-host connection.json  (file contains the token; transfer privately)"
}

if ($Only) {
    switch ($Only) {
        "packages" { Step-Packages }
        "venv" { Step-Venv }
        "init" { Step-Init }
        "service" { Step-Service }
        "firewall" { Step-Firewall }
    }
} elseif ($All -or $NoPackages -or $NoTask -or $OpenFirewall) {
    if ($NoPackages) { Step-Bootstrap } else { Step-Packages }
    Step-Venv
    Step-Init
    if ($OpenFirewall) { Step-Firewall }
    if (-not $NoTask) { Step-Service }
    Report
} else {
    Step-Bootstrap
    Step-Venv
    Step-Init
    if ($NoTui) { Report }
    else {
        Write-Host "==> opening the setup TUI (System setup tab installs tools, autostart, firewall, ...)"
        & $Cli tui --tab system
    }
}
