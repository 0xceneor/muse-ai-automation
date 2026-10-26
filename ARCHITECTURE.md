# Muse.ai Automation Pipeline — Technical Architecture & Deep Dive

[English](ARCHITECTURE.md) | [简体中文](ARCHITECTURE_ZH.md)

This document provides a comprehensive technical breakdown of the **Muse.ai** onboarding pipeline, the underlying Meta Account authentication flow, security & bot-detection defenses, and the Playwright CDP evasion strategies implemented in this repository.

---

## 1. Muse.ai & Meta Infrastructure Architecture

Muse.ai is a next-generation autonomous personal AI agent platform built by Meta. Account provisioning and verification are governed by Meta's shared account infrastructure:

```
┌────────────────────────────────────────────────────────┐
│                        User Client                     │
│    (CloakBrowser + Playwright CDP on 127.0.0.1:9222)   │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                Vercel Edge / Cloudflare CDN            │
│         - TLS Fingerprinting (JA3/JA4, HTTP/2)         │
│         - Temporary 307 Redirect to Auth Subsystem     │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│              auth.muse.ai / Meta Identity              │
│         - Proxygen Reverse Proxy Layer                 │
│         - Hatch Telemetry (Sentry & Facebook Reports)  │
│         - Email / SMS OTP Delivery Engine              │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│               Stripe & Meta Payment Gateway            │
│         - $1.00 Refundable Age Verification Hold       │
│         - BIN & Geolocation ZIP Validation             │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                Muse Chat & Token Services              │
│         - Free Plan: Weekly rate-limited tokens        │
│         - Referral Engine: 1B Unexpiring Tokens        │
└────────────────────────────────────────────────────────┘
```

---

## 2. Onboarding State Machine

The account registration and activation sequence operates as a deterministic 7-stage state machine:

```
  ┌──────────────┐
  │ 1. Landing   │ ──► Click 'Use phone or email'
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ 2. Email     │ ──► Type email + Submit form
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ 3. OTP Code  │ ──► 6-digit email verification (Pierces sr-only overlay)
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ 4. Birthday  │ ──► Select 18+ adult date (Year <= 2002)
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ 5. TOS Terms │ ──► Accept /api/hatch/accept-tos via 'Get started'
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ 6. Card Age  │ ──► Resolve Egress IP ZIP -> Submit 16-digit card
  └──────┬───────┘
         │
         ▼
  ┌──────────────┐
  │ 7. Workspace │ ──► Open Settings -> Redeem invite code (RM99IU)
  └──────────────┘
```

---

## 3. Defense Evasion & DOM Challenges

### Challenge A: Intranet Probes & 502 Bad Gateway
* **Mechanism**: When Chromium launches, its network stack issues speculative queries to resolve single-word hostnames (e.g. `GET http://google/`) to detect local DNS search suffixes or intranet portals.
* **Failure Mode**: Upstream residential proxies fail to forward single-word hostnames and return `HTTP 502 Bad Gateway`.
* **Solution**: `LocalProxyBridge` acts as an HTTP/HTTPS proxy on `127.0.0.1:<port>`. It intercepts any request where `host` does not contain a dot (`.`), returning an immediate `302 Found` to Google Search. For valid FQDNs, it initiates an authenticated `CONNECT` tunnel to the upstream proxy.

### Challenge B: The `sr-only` Presentation Overlay Trap
* **Mechanism**: Both the OTP input screen and the Invite Code modal render an `<input>` element with the CSS class `sr-only` (screen-reader only, width 1px, opacity 0). A visual container `<div>` with `role="presentation"` is rendered directly on top.
* **Failure Mode**: Standard Playwright `page.click('input')` fails with:
  ```
  playwright._impl._errors.TimeoutError: Locator.click: Timeout 30000ms exceeded.
  <div role="presentation"> intercepts pointer events.
  ```
* **Solution**:
  1. Call `locator.focus()` to set focus programmatically without mouse hit-testing.
  2. Use `page.keyboard.type(code, delay=50)` to send real hardware key events.
  3. Dispatch synthetic `Event('input', { bubbles: true })` and `Event('change', { bubbles: true })` to force React 19 / Next.js internal synthetic state synchronizations.

### Challenge C: Fraud Scoring & Billing Address Mismatch
* **Mechanism**: Meta's age verification charges a \$1.00 refundable authorization hold to verify identity. The gateway inspects the card BIN, the card billing ZIP, and the connection egress IP.
* **Failure Mode**: Using a generic or default ZIP code (e.g. `90210` or `10001`) while routing through a proxy in Texas or Kansas triggers automated fraud score flags.
* **Solution**: The script dynamically queries `https://ipinfo.io/json` directly from the browser's execution context before rendering the form, extracting the exact postal code of the current residential exit IP and populating the ZIP input.

### Challenge D: Nested Settings Navigation & Hydration
* **Mechanism**: Muse.ai uses Next.js app router modals for Settings. If the modal was previously left on a sub-view (e.g., `Upgrade`), the "Redeem invite code" entry point is not present in the DOM.
* **Solution**:
  1. Inspect the modal header for `button[aria-label="Go back"]`.
  2. If present, click it to unwind the stack to the `General` root view.
  3. Target `[data-pel-click="invite_redeem_open_click"]` to launch the dedicated redemption modal.

---

## 4. Token & Referral Economics

| Tier / Feature | Allocation | Validity | Behavior |
| :--- | :--- | :--- | :--- |
| **Free Plan Default** | Rate-limited weekly | Resets every 7 days | Hard throttled upon exhaustion |
| **Invite Referral Grant** | **1,000,000,000 Tokens (1B)** | **Never expires** | Consumed before weekly quota |
| **Model Access** | Muse Wonder & Base | Included | Full tool calling and web execution |

---

## 5. Security & Privacy Safeguards
* **Zero Hardcoded Secrets**: All scripts strictly accept environment variables (`CARD_NUMBER`, `CARD_EXPIRY`, `CARD_CVV`, `PROXY_URL`).
* **Session Persistence**: User sessions, auth cookies, and local storage keys are isolated per profile in `~/.cloakbrowser/profiles/<id>/`, preventing cross-account contamination.
