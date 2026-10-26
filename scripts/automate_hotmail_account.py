"""Automated end-to-end Muse.ai provisioning for Microsoft Graph Hotmail account.

Performs:
1. Spawns CloakBrowser on a dedicated profile with Decodo residential proxy.
2. Navigates to Muse.ai and enters the Hotmail address.
3. Automatically retrieves the 6-digit verification code from Microsoft Graph API.
4. Enters OTP and handles adult birthday, disclosure, and card age verification.
5. Loads the workspace and redeems the 1 Billion token invite code (INVITE_CODE).
6. Records credentials in accounts.csv with status 'active'.
"""

import os
import sys
import time
import json
import re
import secrets
import random
import subprocess
import urllib.request
import urllib.parse
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
from automate_account import run_all_after_email, screen_of

import argparse

CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

ENV_CLIENT_ID = os.getenv("HOTMAIL_CLIENT_ID", "")
ENV_REFRESH_TOKEN = os.getenv("HOTMAIL_REFRESH_TOKEN", "")
ENV_EMAIL = os.getenv("HOTMAIL_EMAIL", "")
ENV_PASSWORD = os.getenv("HOTMAIL_PASSWORD", "")
ENV_INVITE_CODE = os.getenv("INVITE_CODE", "RM99IU")


def get_graph_access_token(client_id: str, refresh_token: str) -> str:
    ep = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "https://graph.microsoft.com/Mail.Read",
    }).encode()
    req = urllib.request.Request(ep, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    res = json.loads(urllib.request.urlopen(req, timeout=15).read().decode())
    return res["access_token"]


def get_existing_message_ids(client_id: str, refresh_token: str) -> set:
    try:
        token = get_graph_access_token(client_id, refresh_token)
        url = "https://graph.microsoft.com/v1.0/me/messages?$top=10&$select=id,receivedDateTime"
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
        res = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
        messages = res.get("value", [])
        return {msg["id"] for msg in messages}
    except Exception as e:
        log(f"  Warning getting existing message ids: {e}")
        return set()


def poll_graph_otp(client_id: str, refresh_token: str, seen_ids: set = None, timeout: int = 90) -> str:
    log("Polling Microsoft Graph API for incoming Meta/Muse verification email...")
    token = get_graph_access_token(client_id, refresh_token)
    deadline = time.time() + timeout
    if seen_ids is None:
        seen_ids = set()

    while time.time() < deadline:
        url = "https://graph.microsoft.com/v1.0/me/messages?$top=5&$orderby=receivedDateTime%20desc"
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
        try:
            res = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())
            messages = res.get("value", [])
            for msg in messages:
                if msg.get("id") in seen_ids:
                    continue
                subject = msg.get("subject", "")
                preview = msg.get("bodyPreview", "")
                body = subject + " " + preview
                # Check for 6-digit verification code
                match = re.search(r"\b(\d{6})\b", body)
                if match:
                    code = match.group(1)
                    log(f"[+] Found fresh verification code in email: {code} (Subject: {subject})")
                    return code
        except Exception as e:
            log(f"  Graph poll warning: {e}")

        time.sleep(3)

    raise TimeoutError("Timed out waiting for fresh Meta verification email via Graph API")


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


