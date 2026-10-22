"""Tests for the inventory read and the label-thumbnail fetch."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
import pytest

from pycellarion import (
    IMAGE_PATH_RE,
    MAX_IMAGE_BYTES,
    MAX_INVENTORY_BYTES,
    CellarionApiError,
    CellarionAuthError,
    CellarionInventoryNotSupported,
    CellarionScopeError,
    InventoryResult,
)

from .test_client import BASE_URL, TEST_TOKEN, FakeResponse, password_client, token_client

THUMB = "/api/uploads/thumbs/processed/1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed.webp.webp"
INVENTORY = b'{"schema": 1, "cellars": [], "racks": [], "wines": {}, "bottles": []}'


class BodyResponse(FakeResponse):
    """A FakeResponse with headers and a raw body handed out in chunks.

    ``filler`` appends that many bytes generated lazily, so a test can send
    "more than the cap" without building it, and ``bytes_read`` shows how
    far the client got before it stopped.
    """

    def __init__(
        self,
        status: int = 200,
        body: bytes = b"",
        *,
        headers: dict[str, str] | None = None,
        content_type: str = "application/json",
        content_length: int | None = None,
        filler: int = 0,
        read_error: Exception | None = None,
    ) -> None:
        super().__init__(status, content_type=content_type, content_length=content_length)
        self.headers = headers or {}
        self._body = body
        self._filler = filler
        self._chunk_error = read_error
        self.bytes_read = 0

    async def iter_chunked(self, n: int) -> AsyncIterator[bytes]:
        for start in range(0, len(self._body), n):
            chunk = self._body[start : start + n]
            self.bytes_read += len(chunk)
            yield chunk
        left = self._filler
        while left > 0:
            chunk = b" " * min(n, left)
            left -= len(chunk)
            self.bytes_read += len(chunk)
            yield chunk
        if self._chunk_error:
            raise self._chunk_error

    async def json(self) -> Any:
        return json.loads(self._body)


# ── get_inventory ────────────────────────────────────────────────────


async def test_inventory_200_returns_data_and_etag() -> None:
    resp = BodyResponse(200, INVENTORY, headers={"ETag": 'W/"inv-1"'})
    client, session = token_client(resp)
    result = await client.get_inventory()
    assert result == InventoryResult(
        data={"schema": 1, "cellars": [], "racks": [], "wines": {}, "bottles": []},
        etag='W/"inv-1"',
        not_modified=False,
    )
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("GET", f"{BASE_URL}/api/inventory")
    assert kwargs["headers"] == {"Authorization": f"Bearer {TEST_TOKEN}"}
    assert resp.closed


async def test_inventory_200_without_etag() -> None:
    client, _ = token_client(BodyResponse(200, INVENTORY))
    result = await client.get_inventory()
    assert result.etag is None and result.data is not None and not result.not_modified


async def test_inventory_result_is_frozen() -> None:
    result = InventoryResult(data=None, etag="x", not_modified=True)
    with pytest.raises(AttributeError):
        result.etag = "y"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("headers", "expected_etag"),
    [({"ETag": '"inv-2"'}, '"inv-2"'), ({}, '"inv-1"')],
)
async def test_inventory_304_sends_if_none_match(
    headers: dict[str, str], expected_etag: str
) -> None:
    """304 means "your copy is current": no data, and the etag to keep."""
    resp = BodyResponse(304, headers=headers)
    client, session = token_client(resp)
    result = await client.get_inventory('"inv-1"')
    assert result == InventoryResult(data=None, etag=expected_etag, not_modified=True)
    sent = session.calls[0][2]["headers"]
    assert sent["If-None-Match"] == '"inv-1"'
    assert sent["Authorization"] == f"Bearer {TEST_TOKEN}"
    assert resp.closed and resp.bytes_read == 0


@pytest.mark.parametrize("status", [403, 404])
async def test_inventory_403_or_404_is_not_supported(status: int) -> None:
    """Older servers deny (token allowlist) or don't know the path."""
    for client, _ in (
        token_client(BodyResponse(status, b'{"error": "nope"}')),
        password_client(FakeResponse(200, {"token": "jwt"}), BodyResponse(status)),
    ):
        with pytest.raises(CellarionInventoryNotSupported) as excinfo:
            await client.get_inventory()
        assert isinstance(excinfo.value, CellarionApiError)
        assert not isinstance(excinfo.value, CellarionScopeError)


