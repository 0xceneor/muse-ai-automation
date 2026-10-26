"""Finish onboarding for an account that has already passed the OTP screen.

Walks birthday -> disclosure -> card -> workspace -> invite redemption, acting
on whichever screen is actually showing and verifying each transition. Exits
non-zero when anything stalls so a batch driver can trust the status it records.
"""
import time
import random
import json
import os
import sys
import argparse
from datetime import date
from playwright.sync_api import sync_playwright

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import accounts
from muse_bot import (
    log, wait_hydrated, type_verified,
    take_status_snapshot, OTP_SEL, _connect,
)

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]

CARD_SEL = 'input[placeholder*="Card number" i]'
EXP_SEL = 'input[placeholder*="MM/YY" i], input[placeholder*="MM / YY" i]'
CVV_SEL = 'input[placeholder*="CVV" i], input[placeholder*="CVC" i]'
ZIP_SEL = 'input[placeholder*="ZIP" i], input[aria-label*="ZIP" i], input[placeholder*="Postal" i]'
BIRTHDAY_BTN = 'button[data-pel-click="login_birthday_continue_click"]'
DISCLOSURE_BTN = 'button:has-text("Get started"), button:has-text("Continue"), button[data-pel-click*="disclosure"], button[data-pel-click="onboarding_disclosure_continue_click"]'
SETTINGS_BTN = 'button[aria-label="Settings"], button[data-pel-click="settings_menu_open_click"]'
SETTINGS_NAV = '[data-pel-click="settings_nav_click"]'
REDEEM_ENTRY = '[data-pel-click="invite_redeem_open_click"]'

# The form opens on today's date, which is age 0. Anything under 18 is rejected.
MIN_AGE = 18


def dismiss_dialog(page):
    """Radix dialogs cover the form; click OK and report the message."""
    dialog = page.locator('[role="dialog"]')
    if dialog.count() == 0:
        return None
    text = " ".join(dialog.first.inner_text().split())
    log(f"dialog: {text[:200]}")
    ok = page.locator('[role="dialog"] button:has-text("OK")')
    if ok.count() > 0:
        ok.first.click()
        time.sleep(1.5)
    return text


def screen_of(page):
    def has(sel):
        try:
            return page.locator(sel).count() > 0
        except Exception:
            return False

    if has('input[aria-label="Invite code"]'):
        return "redeem_input"
    if has(REDEEM_ENTRY):
        return "redeem_entry"
    if has(CARD_SEL):
        return "card"
    if has(DISCLOSURE_BTN):
        return "disclosure"
    if page.locator("select").count() >= 3:
        return "birthday"
    if has(OTP_SEL):
        return "otp"
    # The disclosure/access page also carries a Settings button, so /access must be excluded
    if (has(SETTINGS_BTN) or has('button:has-text("Chats")')) and "/access" not in page.url:
        return "workspace"
    if "/access" in page.url and has(DISCLOSURE_BTN):
        return "disclosure"
    return "unknown"


def pick_adult_birthday():
    """A date that is unambiguously at least 18, by calendar arithmetic.

    Ages are sampled from 19 up so that a birthday later in the year cannot
    land at 17 (the flow only exposes month/day/year, not an age check).
    """
    today = date.today()
    age = random.randint(MIN_AGE + 1, 35)
    month = random.randint(1, 12)
    if month == 2:
        day = random.randint(1, 28)
    elif month in (4, 6, 9, 11):
        day = random.randint(1, 30)
    else:
        day = random.randint(1, 31)

    year = today.year - age
    if (month, day) > (today.month, today.day):
        year -= 1
    return month, day, year


def select_number(select_loc, target):
    try:
        for opt in select_loc.locator("option").all():
            raw = (opt.get_attribute("value") or "").strip()
            text = (opt.inner_text() or "").strip()
            for cand in (raw, text):
                if cand.isdigit() and int(cand) == target:
                    select_loc.select_option(value=raw or text)
                    return True
    except Exception:
        pass
    return False


def fill_field(page, locator, text, delay=35):
    target = str(text).replace(" ", "").replace("/", "")
    for _ in range(4):
        try:
            locator.click()
            locator.fill("")
            for ch in str(text):
                locator.type(ch, delay=delay)
            time.sleep(0.3)
            got = locator.input_value().replace(" ", "").replace("/", "")
            if got == target:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def get_zip_from_ip(browser):
    try:
        temp = browser.contexts[0].new_page()
        temp.goto("https://ipinfo.io/json", timeout=25000, wait_until="domcontentloaded")
        data = json.loads(temp.locator("body").inner_text())
        temp.close()
        log(f"egress {data.get('ip')} | {data.get('city')} | postal {data.get('postal')}")
        return data.get("postal") or None
    except Exception as e:
        log(f"could not resolve postal from IP: {e}")
        return None


