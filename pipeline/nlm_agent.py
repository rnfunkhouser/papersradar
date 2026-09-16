#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vision-driven Gemini Notebook agent: drives the (rebranded) NotebookLM web
UI with the Gemini computer-use model instead of brittle CSS selectors — the
model looks at screenshots and picks actions, so Google UI redesigns don't
strand it. Replaces notebooklm-mcp's high-level flow after the 2026-07
"Gemini Notebook" redesign broke its selectors (docs/PODCAST_DESIGN.md).

Runs INSIDE the nlm-agent container (deploy/nlm-agent/Dockerfile: Playwright
Python base image), one-shot per episode, invoked by pipeline/podcast.py:

    python3 nlm_agent.py --job /out/job.json

job.json: {"date", "steering_prompt", "pdfs": [container paths],
           "notes_title", "notes_text", "out_dir"}
Auth: Playwright storageState JSON maintained by the notebooklm-mcp worker
(mounted read-only at STATE_JSON; the worker stays running as auth keeper).
Output: <out_dir>/episode.<ext> + <out_dir>/result.json
    {"ok", "error", "error_kind": auth|steps|timeout|safety|api|download,
     "audio_path", "steps_used"}

Deliberately standalone: stdlib + playwright only, config via env
(GEMINI_API_KEY, NLM_CU_MODEL, STATE_JSON, NLM_GENERATE_TIMEOUT_SEC).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = os.environ.get("GEMINI_API_BASE",
                          "https://generativelanguage.googleapis.com")
MODEL = os.environ.get("NLM_CU_MODEL", "gemini-3.7-flash")
# The LIVE Google session is the persistent Chrome profile the notebooklm-mcp
# worker created at login (Google rotates cookies, so the state.json snapshot
# goes stale within hours — measured 2026-09-02). The agent launches from the
# profile directly (volume mounted rw) and is its primary user; the worker
# stays only as the noVNC re-auth tool.
PROFILE_DIR = os.environ.get("PROFILE_DIR", "/data/chrome_profile")
STATE_JSON = os.environ.get("STATE_JSON", "/data/browser_state/state.json")
VIEWPORT = {"width": 1440, "height": 900}
PACE_SEC = float(os.environ.get("NLM_CU_PACE_SEC", "6"))
SETTLE_MS = 900                 # let the UI settle after each action
NAV_HOSTS = ("notebooklm.google.com", "notebook.google.com",
             "gemini.google.com", "accounts.google.com")

TOOLS = [
    {"type": "computer_use", "environment": "browser",
     "enable_prompt_injection_detection": True},
    {"type": "function", "name": "insert_provided_text",
     "description": "Insert the pre-supplied text for the CURRENT task into "
                    "the currently focused text field (use instead of typing "
                    "long provided content verbatim).",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"type": "function", "name": "report_status",
     "description": "Report the yes/no status the current task asks about.",
     "parameters": {"type": "object", "properties":
                    {"ready": {"type": "boolean"}}, "required": ["ready"]}},
]


class AgentError(Exception):
    def __init__(self, msg: str, kind: str = "api"):
        super().__init__(msg)
        self.kind = kind


# --- computer-use API client --------------------------------------------------

_last_call = 0.0


def _pace():
    global _last_call
    wait = PACE_SEC - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def cu_request(payload: dict, retries: int = 3) -> dict:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise AgentError("GEMINI_API_KEY not set", kind="api")
    req = urllib.request.Request(
        f"{API_BASE}/v1beta/interactions", method="POST",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    for attempt in range(retries + 1):
        _pace()
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:400]
            except Exception:
                pass
            if e.code in (429, 500, 502, 503) and attempt < retries:
                time.sleep(30.0 if e.code == 429 else 8.0)
                continue
            raise AgentError(f"interactions HTTP {e.code}: {detail}",
                             kind="api")
        except Exception as e:
            if attempt < retries:
                time.sleep(8.0)
                continue
            raise AgentError(f"interactions {type(e).__name__}: {e}",
                             kind="api")


def extract_calls(resp: dict) -> list[dict]:
    """Function-call steps from an interactions response, shape-tolerantly."""
    steps = resp.get("steps") or resp.get("output") or []
    if isinstance(steps, dict):
        steps = [steps]
    return [s for s in steps
            if isinstance(s, dict) and s.get("type") == "function_call"]


def scale(v, extent: int) -> int:
    """Model coordinates are normalized 0-1000."""
    return max(0, min(extent - 1, round(float(v) / 1000 * extent)))


# --- action executor ----------------------------------------------------------

