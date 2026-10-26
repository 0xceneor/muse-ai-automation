@echo off
title Muse.ai Automation Pipeline
cd /d "%~dp0"

echo =======================================================
echo          Muse.ai Automation Pipeline Runner
echo =======================================================
echo.

if not exist node_modules (
    echo [*] Installing Node dependencies...
    call npm install
)

echo [*] Starting CloakBrowser session on port 9222...
node scripts/launch_profile.js
pause