async def test_inventory_401_with_token_is_auth_error() -> None:
    client, session = token_client(BodyResponse(401))
    with pytest.raises(CellarionAuthError, match="revoked or invalid"):
        await client.get_inventory('"inv-1"')
    assert len(session.calls) == 1


async def test_inventory_401_relogs_once_for_password_clients() -> None:
    client, session = password_client(
        FakeResponse(200, {"token": "jwt-1"}),
        BodyResponse(401),
        FakeResponse(200, {"token": "jwt-2"}),
        BodyResponse(304, headers={"ETag": '"inv-1"'}),
    )
    result = await client.get_inventory('"inv-1"')
    assert result.not_modified
    assert [c[0] for c in session.calls] == ["POST", "GET", "POST", "GET"]
    retry = session.calls[-1][2]["headers"]
    assert retry == {"Authorization": "Bearer jwt-2", "If-None-Match": '"inv-1"'}

    last = BodyResponse(401)
    client, _ = password_client(
        FakeResponse(200, {"token": "jwt-1"}),
        BodyResponse(401),
        FakeResponse(200, {"token": "jwt-2"}),
        last,
    )
    with pytest.raises(CellarionAuthError, match="after retry"):
        await client.get_inventory()
    assert last.closed


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (BodyResponse(500, b""), r"status 500$"),
        (BodyResponse(429, b'{"error": "Too many requests"}'), "status 429: Too many requests"),
        (BodyResponse(204), "status 204"),
    ],
)
async def test_inventory_other_statuses_are_api_errors(response: Any, match: str) -> None:
    client, _ = token_client(response)
    with pytest.raises(CellarionApiError, match=match) as excinfo:
        await client.get_inventory()
    assert not isinstance(excinfo.value, CellarionInventoryNotSupported)


async def test_inventory_connection_error() -> None:
    client, _ = token_client(aiohttp.ClientError("refused"))
    with pytest.raises(CellarionApiError, match="Request failed"):
        await client.get_inventory()


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (b"[1, 2, 3]", "not a JSON object"),
        (b'"a string"', "not a JSON object"),
        (b"null", "not a JSON object"),
        (b"<!doctype html><html></html>", "not JSON"),
        (b"", "not JSON"),
        (b'{"schema": 1, "bottles": [', "not JSON"),
        (b"\xff\xfe\xfa", "not JSON"),
    ],
)
async def test_inventory_body_must_be_a_json_object(body: bytes, match: str) -> None:
    """Unlike the small reads, a bad inventory body is an error, never {}."""
    resp = BodyResponse(200, body, content_type="text/html")
    client, _ = token_client(resp)
    with pytest.raises(CellarionApiError, match=match):
        await client.get_inventory()
    assert resp.closed


async def test_inventory_cap_by_content_length_reads_nothing() -> None:
    resp = BodyResponse(200, content_length=MAX_INVENTORY_BYTES + 1, filler=MAX_INVENTORY_BYTES + 1)
    client, _ = token_client(resp)
    with pytest.raises(CellarionApiError, match="refusing to read"):
        await client.get_inventory()
    assert resp.bytes_read == 0
    assert resp.closed


@pytest.mark.parametrize("content_length", [None, 100])
async def test_inventory_cap_enforced_while_reading(content_length: int | None) -> None:
    """A missing or understated Content-Length does not get past the cap."""
    resp = BodyResponse(
        200, b'{"bottles": [', content_length=content_length, filler=MAX_INVENTORY_BYTES * 4
    )
    client, _ = token_client(resp)
    with pytest.raises(CellarionApiError, match="stopped reading"):
        await client.get_inventory()
    # Stopped within one chunk of the cap, not at the end of the stream
    assert MAX_INVENTORY_BYTES < resp.bytes_read <= MAX_INVENTORY_BYTES + 64 * 1024
    assert resp.closed


async def test_inventory_read_error_is_api_error() -> None:
    resp = BodyResponse(200, b'{"bottles": [', read_error=aiohttp.ClientPayloadError("cut"))
    client, _ = token_client(resp)
    with pytest.raises(CellarionApiError, match="read failed"):
        await client.get_inventory()
    assert resp.closed


# ── get_image ────────────────────────────────────────────────────────


def test_image_path_re_is_exported_compiled() -> None:
    assert isinstance(IMAGE_PATH_RE, re.Pattern)
    for ok in (
        THUMB,
        "/api/uploads/thumbs/originals/abc_DEF-123.jpg.webp",
        "/api/uploads/thumbs/processed/x.jpeg.webp",
        "/api/uploads/thumbs/processed/x.png.webp",
    ):
        assert IMAGE_PATH_RE.fullmatch(ok), ok


