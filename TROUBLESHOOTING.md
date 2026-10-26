# Muse.ai Automation — Troubleshooting & Operations Playbook

[English](TROUBLESHOOTING.md) | [简体中文](TROUBLESHOOTING_ZH.md)

Practical troubleshooting guide, debugging recipes, and recovery strategies for the Muse.ai automation pipeline.

---

## 1. Quick Diagnostic Commands

When an automation step pauses or unexpected behavior occurs, run these non-destructive diagnostics:

```bash
# 1. Take a screenshot and inspect visible text cues & inputs
python scripts/muse_bot.py --status

# 2. Check if CloakBrowser CDP is responding on port 9222
curl -s http://127.0.0.1:9222/json/version

# 3. Check browser egress IP and GeoIP information
curl -x http://127.0.0.1:<bridge_port> https://ipinfo.io/json
```

---

## 2. Common Scenarios & Resolutions

### Scenario 1: OTP Email Delayed or Resend Needed
* **Symptom**: The 6-digit OTP email is not received within 60 seconds.
* **Resolution**:
  Click the "Resend code" button directly in the running session:
  ```bash
  python -c "
  from playwright.sync_api import sync_playwright
  with sync_playwright() as p:
      b = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
      page = b.contexts[0].pages[0]
      page.locator('button:has-text(\"Resend code\"), text=\"Resend code\"').first.click()
      print('Resend triggered')
  "
  ```

---

### Scenario 2: Age / Card Verification Hangs on "Processing..."
* **Symptom**: Card confirmation button shows "Processing..." for over 20 seconds.
* **Root Cause**: Next.js client router failed to transition, or a 3D Secure / bank challenge frame opened.
* **Resolution**:
  1. Inspect the open frames:
     ```bash
     python -c "
     from playwright.sync_api import sync_playwright
     with sync_playwright() as p:
         b = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
         page = b.contexts[0].pages[0]
         print('Frames:', len(page.frames))
         for f in page.frames:
             print(' - Frame:', f.url)
     "
     ```
  2. Because the browser is running headed on your desktop, look at the browser window. If a bank OTP or 3DS challenge is presented, complete it directly in the open window.

---

### Scenario 3: Settings Modal Stuck on Sub-Page (Upgrade / Wallet)
* **Symptom**: `Redeem invite code` cannot be found because the Settings modal is open to a different tab.
* **Resolution**:
  Click the "Go back" arrow or close and reopen the Settings dialog:
  ```bash
  python -c "
  from playwright.sync_api import sync_playwright
  with sync_playwright() as p:
      b = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
      page = b.contexts[0].pages[0]
      back = page.locator('button[aria-label=\"Go back\"]')
      if back.count() > 0:
          back.first.click()
          print('Unwound navigation stack')
  "
  ```

---

### Scenario 4: Next.js Client Hydration State Mismatch
* **Symptom**: Programmatic inputs do not reflect in the internal form state when submitting.
* **Resolution**:
  Always dispatch synthetic DOM events after changing an input value:
  ```javascript
  element.value = "YOUR_VALUE";
  element.dispatchEvent(new Event('input', { bubbles: true }));
  element.dispatchEvent(new Event('change', { bubbles: true }));
  ```

---

## 3. Human Intervention Protocol

The entire pipeline is intentionally designed around **Headed CloakBrowser Sessions**:
* The actual Chromium browser window is always visible on your desktop screen.
* If any unforeseen security checkpoint, CAPTCHA, or 2FA verification appears, you can interact with the window directly with your physical mouse and keyboard.
* The Playwright automation script will cleanly detect the subsequent URL navigation without crashing.
