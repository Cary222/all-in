# Create the desktop shortcuts for this working copy of All In.
#
# Two shortcuts are produced:
#   "All In"        - starts the dedicated Chrome profile + local workbench
#                     (delegates to the repo-root start_local.ps1, which pins this
#                     repo's .venv and picks a free Chrome DevTools port)
#   "All In <terminal>" - opens a terminal with the venv already activated
#
# The repo-root launchers are used on purpose: scripts\windows\start_allin.ps1 is
# the portable upstream script, which resolves `allin` from PATH rather than this
# checkout's virtualenv. Both shortcuts share assets\allin.ico so the desktop icon
# matches the in-app logo and the browser favicon.
#
# Source stays pure ASCII: PowerShell 5.1 decodes a BOM-less script as ANSI, so
# non-ASCII literals here would be mangled (the existing scripts follow the same
# rule). The Chinese shortcut name is built from code points at runtime instead.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\windows\create_desktop_shortcuts.ps1
#   ... -Uninstall                # remove the shortcuts again

[CmdletBinding()]
param(
	[string[]]$Names,
	[switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$IconPath = Join-Path $RepoRoot "assets\allin.ico"
$PowerShell = Join-Path $PSHOME "powershell.exe"
$Desktop = [Environment]::GetFolderPath("Desktop")
$Shell = New-Object -ComObject WScript.Shell
$Launcher = Join-Path $RepoRoot "start_local.ps1"
$Batch = Join-Path $env:SystemRoot "System32\cmd.exe"

# U+7EC8 U+7AEF = the two CJK characters in the terminal batch file's name.
$TerminalSuffix = [string][char]0x7EC8 + [string][char]0x7AEF
$Terminal = Join-Path $RepoRoot ("AllIn" + $TerminalSuffix + ".bat")
if (-not $Names -or $Names.Count -lt 2) {
	$Names = @("All In", "All In $TerminalSuffix")
}

# Each shortcut binds a display name to a target, an argument list, a description
# and the window style: the launcher runs hidden (it opens its own windows), while
# the terminal stays visible for interactive use.
$Definitions = @(
	@{
		Name = $Names[0]
		Target = $PowerShell
		Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Launcher`""
		Description = "Start the All In Chrome profile and local workbench"
		WindowStyle = 7
	},
	@{
		Name = $Names[1]
		# Launch the batch through cmd.exe so the console window is created by a
		# stable target; the batch itself ends in `cmd /k`, keeping it interactive.
		Target = $Batch
		Arguments = "/c `"$Terminal`""
		Description = "Open a terminal with the All In virtualenv activated"
		WindowStyle = 1
	}
)

foreach ($definition in $Definitions) {
	$shortcutPath = [System.IO.Path]::Combine($Desktop, $definition.Name + ".lnk")

	if ($Uninstall) {
		if (Test-Path -LiteralPath $shortcutPath) {
			Remove-Item -LiteralPath $shortcutPath -Force
			Write-Host "Removed  : $shortcutPath"
		} else {
			Write-Host "Skipped  : $shortcutPath (not present)"
		}
		continue
	}

	# Always overwrite: an existing shortcut may still point at an old launcher.
	$shortcut = $Shell.CreateShortcut($shortcutPath)
	$shortcut.TargetPath = $definition.Target
	$shortcut.Arguments = $definition.Arguments
	$shortcut.WorkingDirectory = $RepoRoot
	$shortcut.Description = $definition.Description
	$shortcut.WindowStyle = $definition.WindowStyle
	if (Test-Path -LiteralPath $IconPath) {
		$shortcut.IconLocation = "$IconPath,0"
	} else {
		Write-Warning "Icon not found, the shortcut will use the default icon: $IconPath"
	}
	$shortcut.Save()
	Write-Host "Created  : $shortcutPath"
}

if (-not $Uninstall) {
	Write-Host ""
	Write-Host "Done. Double-click the All In shortcut to start the workbench."
}
