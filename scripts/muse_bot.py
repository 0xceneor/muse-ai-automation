import sys
import time
import argparse
import os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import accounts

CDP_URL = os.getenv("CDP_URL", "http://127.0.0.1:9222")

EMAIL_SEL = 'input[placeholder*="Mobile number or email"], input[aria-label*="Mobile number or email"], input[inputmode="email"]'
OTP_SEL = 'input[autocomplete="one-time-code"]'
CONTINUE_SEL = 'button:has-text("Continue"), button[type="submit"]'
CONFIRM_SEL = 'button:has-text("Confirm"), button[type="submit"]'
BIRTHDAY_SEL_COUNT = 3

_t0 = time.time()


def log(msg):
    print(f"[{time.time() - _t0:6.1f}s] {msg}", flush=True)


def get_page(browser):
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

    def on_req(req):
        if "register-completion" in req.url:
            log(f"[API REQ] {req.url} -> {req.post_data}")

    def on_resp(res):
        try:
            if "register-completion" in res.url or res.status >= 400:
                txt = res.text()
                log(f"[API RESP {res.status}] {res.url[:70]} -> {txt[:300]}")
        except Exception:
            pass

    page.on("request", on_req)
    page.on("response", on_resp)
    return page


def which_screen(page):
    """Which onboarding stage the resumed page is sitting on."""
    try:
        if page.locator(OTP_SEL).count() > 0:
            return "otp"
        if page.locator(EMAIL_SEL).count() > 0:
            return "email"
        if page.locator("select").count() >= BIRTHDAY_SEL_COUNT:
            return "birthday"
    except Exception:
        pass
    return "unknown"


def wait_for_stage(page, stage, timeout=90):
    """The load event never fires here (hanging media), so poll the DOM.

    Hydration is implied for a fully rendered stage; the caller verifies that
    typing actually registers before acting.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if which_screen(page) == stage:
            return True
        time.sleep(0.5)
    return False


def take_status_snapshot(page, filename="muse_status.png"):
    os.makedirs("artifacts", exist_ok=True)
    out_path = os.path.abspath(os.path.join("artifacts", filename))
    page.screenshot(path=out_path)
    log(f"screenshot -> {out_path}")
    log(f"url: {page.url}")


def hydrated(page, selector):
    """React attaches __reactProps to an element once it has taken it over."""
    try:
        return page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                return Object.keys(el).some(k => k.startsWith('__reactProps'));
            }""",
            selector,
        )
    except Exception:
        return False


def wait_hydrated(page, selector, timeout=90):
    """The load event never fires here (hanging media), so poll for hydration."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if hydrated(page, selector):
            return True
        time.sleep(0.5)
    return False


def wait_enabled(page, selector, timeout=20):
    """A server-rendered disabled button only enables once React state is real."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            el = page.locator(selector).first
            if el.count() > 0 and el.is_visible() and not el.is_disabled():
                return True
        except Exception:
            pass
        time.sleep(0.25)
    return False


def dismiss_remembered(page):
    """A reused profile shows a saved-account chip instead of the email field."""
    link = page.locator('text="Use another account"')
    if link.count() > 0 and link.first.is_visible():
        log("remembered account found, choosing 'Use another account'")
        link.first.click()
        time.sleep(1.5)
        return True
    return False


def type_verified(page, locator, text, enable_selector, delay=35, attempts=5):
    """Type, then confirm the app actually accepted it.

    The authoritative signal is the submit button enabling, not the DOM value:
    before hydration the value lands but React never sees it.
    """
    for attempt in range(1, attempts + 1):
        locator.click()
        locator.fill("")
        for ch in text:
            locator.type(ch, delay=delay)
        time.sleep(0.4)

        if enable_selector and wait_enabled(page, enable_selector, timeout=4):
            log(f"field accepted (value={text!r})")
            return True

        log(f"submit stayed disabled (attempt {attempt}/{attempts}), re-typing")
        time.sleep(1.5)
    return False


