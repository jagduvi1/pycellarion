# pycellarion

[![PyPI](https://img.shields.io/pypi/v/pycellarion)](https://pypi.org/project/pycellarion/)
[![CI](https://github.com/jagduvi1/pycellarion/actions/workflows/ci.yml/badge.svg)](https://github.com/jagduvi1/pycellarion/actions/workflows/ci.yml)
[![Contract](https://github.com/jagduvi1/pycellarion/actions/workflows/contract.yml/badge.svg)](https://github.com/jagduvi1/pycellarion/actions/workflows/contract.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Async Python client for the [Cellarion](https://cellarion.app) wine-cellar
API. It is the library behind the
[Home Assistant integration](https://github.com/jagduvi1/ha-cellarion), and
usable on its own by anything that wants to read a cellar or mark a bottle
as consumed.

- **Async, typed, small.** One dependency (`aiohttp`), `py.typed`, no I/O
  outside the calls you make.
- **Two credentials.** A personal API token (`cel_…`, created in Cellarion
  under *Settings → API tokens*), or email and password used once to mint
  such a token. Passwords are never kept beyond the login they were given for.
- **Push events.** Parses the server's `text/event-stream` and yields event
  names, so callers can refresh on change instead of polling.
- **Honest errors.** Status codes map to a small exception hierarchy:
  `CellarionAuthError` (re-authenticate), `CellarionScopeError` (the token
  lacks a scope), `CellarionTokensNotSupported` and
  `CellarionPushNotSupported` (older servers), `CellarionPushForbidden`,
  and `CellarionApiError` for everything else.

## Install

```bash
pip install pycellarion
```

## Use

```python
import aiohttp
from pycellarion import CellarionClient

async with aiohttp.ClientSession() as session:
    client = CellarionClient(session, "https://cellarion.app", token="cel_…")

    stats = await client.get_stats_overview()
    print(stats["stats"]["overview"]["totalBottles"])

    async for event in client.events_stream():
        if event == "_connected":
            continue
        print("something changed:", event)
```

Minting a token from email and password:

```python
client = CellarionClient(session, "https://cellarion.app", "me@example.com", "secret")
await client.authenticate()
token = await client.async_create_api_token("My script", ["read", "consume"])
# keep `token`; the password is not needed again
```

## API

| Method | Purpose |
|---|---|
| `authenticate()` | Log in with email and password (session JWT); raises `CellarionAuthError` on bad credentials |
| `async_create_api_token(name, scopes)` | Mint a personal API token (password login required) |
| `get_stats_overview()` / `get_cellars()` / `get_notifications()` / `get_peak_bottles(limit)` / `get_health()` | Reads |
| `get_account_id()` | Stable account id from `/api/auth/whoami`, or `None` on servers without it |
| `consume_bottle(bottle_id, reason, rating, note)` | Mark a bottle as consumed |
| `events_stream()` | Async iterator of push event names; yields `"_connected"` first |
| `revoke_own_token()` | Ask the server to revoke the client's own API token (Cellarion 1.220+) |

Responses are returned as plain `dict`s (`JsonDict`); bodies over
`MAX_BODY_BYTES` (4 MiB) are refused.

## API contract

The integration depends on a handful of endpoints and response shapes.
`tests/contract/` pins them down and runs nightly against a real Cellarion
server (see the Contract badge above), so a change on the server side is
caught before it reaches users. Run them yourself against any server with a
read-scoped token:

```bash
CELLARION_CONTRACT_URL=https://cellarion.app CELLARION_CONTRACT_TOKEN=cel_… pytest tests/contract
```

They never write: no bottle is consumed and no token is revoked.

## Development

```bash
pip install -e ".[test]"
ruff check . && ruff format --check . && mypy src
pytest --cov
```

Releases are published to PyPI from GitHub releases through
[trusted publishing](https://docs.pypi.org/trusted-publishers/).

## License

MIT