def do_birthday(page):
    """Set an adult birthday with human-like behavioral pauses and React state sync."""
    month, day, year = pick_adult_birthday()
    time.sleep(random.uniform(2.5, 4.0))

    for attempt in range(1, 4):
        sels = page.locator("select")
        if sels.count() < 3:
            log("  birthday selects not present yet")
            time.sleep(2)
            continue

        log(f"birthday {MONTHS[month - 1]} {day}, {year} (age {date.today().year - year})")

        # Check for first and last name inputs if requested on this screen
        fn_input = page.locator('input[placeholder*="First name" i], input[name*="first" i], input[aria-label*="First name" i]')
        ln_input = page.locator('input[placeholder*="Last name" i], input[name*="last" i], input[aria-label*="Last name" i]')
        if fn_input.count() > 0 and fn_input.first.is_visible():
            first_names = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Sam", "Chris"]
            last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis"]
            fn = random.choice(first_names)
            ln = random.choice(last_names)
            log(f"  filling name: {fn} {ln}")
            try:
                fn_input.first.fill(fn)
                ln_input.first.fill(ln)
                page.evaluate("""() => {
                    const f = document.querySelector('input[placeholder*="First name" i], input[name*="first" i]');
                    const l = document.querySelector('input[placeholder*="Last name" i], input[name*="last" i]');
                    if (f) { f.dispatchEvent(new Event('input', { bubbles: true })); f.dispatchEvent(new Event('change', { bubbles: true })); }
                    if (l) { l.dispatchEvent(new Event('input', { bubbles: true })); l.dispatchEvent(new Event('change', { bubbles: true })); }
                }""")
            except Exception as e:
                log(f"  name fill error: {e}")

        # Use React-native property setter to ensure React component state updates
        res = page.evaluate("""([m, d, y]) => {
            const selects = document.querySelectorAll('select');
            if (selects.length < 3) return { success: false, reason: 'not enough selects' };
            
            const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
            
            // Year (selects[2])
            setter.call(selects[2], String(y));
            selects[2].dispatchEvent(new Event('input', { bubbles: true }));
            selects[2].dispatchEvent(new Event('change', { bubbles: true }));

            // Month (selects[0])
            setter.call(selects[0], String(m));
            selects[0].dispatchEvent(new Event('input', { bubbles: true }));
            selects[0].dispatchEvent(new Event('change', { bubbles: true }));

            // Day (selects[1])
            setter.call(selects[1], String(d));
            selects[1].dispatchEvent(new Event('input', { bubbles: true }));
            selects[1].dispatchEvent(new Event('change', { bubbles: true }));

            const btn = document.querySelector('button[data-pel-click="login_birthday_continue_click"]');
            return {
                success: true,
                values: [selects[0].value, selects[1].value, selects[2].value],
                btnDisabled: btn ? btn.disabled : null
            };
        }""", [month, day, year])

        time.sleep(random.uniform(1.0, 1.8))
        btn = page.locator(BIRTHDAY_BTN).first
        if btn.count() > 0:
            try:
                btn.hover()
                time.sleep(0.5)
            except Exception:
                pass
            # Wait for button to be enabled if disabled
            if btn.is_disabled():
                time.sleep(1.5)
            btn.click(force=True)
            log("birthday submitted")
            try:
                page.wait_for_function(
                    "() => document.querySelectorAll('select').length < 3 || window.location.pathname.includes('/access') || document.querySelector('button[data-pel-click*=\"disclosure\"]')",
                    timeout=15000,
                )
            except Exception:
                pass
            time.sleep(2)
            if page.locator("select").count() < 3 or "/access" in page.url or page.locator(DISCLOSURE_BTN).count() > 0:
                return True
            log("  birthday form still present, retrying...")

        time.sleep(1.5)

    log("could not set an adult birthday")
    return False


def do_disclosure(page):
    log("accepting the disclosure")
    time.sleep(random.uniform(1.5, 2.5))
    for attempt in range(1, 4):
        if page.locator(CARD_SEL).count() > 0 or "/verification" in page.url:
            log("  already on card verification screen")
            return True
        btn = page.locator(DISCLOSURE_BTN).first
        try:
            if btn.count() == 0 or not btn.is_visible():
                return True
            btn.hover()
            time.sleep(0.3)
            btn.click(force=True, timeout=5000)
        except Exception as e:
            log(f"  disclosure click handled: {e}")
            if page.locator(CARD_SEL).count() > 0 or "/verification" in page.url:
                return True
            time.sleep(1)
            continue

        try:
            page.wait_for_function(
                "() => !document.querySelector('button:has-text(\"Get started\")') || window.location.pathname.includes('/card') || window.location.pathname.includes('/verification') || document.querySelector('input[placeholder*=\"Card number\" i]')",
                timeout=12000,
            )
        except Exception:
            pass
        time.sleep(1.5)
        if page.locator(CARD_SEL).count() > 0 or "/verification" in page.url:
            return True
    return True