class Executor:
    """Executes model actions against a Playwright page. Long provided text
    (steering prompt, notes) is injected via the insert_provided_text custom
    function rather than model typing."""

    KEYMAP = {"enter": "Enter", "return": "Enter", "tab": "Tab", "esc":
              "Escape", "escape": "Escape", "backspace": "Backspace",
              "delete": "Delete", "space": " ", "up": "ArrowUp",
              "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight",
              "pageup": "PageUp", "pagedown": "PageDown", "home": "Home",
              "end": "End", "ctrl": "Control", "cmd": "Meta", "alt": "Alt",
              "shift": "Shift"}

    def __init__(self, page):
        self.page = page
        self.provided_text = ""
        self.status_reported: bool | None = None

    def _xy(self, args) -> tuple[int, int]:
        return (scale(args.get("x", 500), VIEWPORT["width"]),
                scale(args.get("y", 500), VIEWPORT["height"]))

    def _key(self, k: str) -> str:
        return self.KEYMAP.get(k.strip().lower(), k.strip())

    def execute(self, name: str, args: dict) -> str:
        page = self.page
        if name in ("click", "double_click", "triple_click", "right_click",
                    "middle_click"):
            x, y = self._xy(args)
            clicks = {"double_click": 2, "triple_click": 3}.get(name, 1)
            button = {"right_click": "right",
                      "middle_click": "middle"}.get(name, "left")
            page.mouse.click(x, y, click_count=clicks, button=button)
        elif name in ("move", "hover"):
            x, y = self._xy(args)
            page.mouse.move(x, y)
        elif name == "type":
            if "x" in args and "y" in args:
                x, y = self._xy(args)
                page.mouse.click(x, y)
            if args.get("clear_before_typing"):
                page.keyboard.press("Control+a")
                page.keyboard.press("Backspace")
            page.keyboard.insert_text(str(args.get("text", "")))
            if args.get("press_enter"):
                page.keyboard.press("Enter")
        elif name == "scroll":
            x, y = self._xy(args)
            page.mouse.move(x, y)
            mag = int(args.get("magnitude_in_pixels", 400))
            d = str(args.get("direction", "down")).lower()
            dx, dy = {"down": (0, mag), "up": (0, -mag), "left": (-mag, 0),
                      "right": (mag, 0)}.get(d, (0, mag))
            page.mouse.wheel(dx, dy)
        elif name == "drag_and_drop":
            sx = scale(args.get("start_x", 0), VIEWPORT["width"])
            sy = scale(args.get("start_y", 0), VIEWPORT["height"])
            ex = scale(args.get("end_x", 0), VIEWPORT["width"])
            ey = scale(args.get("end_y", 0), VIEWPORT["height"])
            page.mouse.move(sx, sy)
            page.mouse.down()
            page.mouse.move(ex, ey, steps=12)
            page.mouse.up()
        elif name == "navigate":
            url = str(args.get("url", ""))
            host = url.split("://")[-1].split("/")[0]
            if not any(host.endswith(h) for h in NAV_HOSTS):
                return f"navigation to {host} refused (outside Gemini Notebook)"
            page.goto(url, timeout=45_000)
        elif name == "go_back":
            page.go_back()
        elif name == "go_forward":
            page.go_forward()
        elif name in ("press_key", "key_down", "key_up"):
            key = self._key(str(args.get("key", args.get("text", "Enter"))))
            if name == "key_down":
                page.keyboard.down(key)
            elif name == "key_up":
                page.keyboard.up(key)
            else:
                page.keyboard.press(key)
        elif name == "hotkey":
            keys = args.get("keys") or [args.get("key", "")]
            combo = "+".join(self._key(str(k)) for k in keys if k)
            page.keyboard.press(combo)
        elif name == "wait":
            time.sleep(min(float(args.get("seconds", 3) or 3), 10))
        elif name == "take_screenshot":
            pass                        # every result carries one anyway
        elif name == "insert_provided_text":
            page.keyboard.insert_text(self.provided_text)
        elif name == "report_status":
            self.status_reported = bool(args.get("ready"))
        else:
            return f"unsupported action {name!r} — try another approach"
        page.wait_for_timeout(SETTLE_MS)
        return "ok"


# --- phase loop ---------------------------------------------------------------

def screenshot_b64(page) -> str:
    return base64.b64encode(page.screenshot(type="png")).decode()


