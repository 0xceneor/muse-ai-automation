@echo off
setlocal
title Muse.ai Account Provisioning
cd /d "%~dp0"

echo =======================================================
echo          Muse.ai Account Provisioning Runner
echo =======================================================
echo.

if not exist .env (
    echo [!] No .env found. Copy .env.example to .env and fill it in first.
    pause
    exit /b 1
)

if not exist node_modules (
    echo [*] Installing Node dependencies...
    call npm install
)

python -c "import playwright" 2>nul
if errorlevel 1 (
    echo [*] Installing Python dependencies...
    call pip install -r requirements.txt
)

echo [*] Starting CloakBrowser session on port 9222...
start "CloakBrowser" node scripts/launch_profile.js

echo [*] Waiting for CDP endpoint...
set /a TRIES=0
:waitcdp
timeout /t 2 >nul
curl -s http://127.0.0.1:9222/json/version >nul 2>&1
if not errorlevel 1 goto ready
set /a TRIES+=1
if %TRIES% lss 20 goto waitcdp
echo [!] Browser did not come up on 9222. Check the CloakBrowser window.
pause
exit /b 1

:ready
echo.
echo [*] Stage 1/3: creating inbox and submitting address
python scripts/muse_bot.py --new-account || goto failed

for /f "usebackq tokens=1 delims=," %%a in ("accounts.csv") do set "ADDRESS=%%a"

echo.
echo [*] Stage 2/3: waiting for the OTP mail
python scripts/muse_bot.py --fetch-otp --account "%ADDRESS%" || goto failed

echo.
echo [*] Stage 3/3: birthday, terms, card verification, invite redemption
python scripts/automate_account.py --account "%ADDRESS%" || goto failed

echo.
echo [*] Done. Account: %ADDRESS%
echo [*] Credentials are in accounts.csv
pause
exit /b 0

:failed
echo.
echo [!] Pipeline stopped. Fix the cause, then rerun, or continue by hand.
pause
exit /b 1
