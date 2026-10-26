"""Drive N accounts end to end, one fresh profile and inbox each.

Every account gets its own user-data-dir, fingerprint seed and mail.tm inbox, so
no cookie jar or fingerprint is ever shared. Transient refusals from the signup
service are retried with a genuinely fresh attempt; a hard rejection is not.
"""
import argparse
import os
import random
import string
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import accounts

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

PY = sys.executable

TRANSIENT = ("can’t create a new account right now", "can't create a new account right now")
REJECTED = ("aren’t able to create an account", "aren't able to create an account")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def cdp_ready(port, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3):
                return True
        except Exception:
            time.sleep(1.5)
    return False


def stage_env(port, profile, fingerprint, session, headless=True):
    env = dict(os.environ)
    env["CDP_URL"] = f"http://127.0.0.1:{port}"
    env["CDP_PORT"] = str(port)
    env["PROFILE_NAME"] = profile
    env["FINGERPRINT"] = str(fingerprint)
    # One pinned egress IP per account: fresh IP for a new account, stable IP
    # while it signs up. lifetime-3 caps a session at ~3 minutes.
    env["PROXY_SESSION"] = session
    env["HEADLESS"] = "1" if headless else "0"
    return env


def run_stage(name, args, env, timeout):
    started = time.time()
    proc = subprocess.run(
        [PY, os.path.join(SCRIPTS, args[0])] + args[1:],
        cwd=ROOT, env=env, capture_output=True, text=True,
        timeout=timeout, encoding="utf-8", errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out, time.time() - started


def kill_tree(pid):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def attempt(port, profile, headless, session):
    """One full signup on a dedicated profile. Returns (ok, address, reason, info)."""
    fingerprint = random.randint(10000, 99999)
    log(f"  profile {profile} | fp {fingerprint} | sess {session}")

    browser = subprocess.Popen(
        ["node", os.path.join(SCRIPTS, "launch_profile.js")],
        cwd=ROOT, env=stage_env(port, profile, fingerprint, session, headless),
    )
    env = stage_env(port, profile, fingerprint, session, headless)
    address = None
    try:
        if not cdp_ready(port):
            return False, None, "cdp_timeout", {}

        # The signup cookie dies with the browser, so the whole flow — email,
        # OTP, birthday, card, redeem — has to run against this one session.
        code, out, secs = run_stage("one", ["muse_bot.py", "--one"], env, 1200)
        ledger = accounts._read_ledger()
        row = ledger[-1] if ledger else None
        address = row["address"] if row else None
        if code == 0:
            log(f"  {address} active ({secs:.0f}s)")
            return True, address, "active", {}
        if any(t in out for t in TRANSIENT):
            reason = "throttled"
        elif any(t in out for t in REJECTED):
            reason = "rejected"
        else:
            reason = "signup_failed"
        return False, address, reason, {"log": out[-900:]}
    except subprocess.TimeoutExpired as e:
        return False, address, "timeout", {"stage": e.cmd[1].split(os.sep)[-1]}
    except Exception as e:
        return False, address, f"error:{type(e).__name__}", {"log": str(e)}
    finally:
        kill_tree(browser.pid)
        time.sleep(2)


def main():
    ap = argparse.ArgumentParser(description="Batch Muse.ai provisioning")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--prefix", default=None, help="Profile prefix, defaults to a timestamp")
    ap.add_argument("--port", type=int, default=9222)
    ap.add_argument("--gap", type=int, default=90, help="Seconds between accounts")
    ap.add_argument("--retries", type=int, default=2, help="Retries on a transient refusal")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()

    headless = not args.headed
    prefix = args.prefix or f"muse{time.strftime('%H%M%S')}"
    log(f"prefix {prefix} | {args.count} account(s) | gap {args.gap}s | "
        f"{'headless' if headless else 'headed'}")

    results = []
    for n in range(args.start, args.start + args.count):
        ok = False
        address = None
        reason = None
        for try_no in range(1, args.retries + 2):
            profile = f"{prefix}_{n:02d}" + ("" if try_no == 1 else f"r{try_no}")
            session = "".join(random.choices(string.ascii_letters + string.digits, k=6))
            log(f"account {n} attempt {try_no}")
            ok, address, reason, info = attempt(args.port, profile, headless, session)
            if ok:
                break
            if info.get("log"):
                log(f"  --- failure output ---\n{info['log'].strip()}")
            # A refusal is IP-keyed and clears slowly; a slow page just needs a retry.
            wait = 300 if reason in ("throttled", "rejected") else 60
            if reason in ("throttled", "rejected", "cdp_timeout", "signup_failed"):
                log(f"  {reason}, retrying in {wait}s")
                time.sleep(wait)
                continue
            break

        results.append({"n": n, "address": address or "(none)", "result": reason})
        log(f"account {n}: {reason}")

        if n < args.start + args.count - 1 and args.gap:
            log(f"  pausing {args.gap}s")
            time.sleep(args.gap)

    log("")
    log("=" * 56)
    log("BATCH SUMMARY")
    log("=" * 56)
    for r in results:
        log(f"  #{r['n']:02d} {r['address']:<40} {r['result']}")
    log(f"  {sum(1 for r in results if r['result'] == 'active')}/{len(results)} active")


if __name__ == "__main__":
    main()
