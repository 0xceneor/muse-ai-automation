"""Disposable inboxes (mail.tm) and the local credential ledger.

Every account gets a fresh throwaway inbox, so a run is not limited by a real
mailbox. Credentials are appended to accounts.csv as they are created, which
means an interrupted run still leaves every account it produced usable.
"""
import csv
import html as html_mod
import json
import os
import random
import re
import secrets
import string
import time
import urllib.error
import urllib.request

API = "https://api.mail.tm"
LEDGER = os.path.abspath(
    os.getenv("LEDGER_PATH")
    or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "accounts.csv")
)
FIELDS = ["address", "password", "inbox_id", "created_at", "status"]
OTP_RE = re.compile(r"\b(\d{6})\b")

_domains = None


def _get_opener():
    proxy = os.getenv("PROXY_URL")
    if proxy:
        return urllib.request.build_opener(urllib.request.ProxyHandler({"https": proxy, "http": proxy}))
    return urllib.request.build_opener()


def _request(method, path, payload=None, token=None, retries=5):
    body = json.dumps(payload).encode() if payload is not None else None
    opener = _get_opener()
    for attempt in range(retries):
        req = urllib.request.Request(API + path, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/146.0.0.0")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with opener.open(req, timeout=30) as resp:
                raw = resp.read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            # mail.tm throttles bursts; 429/422/503 clear after a pause.
            if e.code in (429, 422, 503) and attempt < retries - 1:
                time.sleep(2 + attempt * 3)
                continue
            raise RuntimeError(f"{method} {path} -> {e.code}: {detail}") from None
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(2 + attempt * 3)
                continue
            raise
    raise RuntimeError(f"{method} {path} exhausted retries")


def _pick_domain():
    global _domains
    if _domains is None:
        data = _request("GET", "/domains?page=1")
        _domains = [
            d["domain"]
            for d in data.get("hydra:member", [])
            if d.get("isActive") and not d.get("isPrivate")
        ]
        if not _domains:
            raise RuntimeError("mail.tm returned no usable public domain")
    return random.choice(_domains)


def _read_ledger():
    if not os.path.exists(LEDGER):
        return []
    with open(LEDGER, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_ledger(rows):
    with open(LEDGER, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _upsert(address, **fields):
    rows = [r for r in _read_ledger() if r["address"] != address]
    rows.append({**{k: "" for k in FIELDS}, "address": address, **fields})
    _write_ledger(rows)


def set_status(address, status):
    rows = _read_ledger()
    hit = False
    for row in rows:
        if row["address"] == address:
            row["status"] = status
            hit = True
    if hit:
        _write_ledger(rows)


def last_pending():
    """Most recently created account that has not finished onboarding yet."""
    for row in reversed(_read_ledger()):
        if row["status"] in ("inbox_created", "submitted", "otp_verified"):
            return row
    return None


def new_inbox():
    domain = _pick_domain()
    address = "muse" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(10)) + "@" + domain
    password = secrets.token_urlsafe(12)
    created = _request("POST", "/accounts", {"address": address, "password": password})
    inbox_id = created.get("id", "")
    _upsert(address, password=password, inbox_id=inbox_id,
            created_at=time.strftime("%Y-%m-%d %H:%M:%S"), status="inbox_created")
    return {"address": address, "password": password, "id": inbox_id}


def login(address, password):
    return _request("POST", "/token", {"address": address, "password": password})["token"]


def _message_text(message_id, token):
    full = _request("GET", "/messages/" + message_id, token=token)
    chunks = [full.get("text") or ""]
    raw_html = full.get("html")
    if isinstance(raw_html, list):
        raw_html = " ".join(str(c) for c in raw_html)
    chunks.append(re.sub(r"<[^>]+>", " ", raw_html or ""))
    return html_mod.unescape(" ".join(chunks))


def wait_for_otp(token, timeout=180, interval=4):
    """Poll the inbox until a 6-digit code shows up, newest message first."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = _request("GET", "/messages?page=1", token=token)
        for message in sorted(data.get("hydra:member", []),
                              key=lambda m: m.get("createdAt", ""), reverse=True):
            match = OTP_RE.search(_message_text(message["id"], token))
            if match:
                return match.group(1)
        time.sleep(interval)
    raise TimeoutError(f"no OTP arrived within {timeout}s")


def create_and_record():
    acct = new_inbox()
    print(f"[*] Inbox ready : {acct['address']}")
    print(f"[*] Inbox password: {acct['password']}")
    print(f"[*] Ledger      : {LEDGER}")
    return acct