def enter_email(page, email):
    log("waiting for the signup form to hydrate...")
    if not wait_hydrated(page, EMAIL_SEL):
        log("email form never hydrated")
        take_status_snapshot(page, "muse_no_input.png")
        return False

    dismiss_remembered(page)

    inp = page.locator(EMAIL_SEL)
    if inp.count() == 0:
        log("email input missing")
        take_status_snapshot(page, "muse_no_input.png")
        return False

    log(f"typing email: {email}")
    if not type_verified(page, inp.first, email, CONTINUE_SEL):
        log("email never registered with the app")
        take_status_snapshot(page, "muse_email_stuck.png")
        return False

    log("clicking Continue")
    page.locator(CONTINUE_SEL).first.click()

    deadline = time.time() + 50
    retry_cooldown = time.time() + 6
    while time.time() < deadline:
        dialog = page.locator('[role="dialog"]')
        if dialog.count() > 0 and dialog.first.is_visible():
            text = " ".join(dialog.first.inner_text().split())
            if any(term in text.lower() for term in ("something went wrong", "can't", "cannot", "aren't")):
                log(f"dialog on email screen: {text[:200]}")
                take_status_snapshot(page, "muse_rejected.png")
                return False

        # If inline error appears (e.g. "We couldn't send a code. Try again."), re-click Continue
        err_loc = page.get_by_text("couldn't send a code")
        if err_loc.count() > 0 and err_loc.first.is_visible() and time.time() > retry_cooldown:
            log("Inline error 'couldn't send a code' detected. Re-clicking Continue...")
            try:
                page.locator(CONTINUE_SEL).first.click()
            except Exception:
                pass
            retry_cooldown = time.time() + 8

        if page.locator(OTP_SEL).count() > 0 or page.get_by_text("Enter your code").count() > 0:
            log("OTP screen reached")
            return True
        time.sleep(0.5)

    log("OTP screen did not appear")
    take_status_snapshot(page, "muse_post_email.png")
    return False


def enter_otp(page, otp_code):
    """The OTP input is sr-only, so focus + keyboard, then synthetic events.

    The Confirm button keeps its disabled attribute even when the code is
    accepted, so it is clicked with force rather than waited on.
    """
    code = str(otp_code).strip()
    if not wait_hydrated(page, OTP_SEL, timeout=30):
        log("OTP input never appeared/hydrated")
        take_status_snapshot(page, "muse_otp_missing.png")
        return False

    inp = page.locator(OTP_SEL)
    log(f"entering OTP {code}")
    try:
        inp.first.focus()
        page.keyboard.type(code, delay=50)
    except Exception:
        pass

    page.evaluate(
        f"""() => {{
            const el = document.querySelector('input[autocomplete="one-time-code"]');
            if (el) {{
                el.value = "{code}";
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}"""
    )

    deadline = time.time() + 8
    while time.time() < deadline:
        try:
            if inp.first.input_value() == code:
                break
        except Exception:
            pass
        time.sleep(0.3)

    log("clicking Confirm")
    page.locator(CONFIRM_SEL).first.click(force=True)

    deadline = time.time() + 45
    while time.time() < deadline:
        dialog = page.locator('[role="dialog"]')
        if dialog.count() > 0:
            log("dialog: " + " ".join(dialog.first.inner_text().split())[:200])
            return False
        if page.locator(OTP_SEL).count() == 0:
            log("OTP accepted, moved on")
            return True
        time.sleep(0.5)

    log("still on the OTP screen")
    take_status_snapshot(page, "muse_post_otp.png")
    return False


def _connect():
    log(f"connecting over CDP at {CDP_URL}")
    playwright = sync_playwright().start()
    browser = playwright.chromium.connect_over_cdp(CDP_URL)
    return playwright, browser, get_page(browser)


def action_submit_email(email):
    playwright, browser, page = _connect()
    try:
        if enter_email(page, email):
            take_status_snapshot(page, "muse_post_email.png")
    finally:
        playwright.stop()


