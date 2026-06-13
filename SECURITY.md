# Security Policy

## Design stance

`agy-headless-bridge` handles **no credentials** by design. It does not read,
store, or transmit any auth token, and it does not bypass any access control. It
only spawns the `agy` binary already installed and authenticated on your machine,
inside a pseudo-terminal, and returns the cleaned stdout. Authentication and
quotas are entirely `agy`'s concern.

It does execute a subprocess (`agy`, or — in tests — a stub you provide). Treat
the `prompt` you pass like any other input you'd hand to a CLI.

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅ |
| < 1.0   | ❌ |

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Use GitHub's **[private vulnerability reporting](https://github.com/rhishi99/agy-headless-bridge/security/advisories/new)**
(Security tab → "Report a vulnerability"). Include reproduction steps, affected
version, and platform.

Examples worth reporting privately: a way to make the bridge leak environment
data, execute something other than the requested command, or write outside its
intended scope.

You can expect an initial response within a few days. Thanks for helping keep it
safe.
