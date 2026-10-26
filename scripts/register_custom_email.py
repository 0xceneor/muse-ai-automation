"""Interactive registration for custom email addresses (e.g. Gmail).

Usage:
  Step 1 (Submit Email):
    python scripts/register_custom_email.py --email siamgateio1@gmail.com

  Step 2 (Submit OTP and complete onboarding):
    python scripts/register_custom_email.py --code 123456 [--email siamgateio1@gmail.com]
"""

import os
import sys
import time
import argparse
import secrets
import random
import subprocess
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    from dotenv import load_dotenv
    load_dotenv(str(ROOT / ".env"))
except ImportError:
    pass

import accounts
from muse_bot import (
    log, enter_email, enter_otp, take_status_snapshot,
)
from automate_account import run_all_after_email

CDP_PORT = int(os.getenv("CDP_PORT", "9222"))
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"
STATE_FILE = ROOT / ".current_custom_email.txt"


def cdp_ready(port: int, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def ensure_browser_running():
    if cdp_ready(CDP_PORT, timeout=2):
        log(f"Browser already listening on port {CDP_PORT}")
        return None

    profile_name = f"profile_gmail_{secrets.token_hex(3)}"
    fp_seed = random.randint(100000, 999999)

    env = dict(os.environ)
    env["CDP_PORT"] = str(CDP_PORT)
    env["CDP_URL"] = CDP_URL
    env["PROFILE_NAME"] = profile_name
    env["FINGERPRINT"] = str(fp_seed)
    env["HEADLESS"] = "1"

    launch_js = SCRIPTS / "launch_profile.js"
    log(f"Spawning CloakBrowser instance on port {CDP_PORT}...")

    proc = subprocess.Popen(
        ["node", str(launch_js)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if not cdp_ready(CDP_PORT, timeout=40):
        log("[-] Browser CDP timed out")
        sys.exit(1)
    return proc


def get_browser_and_page(playwright):
    log(f"Connecting over CDP at {CDP_URL}...")
    browser = playwright.chromium.connect_over_cdp(CDP_URL)
    page = None
    for context in browser.contexts:
        for p in context.pages:
            if "muse.ai" in p.url or "meta.ai" in p.url:
                page = p
                break
        if page:
            break
    if not page and browser.contexts and browser.contexts[0].pages:
        page = browser.contexts[0].pages[0]
    if not page and browser.contexts:
        page = browser.contexts[0].new_page()
    if not page:
        context = browser.new_context()
        page = context.new_page()

    # Block heavy streaming background media/video to conserve proxy bandwidth
    try:
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["media"] else route.continue_())
    except Exception:
        pass

    # Log any backend API responses
    def on_resp(res):
        try:
            if "register-completion" in res.url or res.status >= 400:
                txt = res.text()
                log(f"[API RESP {res.status}] {res.url[:70]} -> {txt[:300]}")
        except Exception:
            pass

    page.on("response", on_resp)
    return browser, page


def step_submit_email(email: str):
    log(f"Starting submission for custom email: {email}")
    ensure_browser_running()
    prefix = email.split("@")[0].lower()

    # Record email in local state file so step 2 knows which email to record in ledger
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(email.strip())

    playwright = sync_playwright().start()
    try:
        browser, page = get_browser_and_page(playwright)
        if not enter_email(page, email):
            log("[-] Failed to enter email or signup rejected.")
            take_status_snapshot(page, f"{prefix}_email_failed.png")
            sys.exit(1)

        take_status_snapshot(page, f"{prefix}_otp_screen.png")
        take_status_snapshot(page, "muse_custom_email_otp.png")
        log(f"[SUCCESS] OTP dispatched by Meta to {email}!")
        log("[READY_FOR_OTP] The browser is sitting on the OTP screen waiting for verification code.")
        print("\n" + "=" * 60)
        print(f"OTP DISPATCHED TO: {email}")
        print("Please check your email and run:")
        print(f"python scripts/register_custom_email.py --code <6-DIGIT-OTP>")
        print("=" * 60 + "\n")
    finally:
        playwright.stop()


def step_submit_code(code: str, email: str = None):
    if not email and STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            email = f.read().strip()
    email = email or "custom_email@gmail.com"
    prefix = email.split("@")[0].lower()
    invite = os.getenv("INVITE_CODE", "RM99IU")

    log(f"Entering OTP verification code: {code} for {email}")
    playwright = sync_playwright().start()
    try:
        browser, page = get_browser_and_page(playwright)
        if not enter_otp(page, code):
            log("[-] OTP was rejected by Meta.")
            take_status_snapshot(page, f"{prefix}_otp_rejected.png")
            sys.exit(1)

        log("[+] OTP accepted! Proceeding to onboarding (birthday, card, invite)...")
        if run_all_after_email(page, browser, invite_code=invite):
            log(f"[SUCCESS] {email} successfully registered and credited with 1B tokens!")
            take_status_snapshot(page, f"{prefix}_account_active.png")
            take_status_snapshot(page, "muse_custom_email_completed.png")
            accounts._upsert(
                email,
                status="active",
                created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            print("\n" + "=" * 60)
            print(f"ACCOUNT PROVISIONED SUCCESSFULLY: {email}")
            print(f"INVITE REDEEMED: {invite} (1 Billion Tokens)")
            print("=" * 60 + "\n")
        else:
            log("[-] Onboarding did not complete successfully.")
            take_status_snapshot(page, f"{prefix}_onboarding_failed.png")
            sys.exit(1)
    finally:
        playwright.stop()
        log("Cleaning up browser process...")
        subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True)


def main():
    parser = argparse.ArgumentParser(description="Custom Email Provisioning for Muse.ai")
    parser.add_argument("--email", type=str, help="Email address to submit (e.g. user@gmail.com)")
    parser.add_argument("--code", type=str, help="6-digit OTP code received in email")
    args = parser.parse_args()

    if args.email:
        step_submit_email(args.email)
    elif args.code:
        step_submit_code(args.code, email=args.email)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
