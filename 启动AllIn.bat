@echo off
REM All In launcher (venv-based install).
REM Delegates to start_local.ps1, which pins this repo's .venv Python
REM and auto-picks a free Chrome DevTools port.
setlocal
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
	echo [ERROR] Virtual environment not found:
	echo         %~dp0.venv\Scripts\python.exe
	echo.
	echo Run the install steps first:
	echo         python -m venv .venv
	echo         .venv\Scripts\python.exe -m pip install -e .
	echo.
	pause
	exit /b 1
)

if not exist "%~dp0start_local.ps1" (
	echo [ERROR] start_local.ps1 not found in %~dp0
	echo.
	pause
	exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_local.ps1"

endlocal
