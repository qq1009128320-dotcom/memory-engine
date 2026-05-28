# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 2.1.x   | :white_check_mark: |
| 2.0.x   | :warning: Critical fixes only |
| < 2.0   | :x:                |

## Reporting a Vulnerability

**Do not open a public issue.** Instead, please:

1. Email the maintainers privately
2. Include: affected version, steps to reproduce, potential impact
3. We will respond within 48 hours and work with you on a fix
4. We practice coordinated disclosure — you'll be credited after the fix is released

## Security Design

- **No network exposure by default**: MCP server binds to `127.0.0.1`
- **Input validation**: All MCP tool parameters validated via `validators.py`
- **SQL injection protection**: All queries use parameterized statements
- **Log sanitization**: API keys and secrets automatically redacted via `log_utils.py`
- **Single instance lock**: PID file prevents concurrent server access
- **Rate limiting**: `BoundedSemaphore(50)` for request concurrency control

## Dependency Security

We pin version ranges in `requirements.txt` and `pyproject.toml`:
- `faiss-cpu>=1.7,<2.0`
- `sentence-transformers>=3.0,<4.0`
- `httpx>=0.27,<1.0`

CI runs weekly dependency audits via `pip-audit`.