def run_phase(page, ex: Executor, goal: str, max_steps: int = 25,
              provided_text: str = "") -> int:
    """One bounded agent conversation pursuing `goal`. Returns steps used."""
    print(f"[agent] phase: {goal[:70]}...", file=sys.stderr, flush=True)
    ex.provided_text = provided_text
    prev_id = None
    payload_input = goal
    for step in range(max_steps):
        payload = {"model": MODEL, "input": payload_input, "tools": TOOLS}
        if prev_id:
            payload["previous_interaction_id"] = prev_id
        resp = cu_request(payload)
        prev_id = resp.get("id") or prev_id
        calls = extract_calls(resp)
        if not calls:
            print(f"[agent] phase done in {step} steps", file=sys.stderr,
                  flush=True)
            return step                 # model finished the goal
        print(f"[agent] step {step + 1}: "
              + ", ".join(c.get("name", "?") for c in calls),
              file=sys.stderr, flush=True)
        results = []
        for call in calls:
            args = call.get("arguments") or {}
            sd = args.get("safety_decision") or {}
            if sd.get("decision") == "blocked":
                raise AgentError(f"model blocked action: "
                                 f"{sd.get('explanation', '')[:150]}",
                                 kind="safety")
            acknowledged = sd.get("decision") == "require_confirmation"
            if acknowledged:
                print(f"[agent] acknowledging safety confirmation: "
                      f"{sd.get('explanation', '')[:120]}", file=sys.stderr)
            try:
                note = ex.execute(call.get("name", ""), args)
            except Exception as e:
                note = f"action failed: {type(e).__name__}: {e}"[:200]
            result = {
                "type": "function_result", "name": call.get("name"),
                "call_id": call.get("call_id") or call.get("id"),
                "result": [
                    {"type": "text",
                     "text": json.dumps({"url": page.url, "note": note})},
                    {"type": "image", "data": screenshot_b64(page),
                     "mime_type": "image/png"},
                ],
            }
            if acknowledged:
                result["safety_acknowledgement"] = True
            results.append(result)
        payload_input = results
    raise AgentError(f"step budget ({max_steps}) exhausted on: {goal[:100]}",
                     kind="steps")


# --- the episode flow ---------------------------------------------------------

def _cookie_db() -> Path:
    """The worker profile's cookie database (location moved across Chrome
    versions)."""
    for rel in ("Default/Network/Cookies", "Default/Cookies"):
        p = Path(PROFILE_DIR) / rel
        if p.exists():
            return p
    raise AgentError(f"no cookie DB under {PROFILE_DIR} — run the worker's "
                     "setup-auth first (runbook §NLM)", kind="auth")


def _sync_cookies_back(mini: Path) -> None:
    """Copy the transplant profile's (possibly rotated) cookie DB back over
    the canonical one, best-effort."""
    import shutil
    for rel in ("Default/Network/Cookies", "Default/Cookies"):
        src = mini / rel
        if src.exists():
            try:
                shutil.copy2(src, _cookie_db())
            except Exception as e:
                print(f"[agent] cookie sync-back skipped: {e}",
                      file=sys.stderr)
            return


