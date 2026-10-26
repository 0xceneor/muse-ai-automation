import sys
import time
import argparse
import os
from playwright.sync_api import sync_playwright

CDP_URL = os.getenv("CDP_URL", "http://127.0.0.1:9222")

def get_page(browser):
    for context in browser.contexts:
        for page in context.pages:
            if "muse.ai" in page.url or "meta.ai" in page.url:
                return page
    if browser.contexts and browser.contexts[0].pages:
        return browser.contexts[0].pages[0]
    if browser.contexts:
        return browser.contexts[0].new_page()
    context = browser.new_context()
    return context.new_page()

def take_status_snapshot(page, filename="muse_status.png"):
    os.makedirs("artifacts", exist_ok=True)
    out_path = os.path.abspath(os.path.join("artifacts", filename))
    page.screenshot(path=out_path)
    print(f"[*] Screenshot saved to: {out_path}")
    print(f"[*] Page URL: {page.url}")
    print(f"[*] Page Title: {page.title()}")

    texts = page.evaluate('''() => {
        const elements = document.querySelectorAll('h1, h2, h3, p, label, button, [role="alert"], [data-slot="text"]');
        return Array.from(elements).map(e => e.innerText.trim()).filter(t => t.length > 0 && t.length < 250);
    }''')
    print("[*] Key visible text:")
    seen = set()
    for t in texts:
        clean = " ".join(t.split())
        if clean not in seen and len(clean) > 2:
            seen.add(clean)
            print(f"    - {clean}")
            if len(seen) >= 15:
                break

    inputs = page.locator("input").all()
    print(f"[*] Found {len(inputs)} inputs:")
    for i, inp in enumerate(inputs):
        try:
            print(f"    [{i}] type={inp.get_attribute('type')} placeholder={inp.get_attribute('placeholder')} value='{inp.input_value()}'")
        except Exception as e:
            print(f"    [{i}] error: {e}")

def action_submit_email(email):
    with sync_playwright() as p:
        print(f"[*] Connecting to browser over CDP at {CDP_URL}...")
        browser = p.chromium.connect_over_cdp(CDP_URL)
        page = get_page(browser)
        print(f"[*] Active page URL: {page.url}")

        btn_use = page.locator('button:has-text("Use phone or email")')
        if btn_use.count() > 0 and btn_use.first.is_visible():
            print("[*] Clicking 'Use phone or email' button...")
            btn_use.first.click()
            time.sleep(1.5)

        inp = page.locator('input[placeholder*="Mobile number or email"], input[aria-label*="Mobile number or email"]')
        if inp.count() == 0:
            inp = page.locator('input[type="email"], input[inputmode="email"]')

        if inp.count() == 0:
            btn_login = page.locator('button:has-text("Log in")')
            if btn_login.count() > 0 and btn_login.first.is_visible():
                print("[*] Clicking 'Log in' button...")
                btn_login.first.click()
                time.sleep(1.5)
                inp = page.locator('input[placeholder*="Mobile number or email"]')

        if inp.count() == 0:
            print("[!] Could not locate email input directly.")
            take_status_snapshot(page, "muse_no_input.png")
            return

        print(f"[*] Typing email: {email}")
        inp.first.click()
        inp.first.fill("")
        for ch in email:
            inp.first.type(ch, delay=35)
            time.sleep(0.01)

        time.sleep(0.5)

        btn = page.locator('button:has-text("Continue"), button[type="submit"]')
        if btn.count() > 0:
            print("[*] Clicking Continue button...")
            btn.first.click()
        else:
            inp.first.press("Enter")

        time.sleep(5)
        print("[*] Post-submission state:")
        take_status_snapshot(page, "muse_post_email.png")

def action_enter_otp(otp_code):
    with sync_playwright() as p:
        print(f"[*] Connecting to browser over CDP at {CDP_URL}...")
        browser = p.chromium.connect_over_cdp(CDP_URL)
        page = get_page(browser)

        otp_clean = str(otp_code).strip()
        inp_otp = page.locator('input[autocomplete="one-time-code"]')
        if inp_otp.count() > 0:
            try:
                inp_otp.focus()
                page.keyboard.type(otp_clean, delay=50)
            except Exception:
                pass

            page.evaluate(f'''() => {{
                const el = document.querySelector('input[autocomplete="one-time-code"]');
                if (el) {{
                    el.value = "{otp_clean}";
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
            }}''')

        time.sleep(1)
        btn = page.locator('button:has-text("Confirm"), button[type="submit"]')
        if btn.count() > 0:
            btn.first.click(force=True)

        time.sleep(5)
        take_status_snapshot(page, "muse_post_otp.png")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Muse.ai CDP Automation Bot")
    parser.add_argument("--submit-email", type=str, help="Submit email to start registration")
    parser.add_argument("--otp", type=str, help="Enter 6-digit OTP verification code")
    parser.add_argument("--status", action="store_true", help="Inspect current browser status")

    args = parser.parse_args()

    if args.submit_email:
        action_submit_email(args.submit_email)
    elif args.otp:
        action_enter_otp(args.otp)
    elif args.status:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(CDP_URL)
            page = get_page(browser)
            take_status_snapshot(page)
    else:
        parser.print_help()