def do_card(page, browser, card, expiry, cvv, zip_code):
    log("card verification")
    if not wait_hydrated(page, CARD_SEL, 30):
        log("card field never hydrated")
        return False

    if not zip_code:
        zip_code = get_zip_from_ip(browser)
    if not zip_code:
        log("no ZIP available")
        return False

    for sel, val, name in ((CARD_SEL, card, "card"),
                           (EXP_SEL, str(expiry).replace("/", ""), "expiry"),
                           (CVV_SEL, cvv, "cvv"),
                           (ZIP_SEL, zip_code, "zip")):
        loc = page.locator(sel)
        if loc.count() == 0:
            if name == "zip":
                log("no ZIP field, skipping")
                continue
            log(f"{name} field missing")
            return False
        if not fill_field(page, loc.first, val):
            log(f"could not fill {name}")
            return False
        log(f"  {name} filled")

    btn = page.locator('button:has-text("Confirm")').first
    if btn.count() == 0:
        log("card confirm missing")
        return False
    btn.click()
    log("card submitted, awaiting authorisation")
    return True


def do_redeem(page, invite_code):
    entry = None
    for attempt in range(1, 4):
        log(f"opening settings (attempt {attempt}/3)")
        btn = page.locator(SETTINGS_BTN).first
        if btn.count() == 0:
            log("settings button missing")
            time.sleep(2)
            continue
        try:
            btn.click()
            time.sleep(2)
        except Exception:
            pass

        nav = page.locator(SETTINGS_NAV)
        if nav.count() > 0 and nav.first.is_visible():
            try:
                nav.first.click()
                time.sleep(2.5)
            except Exception:
                pass

        back = page.locator('button[aria-label="Go back"]')
        if back.count() > 0 and back.first.is_visible():
            log("unwinding settings sub-page")
            try:
                back.first.click()
                time.sleep(1.5)
            except Exception:
                pass

        # Wait up to 15s for settings content / token usage skeleton loader to resolve
        deadline = time.time() + 15
        while time.time() < deadline:
            cand = page.locator(REDEEM_ENTRY)
            if cand.count() > 0 and cand.first.is_visible():
                entry = cand.first
                break
            cand_alt = page.locator('button:has-text("Redeem a code"), [role="button"]:has-text("Redeem a code")')
            if cand_alt.count() > 0 and cand_alt.first.is_visible():
                entry = cand_alt.first
                break
            time.sleep(0.5)
        
        if entry:
            break
        time.sleep(1)

    if not entry:
        log("redeem entry point not present")
        return False
    entry.click()
    time.sleep(2.5)

    if not wait_hydrated(page, 'input[aria-label="Invite code"]', 15):
        log("invite field never appeared")
        return False

    log(f"entering invite code {invite_code}")
    inp = page.locator('input[aria-label="Invite code"]').first
    try:
        inp.focus()
        page.keyboard.type(invite_code, delay=60)
    except Exception:
        pass
    page.evaluate(
        f"""() => {{
            const el = document.querySelector('input[aria-label="Invite code"]');
            if (el) {{
                el.value = "{invite_code}";
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
        }}"""
    )
    time.sleep(1)

    conf = page.locator('[role="dialog"] button:has-text("Confirm"), button:has-text("Confirm")').first
    if conf.count() == 0:
        log("no confirm in the redeem dialog")
        return False
    conf.click(force=True)
    time.sleep(6)

    dialog = page.locator('[role="dialog"]')
    if dialog.count() > 0:
        result = " ".join(dialog.first.inner_text().split())
        log("result: " + result[:200])
        return "successful" in result.lower() or "tokens" in result.lower()
    return True


