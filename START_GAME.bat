@echo off
setlocal
cd /d "%~dp0"
title PLATE CLUB 3.0

echo ========================================
echo          PLATE CLUB 3.0
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python launcher "py" was not found.
  echo Install Python 3.11 or newer from python.org and enable "Add Python to PATH".
  pause
  exit /b 1
)

echo [1/3] Installing required packages...
py -3 -m pip install --upgrade pip
if errorlevel 1 goto pip_error
py -3 -m pip install -r requirements.txt
if errorlevel 1 goto pip_error

echo.
echo [2/3] Checking server imports...
py -3 -c "import fastapi, uvicorn, pydantic, server; print('Server import OK')"
if errorlevel 1 goto import_error

echo.
echo [3/3] Starting PLATE CLUB...
echo Keep this window open while playing.
echo Open http://127.0.0.1:8000 in your browser.
echo Press Ctrl+C to stop the server.
echo.
start "PLATE CLUB" cmd /c "timeout /t 3 /nobreak ^>nul ^& start http://127.0.0.1:8000"
py -3 -m uvicorn server:app --app-dir "%CD%" --host 127.0.0.1 --port 8000
if errorlevel 1 goto server_error
pause
exit /b 0

:pip_error
echo.
echo ERROR: Could not install Python packages.
echo Check your internet connection and Python installation.
pause
exit /b 1

:import_error
echo.
echo ERROR: The server could not be imported. The Python error above explains why.
echo Send me a screenshot or copy the full error text.
pause
exit /b 1

:server_error
echo.
echo ERROR: The server stopped with an error. Read the message above.
pause
exit /b 1
