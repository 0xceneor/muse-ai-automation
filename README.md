# Muse.ai Automation, Activation & Onboarding Methodology

[English](README.md) | [简体中文 (Mandarin)](README_ZH.md) | [Technical Architecture](ARCHITECTURE.md) | [Troubleshooting Playbook](TROUBLESHOOTING.md)

Production-grade automation methodology, technical architecture, and Playwright CDP scripts for provisioning, verifying, and activating **Muse.ai** accounts with CloakBrowser, residential proxies, and automated invite token redemption.

> **Core Anti-Detect Browser Engine**: Built on **[CloakBrowser (0xceneor/CloakBrowser)](https://github.com/0xceneor/CloakBrowser)** — featuring 87 source-level C++ fingerprint patches, Desktop Profile Manager, and integrated local loopback proxy bridging.

---

## 1. Architectural Stack & Evasion Tactics

Muse.ai and Meta account infrastructure enforce rigorous bot detection and device fingerprinting. To pass verification without checkpoints, the automation stack operates across four coordinated layers:

```
┌────────────────────────────────────────────────────────┐
│                   Playwright Automation                │
│       (CDP / connect_over_cdp to 127.0.0.1:9222)       │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                    CloakBrowser                        │
│    - Windows 11 platform persona                       │
│    - Taskbar height coherence (48px offset)            │
│    - Anti-tamper preset (disabled noise, MediaRouter)  │
│    - WebRTC leak protection (disable_non_proxied_udp)  │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│               LocalProxyBridge (Node.js)               │
│    - 127.0.0.1:<port> loopback listener                │
│    - Upstream proxy credential injection               │
│    - Eliminates 502 Bad Gateway intranet probe errors  │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│           Residential Proxy (US / Windows)             │
│    - Egress IP matching system timezone / locale       │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                   Target: Muse.ai                      │
└────────────────────────────────────────────────────────┘
```

### Core Evasion Mechanisms
1. **Stealth Fingerprint Coherence**:
   - Pinned Windows 11 persona via `--fingerprint-platform=windows` and `--fingerprint-windows-font-metrics`.
   - Screen geometry offset for the Windows taskbar: `--fingerprint-taskbar-height=48`.
   - Anti-tamper preset: Synthetic Canvas/WebGL noise is disabled (`--fingerprint-noise=false`) to prevent detection by hash-tamper tripwires.
2. **Local Loopback Proxy Bridge**:
   - Upstream residential proxies with authentication often return `502 Bad Gateway` on Chromium's single-word background omnibox probes (e.g. `http://google/`).
   - A dedicated Node.js `LocalProxyBridge` listens on `127.0.0.1:<port>`, intercepts non-FQDN probes, and manages upstream authentication transparently.
3. **WebRTC Leak Defense**:
   - Enforce `--webrtc-ip-handling-policy=disable_non_proxied_udp` and `--enforce-webrtc-ip-permission-check` to prevent UDP-based local IP exposure.

---

## 2. Directory Structure

```
muse-ai-automation/
├── README.md                 # Complete methodology & activation guide
├── requirements.txt          # Python dependencies
├── package.json              # Node.js dependencies
├── .env.example              # Configuration template
└── scripts/
    ├── launch_profile.js     # Headed CloakBrowser launcher with local bridge
    ├── muse_bot.py           # CLI automation bot (CDP driver)
    ├── automate_account.py   # Full end-to-end registration pipeline
    └── redeem_code.py        # Standalone invite code redeemer
```

---

## 3. End-to-End Registration Pipeline

```
[Start Profile]
       │
       ▼
[Enter Email] ──► [Wait for 6-Digit OTP]
                          │
                          ▼
[Submit OTP] (handles sr-only hidden input)
       │
       ▼
[Select Adult Birthday] (18+ random real date, e.g. 1995-1998)
       │
       ▼
[Accept Terms Disclosure] (click /api/hatch/accept-tos)
       │
       ▼
[Age Verification & Card Authorization]
  ├─ Inspect Egress IP from browser context
  ├─ Query GeoIP for accurate local postal/ZIP code
  └─ Fill 16-digit Card, MM/YY, CVV, and IP ZIP
       │
       ▼
[Redirect to Main Workspace] (https://muse.ai/)
       │
       ▼
[Open Settings -> Usage]
       │
       ▼
[Redeem Invite Code (RM99IU)] ──► [1 Billion Tokens Credited (Never Expires)]
```

---

## 4. Quick Start

### 1. Prerequisites
- **Node.js**: v20+ or v24+
- **Python**: 3.10+
- **[CloakBrowser](https://github.com/0xceneor/CloakBrowser)**: Stealth Chromium binary installed (`~/.cloakbrowser/chromium-*/chrome.exe`)

```bash
pip install -r requirements.txt
npm install
```

### 2. Configure Environment
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in your proxy, card details, and invite code:
```ini
PROXY_URL=http://username:password@host:port
CARD_NUMBER=4000123456789010
CARD_EXPIRY=MM/YY
CARD_CVV=000
INVITE_CODE=YOUR_INVITE_CODE
```

### 3. Launch Profile & Run Automation
Launch the headed browser session:
```bash
node scripts/launch_profile.js
```

In another terminal, run the automation pipeline:
```bash
# Step 1: Submit email
python scripts/muse_bot.py --submit-email your_email@domain.com

# Step 2: Once OTP is received, submit the code
python scripts/muse_bot.py --otp 123456

# Step 3: Run the full card verification & invite redemption
python scripts/automate_account.py
```

---

## 5. Automation Quirks & Solutions

| Challenge | Root Cause | Solution |
| :--- | :--- | :--- |
| **502 Bad Gateway** | Chromium omnibox intranet probes to upstream proxy | `LocalProxyBridge` intercepts single-word hostnames and provides loopback tunnel |
| **OTP Input Timeout** | Input has `class="sr-only"` obscured by presentation div | Focus element, type via `page.keyboard.type()`, and dispatch synthetic events |
| **ZIP Code Rejection** | Billing address mismatch with proxy geolocation | Dynamically fetch `postal` code from `https://ipinfo.io/json` via browser egress IP |
| **Settings Overlay** | Nested modals in Settings view | Target `[data-pel-click="invite_redeem_open_click"]` and handle `Go back` navigation |

---

## License
MIT License. For educational and authorized testing purposes.
