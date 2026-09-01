"""nlm-agent (vision-driven Gemini Notebook engine): coordinate scaling,
action execution against a fake page, the phase loop (done / step budget /
safety), response-shape tolerance, and the docker invocation. Fully offline —
the interactions API is stubbed; playwright is never imported (the module
only imports it inside run_episode)."""
from __future__ import annotations

import json

import pytest

from pipeline import nlm_agent


# --- fakes --------------------------------------------------------------------

class FakeMouse:
    def __init__(self, log):
        self.log = log

    def click(self, x, y, click_count=1, button="left"):
        self.log.append(("click", x, y, click_count, button))

    def move(self, x, y, steps=1):
        self.log.append(("move", x, y))

    def wheel(self, dx, dy):
        self.log.append(("wheel", dx, dy))

    def down(self):
        self.log.append(("down",))

    def up(self):
        self.log.append(("up",))


class FakeKeyboard:
    def __init__(self, log):
        self.log = log

    def insert_text(self, text):
        self.log.append(("insert", text))

    def press(self, key):
        self.log.append(("press", key))

    def down(self, key):
        self.log.append(("kdown", key))

    def up(self, key):
        self.log.append(("kup", key))


class FakePage:
    def __init__(self):
        self.log = []
        self.mouse = FakeMouse(self.log)
        self.keyboard = FakeKeyboard(self.log)
        self.url = "https://notebooklm.google.com/notebook/abc"

    def wait_for_timeout(self, ms):
        pass

    def goto(self, url, timeout=None):
        self.log.append(("goto", url))
        self.url = url

    def go_back(self):
        self.log.append(("back",))

    def go_forward(self):
        self.log.append(("fwd",))

    def screenshot(self, type="png"):
        return b"\x89PNGfake"


# --- units --------------------------------------------------------------------

def test_scale_normalized_coordinates():
    assert nlm_agent.scale(0, 1440) == 0
    assert nlm_agent.scale(500, 1440) == 720
    assert nlm_agent.scale(1000, 1440) == 1439      # clamped to viewport
    assert nlm_agent.scale(2000, 1440) == 1439


def test_extract_calls_tolerates_shapes():
    calls = nlm_agent.extract_calls(
        {"steps": [{"type": "function_call", "name": "click"},
                   {"type": "text", "text": "done"}]})
    assert len(calls) == 1
    assert nlm_agent.extract_calls({"output": {"type": "function_call",
                                               "name": "wait"}})
    assert nlm_agent.extract_calls({}) == []


def test_executor_click_type_and_scroll():
    page = FakePage()
    ex = nlm_agent.Executor(page)
    ex.execute("click", {"x": 500, "y": 500})
    assert ("click", 720, 450, 1, "left") in page.log
    ex.execute("type", {"x": 100, "y": 100, "text": "hello",
                        "press_enter": True})
    assert ("insert", "hello") in page.log and ("press", "Enter") in page.log
    ex.execute("scroll", {"x": 500, "y": 500, "direction": "up",
                          "magnitude_in_pixels": 300})
    assert ("wheel", 0, -300) in page.log


def test_executor_navigation_domain_lock():
    page = FakePage()
    ex = nlm_agent.Executor(page)
    note = ex.execute("navigate", {"url": "https://evil.example.com/x"})
    assert "refused" in note
    assert not any(entry[0] == "goto" for entry in page.log)
    assert ex.execute("navigate",
                      {"url": "https://notebooklm.google.com/"}) == "ok"


def test_executor_custom_functions():
    page = FakePage()
    ex = nlm_agent.Executor(page)
    ex.provided_text = "long steering prompt"
    ex.execute("insert_provided_text", {})
    assert ("insert", "long steering prompt") in page.log
    ex.execute("report_status", {"ready": True})
    assert ex.status_reported is True


def test_executor_unknown_action_reports_not_raises():
    note = nlm_agent.Executor(FakePage()).execute("teleport", {})
    assert "unsupported" in note


# --- phase loop ---------------------------------------------------------------