def action_enter_otp(otp_code):
    playwright, browser, page = _connect()
    try:
        if enter_otp(page, otp_code):
            take_status_snapshot(page, "muse_post_otp.png")
    finally:
        playwright.stop()


def create_full_account(session_label=None, invite_code=None):
    """Whole signup in one browser session.

    Muse's signup session does not survive the browser restarting, so the email
    -> OTP -> birthday -> card -> redeem sequence has to run without any stage
    boundary that would drop the cookie.
    """
    from automate_account import run_all_after_email

    acct = accounts.create_and_record()
    playwright, browser, page = _connect()
    try:
        if not enter_email(page, acct["address"]):
            accounts.set_status(acct["address"], "failed:no_email_input")
            return None
        accounts.set_status(acct["address"], "submitted")

        token = accounts.login(acct["address"], acct["password"])
        code = accounts.wait_for_otp(token)
        log(f"OTP received: {code}")
        if not enter_otp(page, code):
            accounts.set_status(acct["address"], "failed:otp_rejected")
            return None
        accounts.set_status(acct["address"], "otp_verified")

        if run_all_after_email(page, browser, invite_code):
            accounts.set_status(acct["address"], "active")
            log(f"✅ {acct['address']} active")
            return acct
        accounts.set_status(acct["address"], "failed:onboarding")
        return None
    finally:
        playwright.stop()


def action_new_account():
    acct = accounts.create_and_record()
    playwright, browser, page = _connect()
    try:
        if not enter_email(page, acct["address"]):
            accounts.set_status(acct["address"], "failed:no_email_input")
            sys.exit(1)
        accounts.set_status(acct["address"], "submitted")
        take_status_snapshot(page, "muse_post_email.png")
    finally:
        playwright.stop()
    log("waiting for the OTP mail")


def action_fetch_otp(address=None):
    row = None
    if address:
        row = next((r for r in accounts._read_ledger() if r["address"] == address), None)
    if row is None:
        row = accounts.last_pending()
    if row is None:
        log("no pending account, run --new-account first")
        sys.exit(1)

    token = accounts.login(row["address"], row["password"])
    log(f"polling inbox for {row['address']}")
    code = accounts.wait_for_otp(token)
    log(f"OTP received: {code}")

    playwright, browser, page = _connect()
    try:
        if not wait_for_stage(page, "otp"):
            log(f"browser is on {which_screen(page)}, not the OTP screen")
            take_status_snapshot(page, "muse_wrong_stage.png")
            accounts.set_status(row["address"], "failed:wrong_stage")
            sys.exit(1)
        if not enter_otp(page, code):
            accounts.set_status(row["address"], "failed:otp_rejected")
            sys.exit(1)
        accounts.set_status(row["address"], "otp_verified")
        take_status_snapshot(page, "muse_post_otp.png")
    finally:
        playwright.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Muse.ai CDP Automation Bot")
    parser.add_argument("--one", action="store_true",
                        help="Full signup for one account in a single browser session")
    parser.add_argument("--submit-email", type=str, help="Submit a specific email to start registration")
    parser.add_argument("--otp", type=str, help="Enter a 6-digit OTP verification code")
    parser.add_argument("--new-account", action="store_true", help="Mint a mail.tm inbox, record it, and submit it")
    parser.add_argument("--fetch-otp", action="store_true", help="Fetch the OTP for the last pending account and submit it")
    parser.add_argument("--account", type=str, help="Address to use with --fetch-otp")
    parser.add_argument("--status", action="store_true", help="Inspect current browser status")

    args = parser.parse_args()

    if args.one:
        if create_full_account() is None:
            sys.exit(1)
    elif args.new_account:
        action_new_account()
    elif args.fetch_otp:
        action_fetch_otp(args.account)
    elif args.submit_email:
        action_submit_email(args.submit_email)
    elif args.otp:
        action_enter_otp(args.otp)
    elif args.status:
        playwright, browser, page = _connect()
        try:
            take_status_snapshot(page)
        finally:
            playwright.stop()
    else:
        parser.print_help()