def run_episode(job: dict) -> dict:
    from playwright.sync_api import sync_playwright
    out_dir = Path(job["out_dir"])
    steps_total = 0
    downloads: list = []
    upload_queue = list(job.get("pdfs", []))
    with sync_playwright() as pw:
        # Headful on Xvfb (Google bounces headless fingerprints to the login
        # wall even with a valid session — measured 2026-09-01), launched
        # from the persistent profile with the same flags the worker uses,
        # so we present as the same browser Google already trusts.
        # Minimal transplant profile: a fresh dir seeded with ONLY the
        # worker profile's cookie DB. Playwright's persistent attach crashes
        # on the worker's full patchright profile (measured 2026-09-02),
        # while fresh+Cookies launches clean AND carries the login. On
        # success the (possibly rotated) cookie DB is copied back so the
        # canonical jar stays fresh.
        import shutil
        mini = Path("/tmp/mini-profile")
        shutil.rmtree(mini, ignore_errors=True)
        canonical = _cookie_db()
        (mini / "Default").mkdir(parents=True)
        shutil.copy2(canonical, mini / "Default" / "Cookies")
        context = pw.chromium.launch_persistent_context(
            str(mini), headless=False, viewport=VIEWPORT, locale="en-US",
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        page = context.pages[0] if context.pages else context.new_page()
        page.on("filechooser",
                lambda fc: fc.set_files(upload_queue.pop(0))
                if upload_queue else None)
        page.on("download", lambda d: downloads.append(d))

        # From here on, Google may ROTATE session cookies at any point; the
        # rotated jar in the transplant profile is then the only valid one.
        # The finally block syncs it back no matter how this run ends —
        # only syncing on success is how the session got burned on
        # 2026-09-02 (a failed run discarded the rotated cookies).
        try:
            audio_path = _drive_episode(page, job, out_dir, upload_queue,
                                        downloads)
        finally:
            try:
                context.close()      # flush the cookie DB, then copy back
            except Exception:
                pass
            _sync_cookies_back(mini)
    if not audio_path.exists() or audio_path.stat().st_size < 50_000:
        raise AgentError("downloaded audio missing or implausibly small",
                         kind="download")
    return {"ok": True, "audio_path": str(audio_path),
            "steps_used": _drive_episode.steps_used}


def _drive_episode(page, job, out_dir: Path, upload_queue, downloads) -> Path:
    """The phased UI flow; returns the downloaded audio path."""
    steps_total = 0
    page.goto("https://notebooklm.google.com/", timeout=60_000)
    # Google may bounce THROUGH accounts.google.com and land back when
    # cookies are good — judge auth only after the redirects settle.
    for _ in range(10):
        page.wait_for_timeout(3000)
        if "accounts.google.com" not in page.url:
            break
    if "accounts.google.com" in page.url:
        try:                                    # leave evidence behind
            (out_dir / "auth_fail_url.txt").write_text(page.url)
            page.screenshot(path=str(out_dir / "auth_fail.png"))
        except Exception:
            pass
        raise AgentError("Google session expired — re-login via noVNC "
                         "(runbook §NLM)", kind="auth")
    ex = Executor(page)

    steps_total += run_phase(page, ex, (
        "You are on Gemini Notebook (formerly NotebookLM). Create a "
        "brand-new empty notebook (look for a 'Create notebook' or "
        "'New notebook' or '+' button; dismiss any welcome or "
        "informational dialogs that block it). You are done when a new "
        "notebook is open showing its add-sources view."))

    n = len(job.get("pdfs", []))
    if n:
        steps_total += run_phase(page, ex, (
            f"This notebook needs {n} PDF file(s) added as sources, one "
            "at a time. For each: open the add-source dialog if not "
            "already open, choose the 'Upload files' option and click "
            "it — a file is provided automatically by the environment "
            "when the file picker opens (you will not see an OS dialog). "
            "Wait until the source appears in the sources list before "
            "adding the next. You are done when the sources list shows "
            f"{n} file source(s)."), max_steps=15 + 12 * n)

    if job.get("notes_text"):
        steps_total += run_phase(page, ex, (
            "Add one more source using the 'Copied text' (paste text) "
            "option: open the add-source dialog, choose copied text, "
            "click into the text field, then call insert_provided_text "
            "to insert the prepared content (do NOT type it yourself), "
            f"set the title to {job.get('notes_title', 'Briefing notes')!r} "
            "if a title field exists, and confirm/insert. Done when the "
            "source appears in the sources list."),
            provided_text=job["notes_text"])

    steps_total += run_phase(page, ex, (
        "Now set up the Audio Overview: open the Studio (or Audio "
        "Overview) area, find the option to customize the Audio "
        "Overview before generating (often an edit/customize control), "
        "click into the customization instructions text field, call "
        "insert_provided_text to insert the prepared instructions (do "
        "NOT type them yourself), then start generation (Generate "
        "button). Done once generation has visibly started."),
        provided_text=job["steering_prompt"], max_steps=30)

    deadline = time.monotonic() + int(
        os.environ.get("NLM_GENERATE_TIMEOUT_SEC", "1800"))
    while True:
        ex.status_reported = None
        steps_total += run_phase(page, ex, (
            "Look at the current notebook. Is the generated Audio "
            "Overview finished and ready (a play button and/or download "
            "option for it is available, no progress indicator)? Call "
            "report_status with ready=true or ready=false. Do not click "
            "anything else."), max_steps=4)
        if ex.status_reported:
            break
        if time.monotonic() > deadline:
            raise AgentError("audio generation timed out", kind="timeout")
        time.sleep(45)

    steps_total += run_phase(page, ex, (
        "Download the generated Audio Overview. It appears in the "
        "Studio panel as a card or audio player. Actively work the UI — "
        "do NOT use the wait action in this phase: click the Audio "
        "Overview card/player to reveal its controls; open its "
        "three-dot 'More' options menu and choose Download; or click a "
        "download (down-arrow) icon near the player if one is visible. "
        "Scroll the Studio panel if the card is out of view. Done once "
        "a download has started."), max_steps=25)
    for _ in range(60):
        if downloads:
            break
        page.wait_for_timeout(1000)
    if not downloads:
        raise AgentError("no download captured", kind="download")
    d = downloads[0]
    suffix = Path(d.suggested_filename or "episode.wav").suffix or ".wav"
    audio_path = out_dir / f"episode{suffix}"
    d.save_as(str(audio_path))
    _drive_episode.steps_used = steps_total
    return audio_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True)
    a = ap.parse_args()
    job = json.loads(Path(a.job).read_text())
    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = run_episode(job)
    except AgentError as e:
        result = {"ok": False, "error": str(e)[:400], "error_kind": e.kind}
    except Exception as e:
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"[:400],
                  "error_kind": "api"}
    (out_dir / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result), file=sys.stderr)
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