def run(email: str = None, password: str = None, client_id: str = None, refresh_token: str = None, invite_code: str = None) -> bool:
    email = email or ENV_EMAIL
    password = password or ENV_PASSWORD
    client_id = client_id or ENV_CLIENT_ID
    refresh_token = refresh_token or ENV_REFRESH_TOKEN
    invite_code = invite_code or ENV_INVITE_CODE

    prefix = email.split("@")[0].lower() if email else "hotmail"

    log(f"Starting automated provisioning for: {email}")
    if not client_id or not refresh_token:
        log("[-] client_id and refresh_token must be provided or set in .env")
        return False

    profile_name = f"profile_hotmail_{secrets.token_hex(3)}"
    fp_seed = random.randint(100000, 999999)

    env = dict(os.environ)
    env["CDP_PORT"] = str(CDP_PORT)
    env["CDP_URL"] = CDP_URL
    env["PROFILE_NAME"] = profile_name
    env["FINGERPRINT"] = str(fp_seed)
    env["HEADLESS"] = "1"

    launch_js = SCRIPTS / "launch_profile.js"
    log(f"Spawning CloakBrowser instance on port {CDP_PORT}...")

    browser_proc = subprocess.Popen(
        ["node", str(launch_js)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    try:
        log("Waiting for browser CDP endpoint...")
        if not cdp_ready(CDP_PORT, timeout=40):
            log("[-] Browser CDP timed out")
            return False

        log("Browser CDP is ready. Connecting Playwright...")
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()

            # Listen for backend API responses
            def on_resp(res):
                try:
                    if "register-completion" in res.url or res.status >= 400:
                        txt = res.text()
                        log(f"[API RESP {res.status}] {res.url[:70]} -> {txt[:300]}")
                except Exception:
                    pass

            page.on("response", on_resp)

            # Block heavy streaming background media/video to conserve residential proxy bandwidth
            try:
                page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["media"] else route.continue_())
            except Exception:
                pass

            # 1. Enter email
            existing_ids = get_existing_message_ids(client_id, refresh_token)
            log(f"Entering email: {email} (existing message IDs before send: {len(existing_ids)})")
            if not enter_email(page, email):
                log("[-] Email entry rejected or failed")
                take_status_snapshot(page, f"{prefix}_email_failed.png")
                return False

            take_status_snapshot(page, f"{prefix}_otp_screen.png")
            log("[+] Reached OTP screen. Fetching code via Microsoft Graph API...")

            # 2. Retrieve OTP via Graph API
            code = poll_graph_otp(client_id, refresh_token, seen_ids=existing_ids, timeout=90)
            log(f"[+] Received OTP code: {code}")

            # 3. Enter OTP code
            if not enter_otp(page, code):
                log("[-] OTP was rejected by Meta")
                take_status_snapshot(page, f"{prefix}_otp_rejected.png")
                return False

            log("[+] OTP accepted! Proceeding to onboarding (birthday, card, invite)...")

            # 4. Finish onboarding
            if run_all_after_email(page, browser, invite_code=invite_code):
                log(f"[SUCCESS] {email} successfully registered and credited with 1B tokens!")
                take_status_snapshot(page, f"{prefix}_account_active.png")
                take_status_snapshot(page, "hotmail_account_active.png")
                accounts._upsert(
                    email,
                    password=password,
                    status="active",
                    created_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
                print("\n" + "=" * 60)
                print(f"ACCOUNT PROVISIONED SUCCESSFULLY: {email}")
                print(f"INVITE REDEEMED: {invite_code} (1 Billion Tokens)")
                print("=" * 60 + "\n")
                return True
            else:
                log("[-] Onboarding did not finish cleanly")
                take_status_snapshot(page, f"{prefix}_onboarding_failed.png")
                return False

    finally:
        log("Cleaning up browser process...")
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(browser_proc.pid)], capture_output=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automate Hotmail Muse Account Creation")
    parser.add_argument("--email", default=None, help="Hotmail address")
    parser.add_argument("--password", default=None, help="Hotmail password")
    parser.add_argument("--client-id", default=None, help="Microsoft Graph Client ID")
    parser.add_argument("--refresh-token", default=None, help="Microsoft Graph Refresh Token")
    parser.add_argument("--invite-code", default=None, help="Muse Invite Code")
    args = parser.parse_args()

    success = run(
        email=args.email,
        password=args.password,
        client_id=args.client_id,
        refresh_token=args.refresh_token,
        invite_code=args.invite_code,
    )
    if not success:
        sys.exit(1)
