#!/usr/bin/env python3
"""
agy_headless_bridge.bridge — Make the Google Antigravity CLI (`agy`) callable
headlessly (from any non-TTY context: a subprocess, a pipe, an MCP server,
Claude Code's Bash tool, CI).

WHY THIS EXISTS
---------------
`agy -p "<prompt>"` gates its stdout on `isatty()` (upstream bug #76). When
stdout is NOT attached to a real terminal it emits nothing and exits 0. So a
plain `subprocess.run(["agy", "-p", prompt])` returns an empty string — which
makes `agy` unusable as a delegate from any automated context.

The known community workaround, `winpty agy -p "..."`, requires a *pre-existing*
terminal, so it still fails from a subprocess.

THE FIX
-------
Allocate a *fresh* pseudo-terminal and spawn `agy` attached to it. `agy` then
sees a real tty on stdout and emits normally. We read the pty master, strip the
ANSI / TUI control noise, and return the clean model response.

  * Windows : ConPTY via the `pywinpty` library (`PtyProcess`). ConPTY creates a
              brand-new pty and does NOT require the parent process to already
              own a tty — so this works from any subprocess.
  * POSIX   : the stdlib `pty` module (`os.openpty` + `subprocess.Popen`).

LARGE PROMPTS (cmdline cap)
---------------------------
Passing the prompt as a command-line argument (`agy -p <prompt>`) caps the
prompt at the OS command-line limit — on Windows, CreateProcess rejects a
command line over ~32 767 chars with WinptyError 206 ("filename too long").
Automated callers (e.g. an agent host injecting a full transcript) routinely
exceed that. The fix feeds the prompt to `agy -p -` through STDIN instead:
stdin is an unbounded stream, while stdout still lives in the pty so the
`isatty()` gate is satisfied. `run()` uses this path by default; the legacy
argv path remains available via `run(..., via="argv")` and `_pty_run`.

Public API
----------
    from agy_headless_bridge.bridge import run
    text = run("reply with exactly: OK")
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time

DEFAULT_TIMEOUT = float(os.environ.get("AGY_BRIDGE_TIMEOUT", "180"))

# --- ANSI / TUI noise stripping -------------------------------------------

# CSI sequences (colors, cursor moves), OSC sequences (window titles), lone esc.
_ANSI_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_ANSI_OTHER = re.compile(r"\x1b[@-Z\\-_]")
# Box-drawing / spinner glyphs agy uses for its TUI chrome.
_SPINNER = set(
    "⠁⠂⠄⡀⢀⠠⠐⠈⣾⣽⣻⢿⡿⣟⣯⣷⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    "│─┌┐└┘├┤┬┴┼╭╮╰╯═║╔╗╚╝▌▐█▏▕"
)


def _strip_ansi(text: str) -> str:
    text = _ANSI_OSC.sub("", text)
    text = _ANSI_CSI.sub("", text)
    text = _ANSI_OTHER.sub("", text)
    return text


def _collapse_carriage_returns(text: str) -> str:
    """A spinner repaints one line via \\r. Keep only the final paint per line."""
    text = text.replace("\r\n", "\n")  # normalize CRLF first
    out_lines = []
    for line in text.split("\n"):
        # Each remaining \r overwrites from column 0; the last segment was visible.
        out_lines.append(line.split("\r")[-1])
    return "\n".join(out_lines)


def clean(raw: str) -> str:
    """Strip ANSI escapes, spinner repaints, and TUI chrome from agy output."""
    text = _strip_ansi(raw)
    text = _collapse_carriage_returns(text)
    # Drop remaining control chars except tab/newline.
    text = "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 0x20)
    cleaned = []
    for line in text.split("\n"):
        stripped = "".join(c for c in line if c not in _SPINNER).strip()
        if stripped:
            cleaned.append(stripped)
    return "\n".join(cleaned).strip()


# --- agy discovery ---------------------------------------------------------


def find_agy() -> str | None:
    """Locate the `agy` binary. Honors $AGY_PATH, then PATH, then OS defaults."""
    explicit = os.environ.get("AGY_PATH")
    if explicit and os.path.exists(explicit):
        return explicit

    found = shutil.which("agy") or shutil.which("agy.exe")
    if found:
        return found

    home = os.path.expanduser("~")
    if sys.platform == "win32":
        candidates = [
            os.path.join(home, "AppData", "Local", "agy", "bin", "agy.exe"),
            os.path.join(home, "AppData", "Roaming", "agy", "bin", "agy.exe"),
        ]
    else:
        candidates = [
            os.path.join(home, ".local", "bin", "agy"),
            "/opt/antigravity/bin/agy",
            "/usr/local/bin/agy",
        ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


class AgyNotFoundError(RuntimeError):
    pass


# --- platform pty runners --------------------------------------------------


def _import_winpty():  # pragma: no cover - env-specific
    try:
        from winpty import PtyProcess  # type: ignore

        return PtyProcess
    except ImportError as exc:
        raise RuntimeError(
            "pywinpty is required on Windows. Install: pip install pywinpty"
        ) from exc


def _drain_winpty(proc, timeout: float) -> str:
    """Pump a spawned pywinpty PtyProcess to EOF (or timeout) and clean it.

    Shared by the legacy argv runner (`_run_windows`) and the stdin file-pipe
    runner (`_run_windows_stdin`): both end up with a `PtyProcess` whose master
    must be drained on a watchdog thread so a hung child cannot block forever.
    """
    chunks: list[str] = []

    def _reader() -> None:
        try:
            while True:
                data = proc.read(4096)
                if data:
                    chunks.append(data)
                elif not proc.isalive():
                    break
        except EOFError:
            pass

    t = threading.Thread(target=_reader, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        try:
            proc.terminate(force=True)
        except Exception:
            pass
        t.join(5)
        raise TimeoutError(f"process timed out after {timeout}s")

    return clean("".join(chunks))


def _run_windows(argv: list[str], timeout: float) -> str:
    PtyProcess = _import_winpty()
    # Wide cols so agy does not hard-wrap; tall rows to avoid paging.
    proc = PtyProcess.spawn(argv, dimensions=(50, 200))
    return _drain_winpty(proc, timeout)


def _run_posix(argv: list[str], timeout: float) -> str:
    import pty
    import subprocess

    master_fd, slave_fd = pty.openpty()
    # Hint a wide terminal so agy doesn't hard-wrap its answer.
    env = {**os.environ, "COLUMNS": "200", "LINES": "50", "TERM": "xterm-256color"}
    try:
        proc = subprocess.Popen(
            argv,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env=env,
        )
    finally:
        os.close(slave_fd)  # parent keeps only the master end

    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    try:
        while True:
            if time.monotonic() > deadline:
                proc.kill()
                raise TimeoutError(f"process timed out after {timeout}s")
            try:
                data = os.read(master_fd, 4096)
            except OSError:
                break  # master closed: child exited
            if not data:
                break
            chunks.append(data)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    raw = b"".join(chunks).decode("utf-8", errors="replace")
    return clean(raw)


# --- stdin (file-pipe) pty runners -----------------------------------------
#
# The argv runners above cap the prompt at the OS command-line limit. These
# runners instead deliver the prompt to `agy -p -` through STDIN (an unbounded
# stream) while keeping stdout in the pty so the isatty() gate still fires.


def _run_posix_stdin(agy: str, prompt: str, timeout: float) -> str:
    import pty
    import subprocess

    # Prompt goes to agy via a plain pipe (no length cap); stdout/stderr live
    # in the pty so agy's isatty() check passes and it emits its answer.
    stdin_r, stdin_w = os.pipe()
    master_fd, slave_fd = pty.openpty()
    env = {**os.environ, "COLUMNS": "200", "LINES": "50", "TERM": "xterm-256color"}
    try:
        proc = subprocess.Popen(
            [agy, "-p", "-"],
            stdin=stdin_r,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env=env,
        )
    finally:
        os.close(slave_fd)
        os.close(stdin_r)

    # Feed the prompt on a thread so a large prompt can't deadlock against a
    # pty whose read buffer we are not yet draining.
    def _feed() -> None:
        try:
            os.write(stdin_w, prompt.encode("utf-8"))
        except OSError:
            pass
        finally:
            try:
                os.close(stdin_w)
            except OSError:
                pass

    feeder = threading.Thread(target=_feed, daemon=True)
    feeder.start()

    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    try:
        while True:
            if time.monotonic() > deadline:
                proc.kill()
                raise TimeoutError(f"process timed out after {timeout}s")
            try:
                data = os.read(master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    raw = b"".join(chunks).decode("utf-8", errors="replace")
    return clean(raw)


def _run_windows_stdin(agy: str, prompt: str, timeout: float) -> str:
    # pywinpty puts stdin AND stdout on the pty, so we cannot hand agy a
    # separate stdin pipe directly. Instead drive it through a throwaway cmd
    # batch that pipes a temp file into `agy -p -`: `type` supplies stdin from
    # the file (no cmdline cap), the pipe's right side inherits the pty for
    # stdout (isatty() passes). This is the proven Windows path.
    import tempfile

    PtyProcess = _import_winpty()
    tmpdir = tempfile.mkdtemp(prefix="agy-bridge-")
    prompt_file = os.path.join(tmpdir, "prompt.txt")
    bat_file = os.path.join(tmpdir, "run.bat")
    try:
        with open(prompt_file, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        # %~1 = prompt file. agy path is baked in (quoted) to dodge nested cmd
        # quoting around the pipe.
        with open(bat_file, "w", encoding="utf-8") as fh:
            fh.write("@echo off\r\n")
            fh.write('chcp 65001 >nul\r\n')  # UTF-8 so a non-ASCII prompt survives
            fh.write(f'type "%~1" | "{agy}" -p -\r\n')

        proc = PtyProcess.spawn([bat_file, prompt_file], dimensions=(50, 200))
        return _drain_winpty(proc, timeout)
    finally:
        for p in (prompt_file, bat_file):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


def _pty_run_stdin(agy: str, prompt: str, timeout: float) -> str:
    """Run `agy -p -` in a fresh pty, feeding the prompt via stdin."""
    if sys.platform == "win32":
        return _run_windows_stdin(agy, prompt, timeout)
    return _run_posix_stdin(agy, prompt, timeout)


# --- public API ------------------------------------------------------------


def _pty_run(argv: list[str], timeout: float) -> str:
    """Spawn argv attached to a fresh pty; return its cleaned stdout.

    Platform-agnostic seam: the legacy argv path and the test suite call this
    with an explicit command to exercise the real pty machinery without needing
    `agy` installed.
    """
    if sys.platform == "win32":
        return _run_windows(argv, timeout)
    return _run_posix(argv, timeout)


def run(
    prompt: str,
    timeout: float = DEFAULT_TIMEOUT,
    agy_path: str | None = None,
    via: str = "stdin",
) -> str:
    """
    Run `agy` through a fresh pty and return its cleaned stdout.

    The prompt is delivered to `agy -p -` via STDIN by default (`via="stdin"`),
    which has no length limit — required for large prompts (e.g. an automated
    host injecting a full transcript) that would otherwise blow the OS
    command-line cap. Pass `via="argv"` for the legacy `agy -p <prompt>` path.

    Raises AgyNotFoundError if `agy` can't be located, TimeoutError on timeout.
    Returns "" if agy genuinely emitted nothing.
    """
    if not prompt or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    if via not in ("stdin", "argv"):
        raise ValueError("via must be 'stdin' or 'argv'")

    path = agy_path or find_agy()
    if not path:
        raise AgyNotFoundError(
            "agy binary not found. Set $AGY_PATH or install the Antigravity CLI: "
            "https://antigravity.google/cli"
        )

    if via == "argv":
        return _pty_run([path, "-p", prompt], timeout)
    return _pty_run_stdin(path, prompt, timeout)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        sys.stderr.write('Usage: python -m agy_headless_bridge "your prompt"\n')
        return 64
    prompt = " ".join(argv)
    try:
        output = run(prompt)
    except AgyNotFoundError as exc:
        sys.stderr.write(f"[agy-bridge] {exc}\n")
        return 127
    except TimeoutError as exc:
        sys.stderr.write(f"[agy-bridge] {exc}\n")
        return 1
    if not output:
        sys.stderr.write("[agy-bridge] no output captured from agy\n")
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
