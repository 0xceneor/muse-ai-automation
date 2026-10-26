# Muse.ai Mass Account Provisioning

[English](README.md) | [简体中文 (Mandarin)](README_ZH.md) | [Technical Architecture](ARCHITECTURE.md) | [Troubleshooting Playbook](TROUBLESHOOTING.md)

Unattended pipeline for creating **Muse.ai** accounts in bulk: disposable inboxes for the OTP, CloakBrowser for the fingerprint, residential proxies for the egress IP, and automatic invite-code redemption on every account. Every credential lands in a local ledger.

> **Anti-detect engine**: built on **[CloakBrowser (0xceneor/CloakBrowser)](https://github.com/0xceneor/CloakBrowser)** — 87 source-level C++ fingerprint patches, Desktop Profile Manager, and the local loopback proxy bridge.

---

## 1. Stack

Muse.ai runs on Meta's shared account and risk infrastructure, which fingerprints the device and scores the payment on every signup. Each layer of this stack exists to keep a run clean:

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

### Evasion mechanisms

1. **Stealth fingerprint coherence**:
   - Pinned Windows 11 persona via `--fingerprint-platform=windows` and `--fingerprint-windows-font-metrics`.
   - Screen geometry offset for the Windows taskbar: `--fingerprint-taskbar-height=48`.
   - Anti-tamper preset: synthetic Canvas/WebGL noise is disabled (`--fingerprint-noise=false`) so hash-tamper tripwires stay quiet.
2. **Local loopback proxy bridge**:
   - Upstream residential proxies with authentication return `502 Bad Gateway` on Chromium's single-word background omnibox probes (e.g. `http://google/`).
   - A dedicated Node.js `LocalProxyBridge` listens on `127.0.0.1:<port>`, answers non-FQDN probes itself, and manages upstream authentication transparently. TLS upstreams are supported.
3. **WebRTC leak defense**:
   - `--webrtc-ip-handling-policy=disable_non_proxied_udp` and `--enforce-webrtc-ip-permission-check` stop UDP-based leaks of the real IP.
4. **Disposable inboxes and IP-matched billing**:
   - Each account gets a throwaway mail.tm inbox, so a run is bounded by proxy and card throughput, not by mailbox supply.
   - The billing ZIP is pulled from the live egress IP, so the card's address agrees with the proxy's geolocation instead of tripping the risk score.

---

## 2. Layout

```
muse-ai-automation/
├── accounts.csv              # Credential ledger (written at runtime, gitignored)
├── requirements.txt          # Python dependencies
├── package.json              # Node.js dependencies
├── .env.example              # Configuration template
└── scripts/
    ├── launch_profile.js     # Headed CloakBrowser launcher with local bridge
    ├── accounts.py           # mail.tm inboxes + credential ledger
    ├── muse_bot.py           # CLI automation bot (CDP driver)
    └── automate_account.py   # Onboarding, card verification, invite redemption
```

---

## 3. Per-account pipeline

```
[Start profile]                      (once per account, fresh profile dir)
       │
       ▼
[python scripts/muse_bot.py --new-account]
  ├─ Mint mail.tm inbox
  ├─ Append address + password to accounts.csv
  └─ Submit email
       │
       ▼
[python scripts/muse_bot.py --fetch-otp]
  ├─ Poll the inbox for the 6-digit code
  └─ Submit it (pierces the sr-only hidden input)
       │
       ▼
[python scripts/automate_account.py --account <address>]
  ├─ Select 18+ random adult birthday
  ├─ Accept terms disclosure
  ├─ Read egress IP, set matching ZIP, submit card
  └─ Redeem invite code → 1B tokens credited
       │
       ▼
[Status "active" in accounts.csv]
```

`--new-account` and `--fetch-otp` work as a pair. `--fetch-otp` targets the most recent account still pending, unless `--account` names one explicitly; both forms are equivalent to the plain `--submit-email` / `--otp` steps but with the inbox handled for you.

---

## 4. Running

### 1. Prerequisites
- **Node.js**: v20+ or v24+
- **Python**: 3.10+
- **[CloakBrowser](https://github.com/0xceneor/CloakBrowser)**: stealth Chromium binary installed (`~/.cloakbrowser/chromium-*/chrome.exe`)

```bash
pip install -r requirements.txt
npm install
```

### 2. Configure
Copy `.env.example` to `.env` — both Python scripts load it automatically:
```bash
cp .env.example .env
```
```ini
PROXY_URL=http://username:password@host:port
CARD_NUMBER=4000123456789010
CARD_EXPIRY=MM/YY
CARD_CVV=000
INVITE_CODE=YOUR_INVITE_CODE
```
`INVITE_CODE` is optional. With it set, onboarding ends in redemption; without it, the run stops once the workspace loads and the account is still usable.

### 3. One account
```bash
node scripts/launch_profile.js          # terminal 1, leave running
python scripts/muse_bot.py --new-account     # terminal 2
python scripts/muse_bot.py --fetch-otp
python scripts/automate_account.py
```

### 4. Many accounts
Give each account its own profile and port so browser state never carries over:

```bash
# terminal 1 — one browser per account, each on its own profile and port
PROFILE_NAME=acct_02 CDP_PORT=9223 node scripts/launch_profile.js
```

```bash
# terminal 2 — point the drivers at that port
export CDP_URL=http://127.0.0.1:9223
python scripts/muse_bot.py --new-account && \
python scripts/muse_bot.py --fetch-otp && \
python scripts/automate_account.py
```

Pass `--account <address>` to `automate_account.py` to have it mark that row `active` when the run finishes. Without it the onboarding still happens; the ledger row just keeps its last status. `CDP_URL` must match the `CDP_PORT` of the browser you are driving.

`Launch-Muse-Automation.cmd` drives a single account end to end on Windows: it checks dependencies, brings the browser up, then runs inbox, OTP and onboarding in order, passing the new address through the ledger as it goes.

---

## 5. Credential ledger

`accounts.csv` sits next to the repo root (override with `LEDGER_PATH`):

| Column | Meaning |
| :--- | :--- |
| `address` | Disposable address on mail.tm |
| `password` | Inbox password — needed to poll for the code |
| `inbox_id` | mail.tm account id |
| `created_at` | Local timestamp |
| `status` | `inbox_created` → `submitted` → `otp_verified` → `active`, or `failed:<reason>` |

Rows are appended the moment an inbox is minted, so an interrupted run never strands an account. Muse itself is passwordless: sign-in is by emailed code, which is why the inbox password is the credential that matters.

---

## 6. Known failure points

| Challenge | Root cause | Solution |
| :--- | :--- | :--- |
| **502 Bad Gateway** | Chromium omnibox intranet probes to the upstream proxy | `LocalProxyBridge` answers single-word hostnames on loopback itself |
| **OTP input timeout** | Input is `sr-only`, covered by a `role="presentation"` div | Focus programmatically, type with `page.keyboard.type()`, dispatch synthetic events |
| **ZIP code rejection** | Billing address disagrees with the proxy geolocation | Pull the `postal` code of the current egress IP from `https://ipinfo.io/json` |
| **Settings overlay** | Nested modals in the Settings view | Target `[data-pel-click="invite_redeem_open_click"]` after unwinding with `Go back` |
| **OTP never arrives** | Disposable domain throttled or filtered | `--fetch-otp` polls for three minutes; switch `PROXY_URL` for a fresh IP and mint a new inbox |

---

## License

MIT License.
