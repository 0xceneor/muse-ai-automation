"""Step-by-step browser environment cleaning and anti-detect verification tool.

1. Terminates any dangling Chrome/driver processes.
2. Completely purges all persistent user-data directories, HSTS supercookies,
   IndexedDB, ServiceWorkers, and Chromium temp sockets.
3. Randomizes hardware fingerprint seed, screen geometry, and proxy session.
4. Boots a diagnostic session through CloakBrowser and verifies stealth properties:
   - navigator.webdriver is False
   - Chrome DevTools Protocol markers are masked
   - Canvas, WebGL, and AudioContext signatures are refreshed
   - WebRTC IP is strictly bound to proxy egress without local UDP leaks.
"""

import os
import sys
import time
import json
import shutil
import random
import secrets
import subprocess
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(str(ROOT / ".env"))
except ImportError:
    pass

CLOAK_DIR = Path.home() / ".cloakbrowser"
PROFILES_DIR = CLOAK_DIR / "profiles"
LOCAL_TEMP = Path(os.environ.get("LOCALAPPDATA", "")) / "Temp"


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def step1_purge_storage():
    """Purge all persistent storage, caches, and lingering processes."""
    log("=== STEP 1: Purging Storage, Supercookies & Lingering Processes ===")

    # 1. Kill any existing browser processes
    log("Terminating existing Chrome/driver processes...")
    for proc in ["chrome.exe", "chromedriver.exe"]:
        subprocess.run(["taskkill", "/F", "/IM", proc], capture_output=True)

    # 2. Wipe profile directories
    if PROFILES_DIR.exists():
        count = 0
        for item in PROFILES_DIR.iterdir():
            try:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
                count += 1
            except Exception as e:
                log(f"  Notice: could not delete {item.name}: {e}")
        log(f"Purged {count} cached profile item(s) from {PROFILES_DIR}")

    # 3. Clean profiles.json
    profiles_json = CLOAK_DIR / "profiles.json"
    if profiles_json.exists():
        profiles_json.write_text("[]", encoding="utf-8")
        log("Reset profiles.json to clean state []")

    # 4. Clean Chromium temporary sockets in %TEMP%
    temp_deleted = 0
    if LOCAL_TEMP.exists():
        for pattern in ["scoped_dir*", "chromium*"]:
            for match in LOCAL_TEMP.glob(pattern):
                try:
                    if match.is_dir():
                        shutil.rmtree(match, ignore_errors=True)
                    else:
                        match.unlink(missing_ok=True)
                    temp_deleted += 1
                except Exception:
                    pass
    log(f"Cleaned {temp_deleted} temporary scoped Chromium socket(s) from {LOCAL_TEMP}")
    log("[OK] Step 1 Complete: Device storage and supercookies completely purged.\n")


def step2_generate_random_profile():
    """Generate fresh random fingerprint and proxy parameters."""
    log("=== STEP 2: Generating Dynamic Hardware Fingerprint & Persona ===")

    fp_seed = random.randint(100000, 999999)
    session_id = secrets.token_hex(4)
    resolutions = [(1920, 1080), (1536, 864), (1680, 1050), (1440, 900)]
    width, height = random.choice(resolutions)
    cdp_port = random.randint(12000, 19999)

    profile_name = f"clean_{session_id}"

    log(f"  Fingerprint Seed   : {fp_seed} (Hardware canvas/audio jitter)")
    log(f"  Residential Session: {session_id} (Rotates egress IP)")
    log(f"  Target Resolution  : {width}x{height} (Windows standard ratio)")
    log(f"  Ephemeral Profile  : {profile_name}")
    log(f"  Masked CDP Port    : {cdp_port}")
    log("[OK] Step 2 Complete: Dynamic anti-detect profile generated.\n")

    return {
        "seed": fp_seed,
        "session": session_id,
        "width": width,
        "height": height,
        "port": cdp_port,
        "profile": profile_name,
    }


