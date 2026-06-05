@echo off
REM ============================================================================
REM ADF Cost Optimizer - Web App Launcher (Windows)
REM ============================================================================

setlocal enabledelayedexpansion

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.9+ from https://www.python.org
    pause
    exit /b 1
)

REM Check if running in the correct directory
if not exist "web_app.py" (
    echo Error: web_app.py not found in current directory
    echo Please run this script from the ADF Cost Optimization directory
    pause
    exit /b 1
)

REM Check for virtual environment
if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
) else (
    echo Warning: Virtual environment not found
    echo Creating virtual environment...
    python -m venv .venv
    call .venv\Scripts\activate.bat
)

REM Install/upgrade requirements
echo.
echo Installing dependencies...
pip install -q -U -r requirements.txt

REM Parse command line arguments
set PORT=5000
set HOST=127.0.0.1
set DEBUG=

:parse_args
if "%~1"=="" goto run_app
if "%~1"=="--port" (
    set PORT=%~2
    shift
    shift
    goto parse_args
)
if "%~1"=="--host" (
    set HOST=%~2
    shift
    shift
    goto parse_args
)
if "%~1"=="--debug" (
    set DEBUG=--debug
    shift
    goto parse_args
)
shift
goto parse_args

:run_app
echo.
echo ============================================================================
echo Starting ADF Cost Optimizer Web App
echo ============================================================================
echo.
echo URL: http://!HOST!:!PORT!
echo.
echo Press Ctrl+C to stop the server
echo.

python web_app.py --port !PORT! --host !HOST! !DEBUG!

endlocal