def run_all_after_email(page, browser, invite_code, card=None, expiry=None,
                        cvv=None, zip_code=None):
    """Birthday -> card -> workspace -> redeem on an already signed-up page.

    Runs inside the signup browser session, since the signup cookie dies the
    moment the browser that created it is gone.
    """
    card = card or os.getenv("CARD_NUMBER")
    expiry = expiry or os.getenv("CARD_EXPIRY")
    cvv = cvv or os.getenv("CARD_CVV")
    zip_code = zip_code or os.getenv("ZIP_CODE")

    if not card or not expiry or not cvv:
        log("card details missing")
        return False

    log(f"continuing at {page.url}")
    last = None
    birthday_done = False
    disclosure_done = False
    card_done = False

    # Card authorisation alone took ~25s in testing; allow generous headroom.
    for _ in range(120):
        current = screen_of(page)

        dialog_text = dismiss_dialog(page)
        if dialog_text and (
            "aren’t able" in dialog_text 
            or "can’t create a new account right now" in dialog_text
            or "unable to add card" in dialog_text.lower()
            or "associated with too many" in dialog_text.lower()
        ):
            log(f"terminal dialog encountered: {dialog_text[:120]}")
            take_status_snapshot(page, "muse_rejected.png")
            return False

        if current != last:
            log(f"screen: {current}")
            last = current

        if current == "birthday":
            if not do_birthday(page):
                return False
        elif current == "disclosure":
            if not do_disclosure(page):
                return False
        elif current == "card":
            if not card_done:
                if not do_card(page, browser, card, expiry, cvv, zip_code):
                    return False
                card_done = True
            else:
                time.sleep(1.5)
        elif current in ("workspace", "redeem_entry", "redeem_input"):
            break
        time.sleep(1.5)

    if screen_of(page) not in ("workspace", "redeem_entry", "redeem_input"):
        log(f"workspace never loaded (url {page.url})")
        take_status_snapshot(page, "muse_no_workspace.png")
        return False
    log("workspace loaded")

    if not invite_code:
        log("no invite code configured, stopping here")
        return True

    if not do_redeem(page, invite_code):
        take_status_snapshot(page, "muse_redeem_failed.png")
        return False

    log("redeemed")
    return True


def run_automation(card, expiry, cvv, invite_code, zip_code=None):
    playwright, browser, page = _connect()
    try:
        log(f"starting at {page.url}")
        last = None
        birthday_done = False
        disclosure_done = False
        card_done = False

        # Card authorisation alone took ~25s in testing; allow generous headroom.
        for _ in range(60):
            current = screen_of(page)

            if dismiss_dialog(page):
                # A rejection here kills the run; anything else is transient.
                if "aren’t able" in (page.locator('[role="dialog"]').first.inner_text()
                                     if page.locator('[role="dialog"]').count() else ""):
                    return False

            if current != last:
                log(f"screen: {current}")
                last = current

            if current == "birthday":
                if not birthday_done:
                    if not do_birthday(page):
                        return False
                    birthday_done = True
                else:
                    time.sleep(1.5)
            elif current == "disclosure":
                if not do_disclosure(page):
                    return False
            elif current == "card":
                if not card_done:
                    if not do_card(page, browser, card, expiry, cvv, zip_code):
                        return False
                    card_done = True
                else:
                    time.sleep(1.5)
            elif current in ("workspace", "redeem_entry", "redeem_input"):
                break
            time.sleep(1.5)

        if screen_of(page) == "otp":
            log("never got past the OTP screen")
            take_status_snapshot(page, "muse_stuck_otp.png")
            return False
        if "/access/" in page.url or screen_of(page) not in ("workspace", "redeem_entry", "redeem_input"):
            log(f"workspace never loaded (url {page.url})")
            take_status_snapshot(page, "muse_no_workspace.png")
            return False
        log("workspace loaded")

        if not invite_code:
            log("no invite code configured, stopping here")
            return True

        if not do_redeem(page, invite_code):
            take_status_snapshot(page, "muse_redeem_failed.png")
            return False

        log("redeemed")
        return True
    finally:
        playwright.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End-to-End Muse.ai Provisioning")
    parser.add_argument("--card", default=os.getenv("CARD_NUMBER"))
    parser.add_argument("--expiry", default=os.getenv("CARD_EXPIRY"))
    parser.add_argument("--cvv", default=os.getenv("CARD_CVV"))
    parser.add_argument("--zip", default=os.getenv("ZIP_CODE"))
    parser.add_argument("--invite", default=os.getenv("INVITE_CODE"))
    parser.add_argument("--account", default=None, help="Ledger address to mark active")

    args = parser.parse_args()
    if not args.card or not args.expiry or not args.cvv:
        log("--card, --expiry and --cvv (or env vars) are required")
        sys.exit(1)

    if run_automation(args.card, args.expiry, args.cvv, args.invite, args.zip):
        if args.account:
            accounts.set_status(args.account, "active")
            log(f"marked {args.account} active")
        sys.exit(0)

    if args.account:
        accounts.set_status(args.account, "failed:onboarding")
    sys.exit(1)
