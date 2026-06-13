"""
Smoke + unit tests for agy-headless-bridge.

The unit tests (clean / find_agy / arg validation) always run. The live smoke
test that actually invokes `agy` is skipped automatically when the binary is
not installed/authenticated, so CI without Antigravity still passes.
"""

import os

import pytest

from agy_headless_bridge import bridge


# --- pure-unit: output cleaning -------------------------------------------

def test_clean_strips_ansi_color():
    raw = "\x1b[32mhello\x1b[0m world"
    assert bridge.clean(raw) == "hello world"


def test_clean_collapses_spinner_repaint():
    # A spinner repaints the same line via \r; only the final paint is real.
    raw = "loading...\rloading done\n"
    assert bridge.clean(raw) == "loading done"


def test_clean_drops_tui_chrome_glyphs():
    raw = "╭─────╮\n│ answer: 42 │\n╰─────╯"
    assert bridge.clean(raw) == "answer: 42"


def test_clean_empty_returns_empty():
    assert bridge.clean("\x1b[0m\n  \n") == ""


# --- pure-unit: arg validation --------------------------------------------

def test_run_rejects_empty_prompt():
    with pytest.raises(ValueError):
        bridge.run("   ")


def test_find_agy_honors_explicit_env(tmp_path, monkeypatch):
    fake = tmp_path / ("agy.exe" if os.name == "nt" else "agy")
    fake.write_text("")
    monkeypatch.setenv("AGY_PATH", str(fake))
    assert bridge.find_agy() == str(fake)


def test_run_raises_when_agy_missing(monkeypatch):
    monkeypatch.setenv("AGY_PATH", "/nonexistent/path/to/agy")
    monkeypatch.setattr(bridge, "find_agy", lambda: None)
    with pytest.raises(bridge.AgyNotFoundError):
        bridge.run("hello")


# --- live smoke (skipped if agy not available) ----------------------------

@pytest.mark.skipif(
    bridge.find_agy() is None,
    reason="agy binary not installed/authenticated; skipping live smoke",
)
def test_live_agy_roundtrip():
    out = bridge.run("reply with exactly: SMOKE_OK", timeout=120)
    assert "SMOKE_OK" in out
