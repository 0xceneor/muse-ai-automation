"""Batch runner for Hotmail Muse.ai provisioning."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from automate_hotmail_account import run

def main():
    batch_file = ROOT / "batch_accounts.json"
    if len(sys.argv) > 1:
        batch_file = Path(sys.argv[1])

    if not batch_file.exists():
        print(f"[-] Batch file not found: {batch_file}")
        sys.exit(1)

    with open(batch_file, "r", encoding="utf-8") as f:
        accounts = json.load(f)

    print(f"\n[*] Loaded {len(accounts)} accounts from {batch_file}")
    results = {}

    for i, acc in enumerate(accounts, 1):
        email = acc.get("email")
        password = acc.get("password")
        client_id = acc.get("client_id")
        refresh_token = acc.get("refresh_token")
        invite_code = acc.get("invite_code") or os.getenv("INVITE_CODE", "RM99IU")

        print(f"\n{'='*70}")
        print(f"[*] Processing account {i}/{len(accounts)}: {email}")
        print(f"{'='*70}\n")

        try:
            success = run(
                email=email,
                password=password,
                client_id=client_id,
                refresh_token=refresh_token,
                invite_code=invite_code,
            )
            results[email] = "SUCCESS" if success else "FAILED"
        except Exception as e:
            print(f"[-] Error during {email}: {e}")
            results[email] = f"ERROR: {e}"

        if i < len(accounts):
            print("\n[*] Waiting 5 seconds before next account...\n")
            time.sleep(5)

    print(f"\n{'='*70}")
    print("BATCH PROCESSING COMPLETE - SUMMARY")
    print(f"{'='*70}")
    for email, status in results.items():
        print(f" - {email}: {status}")
    print(f"{'='*70}\n")

if __name__ == "__main__":
    main()
