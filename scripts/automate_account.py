import time
import random
import json
import os
import argparse
from playwright.sync_api import sync_playwright

CDP_URL = os.getenv("CDP_URL", "http://127.0.0.1:9222")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

def get_zip_from_ip(browser):
    try:
        temp_page = browser.contexts[0].new_page()
        temp_page.goto("https://ipinfo.io/json", timeout=15000)
        data = json.loads(temp_page.inner_text("body"))
        temp_page.close()
        postal = data.get("postal", "76107")
        print(f"[*] Resolved Egress IP: {data.get('ip')} | City: {data.get('city')} | Postal: {postal}")
        return postal
    except Exception as e:
        print("[!] Could not auto-fetch postal from IP, fallback to 76107:", e)
        return "76107"

def run_automation(card_number, expiry, cvv, invite_code, zip_code=None):
    with sync_playwright() as p:
        print(f"[*] Connecting to CloakBrowser over CDP at {CDP_URL}...")
        browser = p.chromium.connect_over_cdp(CDP_URL)
        page = browser.contexts[0].pages[0]

        print(f"[*] Current URL: {page.url}")

        # Step 1: Adult Birthday (if on birthday screen)
        selects = page.locator("select").all()
        if len(selects) >= 3:
            b_year = str(random.randint(1992, 2002))
            b_month = random.choice(MONTHS)
            b_day = str(random.randint(1, 28))
            print(f"[*] Selecting 18+ adult birth date: {b_month} {b_day}, {b_year}")
            selects[0].select_option(label=b_month)
            time.sleep(0.3)
            selects[1].select_option(label=b_day)
            time.sleep(0.3)
            selects[2].select_option(label=b_year)
            time.sleep(0.5)

            btn_bday = page.locator('button:has-text("Confirm")')
            if btn_bday.count() > 0:
                print("[*] Confirming birthday...")
                btn_bday.first.click()
                time.sleep(6)

        # Step 2: Disclosure / Get Started
        if "disclosure" in page.url or page.locator('button:has-text("Get started")').count() > 0:
            print("[*] Accepting terms disclosure...")
            btn_start = page.locator('button[data-pel-click="onboarding_disclosure_continue_click"], button:has-text("Get started")')
            if btn_start.count() > 0:
                btn_start.first.click()
                time.sleep(6)

        # Step 3: Card Age Verification
        card_inp = page.locator('input[placeholder*="Card number" i]')
        if card_inp.count() > 0 or "verification" in page.url:
            if not zip_code:
                zip_code = get_zip_from_ip(browser)

            print("[*] Filling card number...")
            card_inp = page.locator('input[placeholder*="Card number" i]')
            card_inp.click()
            card_inp.fill("")
            for ch in str(card_number):
                card_inp.type(ch, delay=35)
                time.sleep(0.01)
            time.sleep(0.3)

            print("[*] Filling expiry date...")
            exp_inp = page.locator('input[placeholder*="MM/YY" i], input[placeholder*="MM / YY" i]')
            exp_inp.click()
            exp_inp.fill("")
            for ch in str(expiry).replace("/", ""):
                exp_inp.type(ch, delay=35)
                time.sleep(0.01)
            time.sleep(0.3)

            print("[*] Filling CVV...")
            cvv_inp = page.locator('input[placeholder*="CVV" i], input[placeholder*="CVC" i]')
            cvv_inp.click()
            cvv_inp.fill("")
            for ch in str(cvv):
                cvv_inp.type(ch, delay=35)
                time.sleep(0.01)
            time.sleep(0.3)

            print(f"[*] Filling IP-matched ZIP code: {zip_code}...")
            zip_inp = page.locator('input[placeholder*="ZIP" i], input[aria-label*="ZIP" i]')
            if zip_inp.count() > 0:
                zip_inp.click()
                zip_inp.fill("")
                for ch in str(zip_code):
                    zip_inp.type(ch, delay=35)
                    time.sleep(0.01)
            time.sleep(0.8)

            print("[*] Submitting verification card...")
            btn_card_confirm = page.locator('button:has-text("Confirm"), button[type="submit"]')
            if btn_card_confirm.count() > 0:
                btn_card_confirm.first.click()

            print("[*] Waiting for card authorization and redirect to workspace...")
            for i in range(15):
                time.sleep(2)
                if page.url == "https://muse.ai/" and page.locator('button[aria-label="Settings"]').count() > 0:
                    print("[*] Successfully loaded main workspace!")
                    break

        # Step 4: Settings & Invite Code Redemption
        print("[*] Opening Settings...")
        btn_settings = page.locator('button[aria-label="Settings"], button[data-pel-click="settings_menu_open_click"]')
        if btn_settings.count() > 0:
            btn_settings.first.click()
            time.sleep(1.5)
            menu_settings = page.locator('[role="menuitem"]:has-text("Settings")')
            if menu_settings.count() > 0:
                menu_settings.first.click()
                time.sleep(2)

        # Handle back button if on subpage
        btn_back = page.locator('button[aria-label="Go back"]')
        if btn_back.count() > 0 and btn_back.first.is_visible():
            btn_back.first.click()
            time.sleep(1)

        # Click Redeem invite code
        print("[*] Clicking Redeem invite code entrypoint...")
        redeem_cell = page.locator('[data-pel-click="invite_redeem_open_click"]')
        if redeem_cell.count() > 0:
            redeem_cell.first.click()
            time.sleep(2)

        inp_invite = page.locator('input[aria-label="Invite code"]')
        if inp_invite.count() > 0:
            print(f"[*] Entering invite code: {invite_code}...")
            try:
                inp_invite.focus()
                page.keyboard.type(invite_code, delay=50)
            except Exception:
                pass

            page.evaluate(f'''() => {{
                const el = document.querySelector('input[aria-label="Invite code"]');
                if (el) {{
                    el.value = "{invite_code}";
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            }}''')

            time.sleep(1)
            btn_redeem_confirm = page.locator('[role="dialog"] button:has-text("Confirm"), button:has-text("Confirm")')
            if btn_redeem_confirm.count() > 0:
                btn_redeem_confirm.first.click(force=True)

            print("[*] Waiting for redemption confirmation...")
            time.sleep(6)

        dialog = page.locator('[role="dialog"]')
        if dialog.count() > 0:
            print("[*] Result:\n", dialog.first.inner_text())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End-to-End Muse.ai Provisioning")
    parser.add_argument("--card", default=os.getenv("CARD_NUMBER"), help="16-digit card number")
    parser.add_argument("--expiry", default=os.getenv("CARD_EXPIRY"), help="MM/YY")
    parser.add_argument("--cvv", default=os.getenv("CARD_CVV"), help="3-digit CVV")
    parser.add_argument("--zip", default=os.getenv("ZIP_CODE", None), help="Postal/ZIP code")
    parser.add_argument("--invite", default=os.getenv("INVITE_CODE"), help="Referral invite code")

    args = parser.parse_args()
    if not args.card or not args.expiry or not args.cvv:
        print("[!] Error: --card, --expiry, and --cvv (or env variables) are required.")
        exit(1)
    run_automation(args.card, args.expiry, args.cvv, args.invite, args.zip)
