@echo off
REM Opens a terminal with the All In virtual environment already activated,
REM so commands like `allin run`, `allin connect` and `allin status` work directly.
setlocal
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\activate.bat" (
	echo [ERROR] Virtual environment not found. Please install first.
	pause
	exit /b 1
)

echo All In environment activated. Repo root:
echo   %~dp0
echo.
echo Useful commands:
echo   allin web          - start the local dashboard (127.0.0.1:8686^)
echo   allin ai-status    - check the AI service connection
echo   allin connect      - check Chrome / Browser Runtime connection
echo   allin run          - full pipeline: scrape -^> score -^> confirm -^> greet -^> send
echo.

cmd /k "%~dp0.venv\Scripts\activate.bat"
