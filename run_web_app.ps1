# ============================================================================
# ADF Cost Optimizer - Web App Launcher (PowerShell)
# ============================================================================
# Usage:
#   .\run_web_app.ps1
#   .\run_web_app.ps1 -Port 8080
#   .\run_web_app.ps1 -Debug
# ============================================================================

param(
    [int]$Port = 5000,
    [string]$Host = "127.0.0.1",
    [switch]$Debug
)

# Set error action
$ErrorActionPreference = "Stop"

# Check if Python is available
Write-Host "Checking Python installation..." -ForegroundColor Cyan
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "Error: Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Python 3.9+ from https://www.python.org" -ForegroundColor Yellow
    exit 1
}

# Check if running in correct directory
if (-not (Test-Path "web_app.py")) {
    Write-Host "Error: web_app.py not found in current directory" -ForegroundColor Red
    Write-Host "Please run this script from the ADF Cost Optimization directory" -ForegroundColor Yellow
    exit 1
}

# Activate or create virtual environment
Write-Host "`nSetting up Python environment..." -ForegroundColor Cyan
if (Test-Path ".venv\Scripts\Activate.ps1") {
    Write-Host "Activating virtual environment..." -ForegroundColor Green
    & ".venv\Scripts\Activate.ps1"
} else {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
    & ".venv\Scripts\Activate.ps1"
}

# Install/upgrade requirements
Write-Host "`nInstalling dependencies..." -ForegroundColor Cyan
pip install -q -U -r requirements.txt

# Build command
$command = "python web_app.py --port $Port --host $Host"
if ($Debug) {
    $command += " --debug"
}

# Print info
Write-Host "`n" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "Starting ADF Cost Optimizer Web App" -ForegroundColor Green
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "URL: http://$Host`:$Port" -ForegroundColor Yellow
Write-Host "Debug Mode: $(if ($Debug) { 'Enabled' } else { 'Disabled' })" -ForegroundColor Yellow
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Yellow
Write-Host ""

# Run the app
Invoke-Expression $command