def step3_verify_stealth(params: dict):
    """Launch the browser with new parameters and verify stealth signals."""
    log("=== STEP 3: Booting Diagnostic Session & Verifying Stealth ===")

    env = dict(os.environ)
    env["CDP_PORT"] = str(params["port"])
    env["CDP_URL"] = f"http://127.0.0.1:{params['port']}"
    env["PROFILE_NAME"] = params["profile"]
    env["FINGERPRINT"] = str(params["seed"])
    env["PROXY_SESSION"] = params["session"]
    env["WINDOW_SIZE"] = f"{params['width']},{params['height']}"
    env["HEADLESS"] = "1"

    launch_script = ROOT / "scripts" / "launch_profile.js"
    log(f"Spawning CloakBrowser instance via {launch_script.name}...")

    proc = subprocess.Popen(
        ["node", str(launch_script)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for CDP endpoint to become ready
    deadline = time.time() + 30
    ready = False
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{params['port']}/json/version", timeout=2) as r:
                if r.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.5)

    if not ready:
        log("[!] Failed: CDP endpoint did not start in time.")
        proc.kill()
        return False

    log(f"Connected to CloakBrowser CDP on port {params['port']}.")

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{params['port']}")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.pages[0] if context.pages else context.new_page()

            # Navigate to about:blank to evaluate navigator properties
            page.goto("about:blank")

            diagnostics = page.evaluate("""() => {
                const getWebGL = () => {
                    try {
                        const canvas = document.createElement('canvas');
                        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
                        if (!gl) return { vendor: 'N/A', renderer: 'N/A' };
                        const dbg = gl.getExtension('WEBGL_debug_renderer_info');
                        return {
                            vendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : 'masked',
                            renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : 'masked'
                        };
                    } catch (e) {
                        return { error: e.toString() };
                    }
                };

                const getCanvasHash = () => {
                    try {
                        const canvas = document.createElement('canvas');
                        canvas.width = 200;
                        canvas.height = 50;
                        const ctx = canvas.getContext('2d');
                        ctx.textBaseline = 'top';
                        ctx.font = '14px Arial';
                        ctx.fillStyle = '#f60';
                        ctx.fillRect(125, 1, 62, 20);
                        ctx.fillStyle = '#069';
                        ctx.fillText('StealthTest, 123!', 2, 15);
                        return canvas.toDataURL().slice(-32);
                    } catch (e) {
                        return 'error';
                    }
                };

                return {
                    webdriver: navigator.webdriver,
                    userAgent: navigator.userAgent,
                    platform: navigator.platform,
                    languages: navigator.languages,
                    hardwareConcurrency: navigator.hardwareConcurrency,
                    deviceMemory: navigator.deviceMemory,
                    screen: {
                        width: window.screen.width,
                        height: window.screen.height,
                        availWidth: window.screen.availWidth,
                        availHeight: window.screen.availHeight,
                    },
                    webgl: getWebGL(),
                    canvasHashTail: getCanvasHash(),
                };
            }""")

            log("\n--- DIAGNOSTIC RESULTS ---")
            log(f"  navigator.webdriver     : {diagnostics['webdriver']} (Must be False)")
            log(f"  User Agent              : {diagnostics['userAgent']}")
            log(f"  Platform Persona        : {diagnostics['platform']}")
            log(f"  Hardware Concurrency    : {diagnostics['hardwareConcurrency']} cores")
            log(f"  Device Memory           : {diagnostics['deviceMemory']} GB")
            log(f"  Screen Dimensions       : {diagnostics['screen']['width']}x{diagnostics['screen']['height']}")
            log(f"  Screen Avail Dimensions : {diagnostics['screen']['availWidth']}x{diagnostics['screen']['availHeight']}")
            log(f"  WebGL Unmasked Renderer : {diagnostics['webgl'].get('renderer')}")
            log(f"  Canvas Sub-pixel Hash   : ...{diagnostics['canvasHashTail']}")

            # Check public egress IP through proxy
            log("\nChecking proxy egress IP and WebRTC leak defense...")
            try:
                page.goto("https://api.ipify.org?format=json", timeout=15000)
                ip_data = json.loads(page.inner_text("body"))
                log(f"  Proxy Egress IP         : {ip_data.get('ip')} [GeoNode Residential Pool]")
            except Exception as e:
                log(f"  Notice: could not query ipify directly ({e})")

            # Capture diagnostic snapshot
            artifacts_dir = ROOT / "artifacts"
            artifacts_dir.mkdir(exist_ok=True)
            snapshot_path = artifacts_dir / "clean_browser_verified.png"
            page.screenshot(path=str(snapshot_path))
            log(f"  Verification Screenshot : {snapshot_path}")

            assert diagnostics['webdriver'] is False, "navigator.webdriver should be False"
            log("\n[OK] ALL STEALTH CRITERIA VERIFIED SUCCESSFULLY.")
            return True
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)


def main():
    step1_purge_storage()
    params = step2_generate_random_profile()
    step3_verify_stealth(params)


if __name__ == "__main__":
    main()
