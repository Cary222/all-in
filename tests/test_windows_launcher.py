from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "windows" / "start_allin.ps1"
INSTALLER = REPO_ROOT / "scripts" / "windows" / "install_desktop_shortcut.ps1"
SHORTCUTS = REPO_ROOT / "scripts" / "windows" / "create_desktop_shortcuts.ps1"


class WindowsLauncherTests(unittest.TestCase):
	def test_launcher_is_portable_and_opens_both_services(self):
		text = LAUNCHER.read_text(encoding="utf-8")
		self.assertIn("$PSScriptRoot", text)
		self.assertIn("allin.main", text)
		self.assertIn("$PythonPath", text)
		self.assertIn("Get-Command", text)
		self.assertIn("remote-debugging-port=9222", text)
		self.assertIn("http://127.0.0.1:8686", text)
		self.assertIn("-WindowStyle Hidden", text)
		self.assertNotIn("C:\\Users\\123", text)

	def test_installer_creates_a_shortcut_to_the_launcher(self):
		text = INSTALLER.read_text(encoding="utf-8")
		self.assertIn("CreateShortcut", text)
		self.assertIn("start_allin.ps1", text)
		self.assertIn('GetFolderPath("Desktop")', text)
		self.assertIn("-WindowStyle Hidden", text)
		self.assertNotIn("C:\\Users\\123", text)

	def test_local_shortcut_installer_targets_this_checkouts_launcher(self):
		"""The desktop shortcut must use the venv-pinned launcher, not PATH's `allin`."""
		text = SHORTCUTS.read_text(encoding="utf-8")
		self.assertIn("CreateShortcut", text)
		self.assertIn("start_local.ps1", text)
		self.assertIn('GetFolderPath("Desktop")', text)
		self.assertIn("assets\\allin.ico", text)
		self.assertNotIn("C:\\Users\\123", text)

	def test_windows_scripts_stay_ascii_so_powershell_5_1_can_parse_them(self):
		"""PowerShell 5.1 decodes a BOM-less script as ANSI, mangling non-ASCII literals."""
		for script in (LAUNCHER, INSTALLER, SHORTCUTS):
			raw = script.read_bytes()
			self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"{script.name} must not need a BOM")
			offenders = [line for line in raw.splitlines() if any(byte > 0x7E for byte in line)]
			self.assertEqual(offenders, [], f"{script.name} must stay pure ASCII")

	def test_brand_assets_share_one_definition(self):
		"""Favicon, Windows icon and the in-app logo must not drift apart again.

		They previously held three unrelated marks (an "BH" favicon left over from the
		BOSS-only project, an orange "AIN" icon, and the green sidebar glyph).
		"""
		favicon = (REPO_ROOT / "src" / "allin" / "web" / "frontend" / "public" / "favicon.svg").read_text("utf-8")
		generator = (REPO_ROOT / "scripts" / "generate_brand_assets.py").read_text("utf-8")
		sidebar = (REPO_ROOT / "src" / "allin" / "web" / "frontend" / "src" / "components" / "layout" / "Sidebar.tsx").read_text("utf-8")

		# hsl(166 50% 28%) - the theme's --primary.
		self.assertIn('fill="#246B5A"', favicon)
		self.assertIn("0x24, 0x6B, 0x5A", generator)
		self.assertIn("--primary: 166 50% 28%", (REPO_ROOT / "src" / "allin" / "web" / "frontend" / "src" / "globals.css").read_text("utf-8"))
		# The in-app mark uses the same theme colour and the same lucide glyph.
		self.assertIn("bg-primary", sidebar)
		self.assertIn("Route", sidebar)
		# The lucide `Route` path must appear in both the vector and the raster source.
		route_path = "M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"
		self.assertIn(route_path, favicon)
		# No trace of the old "BH" wordmark anywhere in the favicon.
		self.assertNotIn(">BH<", favicon)


if __name__ == "__main__":
	unittest.main()
