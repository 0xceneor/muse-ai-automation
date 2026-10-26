"""Interactive or stepped registration for custom email addresses (e.g. Gmail).

Usage:
  Step 1 (Submit Email):
    python scripts/register_custom_email.py --email user@gmail.com

  Step 2 (Submit OTP and complete onboarding):
    python scripts/register_custom_email.py --code 123456
"""

import os
import sys
import time
import argparse
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

from muse_bot import (
    log, enter_email, enter_otp, wait_for_stage,
    take_status_snapshot, which_screen, OTP_SEL,
)
from automate_account import run_all_after_email

CDP_URL = os.getenv("CDP_URL", "http://127.0.0.1:9222")


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
    with sync_playwright() as p:
        browser, page = get_browser_and_page(p)
        if not enter_email(page, email):
            log("[-] Failed to enter email or signup rejected.")
            take_status_snapshot(page, "muse_custom_email_failed.png")
            sys.exit(1)

        take_status_snapshot(page, "muse_custom_email_otp.png")
        log(f"[SUCCESS] OTP dispatched by Meta to {email}!")
        log("[READY_FOR_OTP] The browser is sitting on the OTP screen waiting for verification code.")


def step_submit_code(code: str):
    invite = os.getenv("INVITE_CODE")
    log(f"Entering OTP verification code: {code}")
    with sync_playwright() as p:
        browser, page = get_browser_and_page(p)
        if not enter_otp(page, code):
            log("[-] OTP was rejected by Meta.")
            take_status_snapshot(page, "muse_custom_otp_rejected.png")
            sys.exit(1)

        log("[+] OTP accepted! Proceeding to onboarding (birthday, card, invite)...")
        if run_all_after_email(page, browser, invite_code=invite):
            log("[SUCCESS] Account successfully provisioned, verified, and redeemed!")
            take_status_snapshot(page, "muse_custom_email_completed.png")
            sys.exit(0)
        else:
            log("[-] Onboarding did not complete successfully.")
            take_status_snapshot(page, "muse_custom_onboarding_failed.png")
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Custom Email Provisioning for Muse.ai")
    parser.add_argument("--email", type=str, help="Email address to submit (e.g. user@gmail.com)")
    parser.add_argument("--code", type=str, help="6-digit OTP code received in email")
    args = parser.parse_args()

    if args.email:
        step_submit_email(args.email)
    elif args.code:
        step_submit_code(args.code)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