async def test_image_fetch_carries_no_credentials() -> None:
    resp = BodyResponse(200, b"RIFF....WEBP", content_type="image/webp")
    client, session = token_client(resp)
    assert await client.get_image(THUMB) == (b"RIFF....WEBP", "image/webp")
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("GET", f"{BASE_URL}{THUMB}")
    assert "Authorization" not in (kwargs.get("headers") or {})
    assert TEST_TOKEN not in repr(kwargs)
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"].total == 15
    assert resp.closed


async def test_image_fetch_does_not_log_in() -> None:
    """The uploads mount is public: a password client fetches without a login."""
    client, session = password_client(BodyResponse(200, b"img", content_type="image/webp"))
    assert await client.get_image(THUMB) == (b"img", "image/webp")
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "path",
    [
        "/api/uploads/thumbs/processed/../x.webp.webp",
        "/api/uploads/thumbs/processed/..%2Fx.webp.webp",
        "/api/uploads/thumbs/processed/%2e%2e.webp.webp",
        "/api/uploads/thumbs/../../inventory/x.webp.webp",
        f"https://evil.example{THUMB}",
        f"http://cellarion.local{THUMB}",
        f"//evil.example{THUMB}",
        f"{THUMB}?x=1",
        f"{THUMB}#frag",
        f"{THUMB}\n",
        f" {THUMB}",
        THUMB.replace("/", "\\"),
        "/api/uploads/thumbs/processed/x.gif.webp",
        "/api/uploads/thumbs/processed/x.webp",
        "/api/uploads/thumbs/processed/a/b.webp.webp",
        "/api/uploads/thumbs/other/x.webp.webp",
        "/api/uploads/processed/x.webp",
        "/api/inventory",
        "api/uploads/thumbs/processed/x.webp.webp",
        "",
    ],
)
async def test_image_rejects_anything_but_a_thumb_path(path: str) -> None:
    client, session = token_client()
    with pytest.raises(ValueError, match="thumbnail path"):
        await client.get_image(path)
    assert session.calls == []


@pytest.mark.parametrize("status", [302, 304, 401, 404, 500])
async def test_image_non_2xx_is_api_error(status: int) -> None:
    resp = BodyResponse(status, b"<html>", content_type="text/html")
    client, _ = token_client(resp)
    with pytest.raises(CellarionApiError, match=f"status {status}"):
        await client.get_image(THUMB)
    assert resp.closed and resp.bytes_read == 0


@pytest.mark.parametrize(
    "content_type", ["text/html", "application/octet-stream", "image/svg+xml", "IMAGE/SVG+XML"]
)
async def test_image_must_be_a_raster_image(content_type: str) -> None:
    resp = BodyResponse(200, b"<svg/>", content_type=content_type)
    client, _ = token_client(resp)
    with pytest.raises(CellarionApiError, match="not an image"):
        await client.get_image(THUMB)
    assert resp.closed and resp.bytes_read == 0


async def test_image_exactly_at_cap_is_accepted() -> None:
    client, _ = token_client(BodyResponse(200, content_type="image/webp", filler=MAX_IMAGE_BYTES))
    body, _ = await client.get_image(THUMB)
    assert len(body) == MAX_IMAGE_BYTES


@pytest.mark.parametrize("content_length", [None, 10])
async def test_image_cap_enforced_while_reading(content_length: int | None) -> None:
    resp = BodyResponse(
        200, content_type="image/webp", content_length=content_length, filler=MAX_IMAGE_BYTES * 8
    )
    client, _ = token_client(resp)
    with pytest.raises(CellarionApiError, match="stopped reading"):
        await client.get_image(THUMB)
    assert MAX_IMAGE_BYTES < resp.bytes_read <= MAX_IMAGE_BYTES + 64 * 1024
    assert resp.closed


async def test_image_cap_by_content_length_reads_nothing() -> None:
    resp = BodyResponse(200, content_type="image/webp", content_length=MAX_IMAGE_BYTES + 1)
    client, _ = token_client(resp)
    with pytest.raises(CellarionApiError, match="refusing to read"):
        await client.get_image(THUMB)
    assert resp.bytes_read == 0


@pytest.mark.parametrize("err", [aiohttp.ClientError("refused"), TimeoutError()])
async def test_image_connection_error(err: Exception) -> None:
    client, _ = token_client(err)
    with pytest.raises(CellarionApiError, match="Image request failed"):
        await client.get_image(THUMB)