def _responses(monkeypatch, seq):
    it = iter(seq)
    sent = []

    def fake(payload, retries=3):
        sent.append(payload)
        return next(it)
    monkeypatch.setattr(nlm_agent, "cu_request", fake)
    monkeypatch.setattr(nlm_agent, "PACE_SEC", 0)
    return sent


def test_phase_loop_finishes_and_threads_interaction_id(monkeypatch):
    sent = _responses(monkeypatch, [
        {"id": "i1", "steps": [{"type": "function_call", "name": "click",
                                "call_id": "c1",
                                "arguments": {"x": 10, "y": 10}}]},
        {"id": "i2", "steps": []},
    ])
    steps = nlm_agent.run_phase(FakePage(), nlm_agent.Executor(FakePage()),
                                "do a thing", max_steps=5)
    assert steps == 1
    assert "previous_interaction_id" not in sent[0]
    assert sent[1]["previous_interaction_id"] == "i1"
    result = sent[1]["input"][0]
    assert result["type"] == "function_result" and result["call_id"] == "c1"
    assert result["result"][1]["mime_type"] == "image/png"


def test_phase_loop_step_budget(monkeypatch):
    _responses(monkeypatch, [
        {"id": f"i{n}", "steps": [{"type": "function_call", "name": "wait",
                                   "call_id": f"c{n}", "arguments": {}}]}
        for n in range(10)])
    with pytest.raises(nlm_agent.AgentError) as e:
        nlm_agent.run_phase(FakePage(), nlm_agent.Executor(FakePage()),
                            "never done", max_steps=3)
    assert e.value.kind == "steps"


def test_phase_loop_safety(monkeypatch):
    sent = _responses(monkeypatch, [
        {"id": "i1", "steps": [{"type": "function_call", "name": "click",
                                "call_id": "c1", "arguments":
                                {"x": 1, "y": 1, "safety_decision":
                                 {"decision": "require_confirmation",
                                  "explanation": "sure?"}}}]},
        {"id": "i2", "steps": []},
    ])
    nlm_agent.run_phase(FakePage(), nlm_agent.Executor(FakePage()), "go",
                        max_steps=3)
    assert sent[1]["input"][0]["safety_acknowledgement"] is True
    _responses(monkeypatch, [
        {"id": "i1", "steps": [{"type": "function_call", "name": "click",
                                "call_id": "c1", "arguments":
                                {"safety_decision":
                                 {"decision": "blocked",
                                  "explanation": "no"}}}]}])
    with pytest.raises(nlm_agent.AgentError) as e:
        nlm_agent.run_phase(FakePage(), nlm_agent.Executor(FakePage()), "go",
                            max_steps=3)
    assert e.value.kind == "safety"


# --- podcast-stage integration ------------------------------------------------

def test_nlm_agent_cmd_passes_key_by_name_only(test_db, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "sekret")
    monkeypatch.setenv("NLM_AGENT_IMAGE", "nlm-agent")
    from pipeline import podcast
    cmd = podcast.nlm_agent_cmd(tmp_path / "job.json", tmp_path, tmp_path)
    joined = " ".join(cmd)
    assert "sekret" not in joined          # secret travels via env, not argv
    assert "-e GEMINI_API_KEY" in joined
    assert "notebooklm-data:/data:ro" in joined
    assert cmd[-2:] == ["--job", "/out/job.json"]


def test_mux_downloaded_wav(test_db, tmp_path, monkeypatch):
    from pipeline import podcast, tts
    monkeypatch.setattr(tts.shutil, "which", lambda n: None)   # WAV path
    wav = tmp_path / "episode.wav"
    wav.write_bytes(tts._wav(b"\x00" * tts.BYTES_PER_SEC * 2))
    info = podcast._mux_downloaded(wav, "Ep", tmp_path / "out" / "x")
    assert info["mime"] == "audio/wav" and info["duration_sec"] == 2
    assert info["chapters"] == [{"start_sec": 0, "title": "Ep"}]
