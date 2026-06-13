# Contributing to agy-headless-bridge

Thanks for helping. This is a small, focused package — its job is to make the
Google Antigravity CLI (`agy`) callable from non-TTY contexts. Contributions
that keep it small and dependency-light are very welcome.

## Most-wanted contribution: POSIX verification

The Windows path (ConPTY via `pywinpty`) is verified. The **Linux / macOS path**
(stdlib `pty`) is implemented but **not yet tested on real hardware**. If you run
it on POSIX, please report results — pass *or* fail — via the
[**POSIX result / bug report** issue template](https://github.com/rhishi99/agy-headless-bridge/issues/new/choose).

Include:

- OS + version (`uname -a` on Linux/macOS)
- Python version (`python --version`)
- `agy --version`
- Whether `agy -p "say hi"` works for you **in a real terminal**
- The exact command you ran and the **full stderr/stdout**

## Dev setup

```bash
git clone https://github.com/rhishi99/agy-headless-bridge
cd agy-headless-bridge
python -m pip install -e ".[dev]"
pytest
```

- Unit tests (`clean()`, `find_agy()`, arg validation) run everywhere.
- The live `agy` round-trip test auto-skips when `agy` isn't installed, so you
  don't need Antigravity to develop or to pass CI.

## Guidelines

- **Keep it dependency-light.** The only runtime dependency is `pywinpty`, and
  only on Windows. Don't add an MCP SDK or other heavy deps.
- **TDD.** New behavior gets a test first. Put unit tests in `tests/`.
- **Don't touch auth or credentials.** This package only spawns the `agy`
  already on the user's machine. It must never read, store, or transmit
  credentials, and must not bypass any access control.
- **`clean()` changes need a test** with a sample raw string showing the new
  rule (see `tests/test_smoke.py` for the pattern).
- Match the existing style; run `pytest` before opening a PR.

## Pull requests

1. Fork, branch from `main`.
2. Make the change + tests.
3. `pytest` green locally.
4. Open the PR — CI runs on Windows + Linux across Python 3.9 and 3.12.

## Reporting security issues

Don't open a public issue for anything sensitive. Note that this package handles
no secrets by design; if you find a way it could leak or execute something
unexpected, please report privately to the maintainer.

## License

By contributing you agree your contributions are licensed under the project's
[MIT License](LICENSE).
