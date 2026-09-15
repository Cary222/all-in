# All In local launcher (venv-based install).
#
# Differences from the upstream scripts\windows\start_allin.ps1:
#   1. Pinned to this repo's .venv Python (upstream looks for `allin` on PATH).
#   2. Auto-picks a FREE Chrome DevTools port. The default 9222 is permanently
#      held by Windows' background msedge.exe (--no-startup-window), which does
#      not answer CDP requests, so Chrome can never bind it.
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\start_local.ps1

[CmdletBinding()]
param(
	[switch]$SkipChrome,
	[int[]]$PortCandidates = @(9229, 9333, 9344, 9222, 9223)
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$VenvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$WorkbenchUrl = "http://127.0.0.1:8686"

if (-not (Test-Path -LiteralPath $VenvPy)) {
	throw "Virtual environment Python not found: $VenvPy`nRun: python -m venv .venv && .venv\Scripts\python.exe -m pip install -e ."
}

# ---- locate Chrome -------------------------------------------------------
$ChromeCandidates = @()
if ($env:ProgramFiles) { $ChromeCandidates += Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe" }
if (${env:ProgramFiles(x86)}) { $ChromeCandidates += Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe" }
if ($env:LOCALAPPDATA) { $ChromeCandidates += Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe" }
$ChromeCandidates = @($ChromeCandidates | Where-Object { Test-Path -LiteralPath $_ })
if ($ChromeCandidates.Count -eq 0) { throw "Google Chrome not found." }
$Chrome = $ChromeCandidates[0]

# ---- pick a free DevTools port -------------------------------------------
$ChromePort = $null
foreach ($p in $PortCandidates) {
	$busy = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
	if (-not $busy) { $ChromePort = $p; break }
}
if (-not $ChromePort) {
	throw "No free Chrome DevTools port among: $($PortCandidates -join ', ')"
}
Write-Host "Chrome DevTools port : $ChromePort"

$ChromeProfile = Join-Path $env:LOCALAPPDATA "AllInChrome"

function Start-DedicatedChrome {
	param([string]$Url)
	$args = @(
		"--remote-debugging-port=$ChromePort",
		"--user-data-dir=$ChromeProfile"
	)
	if ($Url) { $args += $Url }
	Start-Process -FilePath $Chrome -ArgumentList $args
}

# ---- start Chrome with remote debugging ----------------------------------
if (-not $SkipChrome) {
	Write-Host "Starting the All In Chrome profile..."
	Start-DedicatedChrome -Url "https://www.zhipin.com"

	$ready = $false
	for ($i = 0; $i -lt 30; $i++) {
		Start-Sleep -Milliseconds 500
		try {
			$null = Invoke-RestMethod -Uri "http://127.0.0.1:$ChromePort/json/version" -TimeoutSec 2
			$ready = $true
			break
		} catch {
			# still starting
		}
	}
	if ($ready) { Write-Host "Chrome DevTools endpoint : ready" }
	else { Write-Warning "Chrome DevTools did not answer within 15s. Is another Chrome already using this profile?" }
}

# ---- All In connection check ---------------------------------------------
Write-Host "Checking All In Browser Runtime connection..."
& $VenvPy -m allin.main connect
if ($LASTEXITCODE -ne 0) {
	Write-Warning "Connection check exited with code $LASTEXITCODE. Opening the workbench anyway."
}

# ---- start the local workbench -------------------------------------------
Write-Host "Starting the local workbench (hidden)..."
Start-Process -FilePath $VenvPy `
	-ArgumentList @("-m", "allin.main", "web", "--no-open") `
	-WorkingDirectory $RepoRoot `
	-WindowStyle Hidden

for ($i = 0; $i -lt 30; $i++) {
	Start-Sleep -Milliseconds 500
	try {
		$null = Invoke-WebRequest -Uri "$WorkbenchUrl/" -UseBasicParsing -TimeoutSec 2
		break
	} catch {
		# still starting
	}
}

# ---- open the workbench in the same dedicated Chrome profile -------------
if (-not $SkipChrome) {
	Start-DedicatedChrome -Url $WorkbenchUrl
}

Write-Host ""
Write-Host "All In is ready."
Write-Host "  Workbench    : $WorkbenchUrl"
Write-Host "  DevTools port: $ChromePort"
Write-Host "  Chrome profile: $ChromeProfile"
Write-Host ""
Write-Host "Log in to BOSS zhipin manually in the dedicated Chrome window if needed."
