"""Contract tests: run the client against a real Cellarion server.

These pin down the shape of every response the Home Assistant integration
depends on, so a change on the server side shows up here before it shows
up as user issues. They only run when a server and a read-scoped token are
provided through the environment:

    CELLARION_CONTRACT_URL    e.g. https://cellarion.app
    CELLARION_CONTRACT_TOKEN  a personal API token with the `read` scope

Nothing here writes: no bottle is consumed and no token is revoked. Use a
dedicated test account with a few bottles in it, never a real cellar.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

import aiohttp
import pytest

from pycellarion import (
    IMAGE_PATH_RE,
    CellarionClient,
    CellarionInventoryNotSupported,
    CellarionPushNotSupported,
)

URL = os.environ.get("CELLARION_CONTRACT_URL")
TOKEN = os.environ.get("CELLARION_CONTRACT_TOKEN")

pytestmark = pytest.mark.skipif(
    not (URL and TOKEN),
    reason="set CELLARION_CONTRACT_URL and CELLARION_CONTRACT_TOKEN to run the contract tests",
)

MATURITY_KEYS = {"peak", "declining", "late", "early", "notReady"}
INVENTORY_KEYS = {"schema", "generatedAt", "cellars", "racks", "wines", "bottles"}


@pytest.fixture
async def client() -> AsyncIterator[CellarionClient]:
    assert URL and TOKEN
    async with aiohttp.ClientSession() as session:
        yield CellarionClient(session, URL, token=TOKEN)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


async def test_health(client: CellarionClient) -> None:
    health = await client.get_health()
    assert health.get("status") in {"ok", "degraded"}, health


async def test_stats_overview_shape(client: CellarionClient) -> None:
    data = await client.get_stats_overview()
    stats = data["stats"]
    overview = stats["overview"]
    for key in ("totalBottles", "totalConsumed", "uniqueWines", "totalCountries"):
        assert _is_int(overview[key]), key
    assert isinstance(overview["totalValue"], int | float)
    assert isinstance(overview["currency"], str) and len(overview["currency"]) == 3
    assert overview.get("healthScore") is None or _is_int(overview["healthScore"])

    maturity = stats["maturity"]
    assert set(maturity) >= MATURITY_KEYS, set(maturity)
    assert all(_is_int(maturity[k]) for k in MATURITY_KEYS)

    assert isinstance(stats["pace"], dict)
    assert isinstance(stats["cellarBreakdown"], list)
    for cellar in stats["cellarBreakdown"]:
        assert isinstance(cellar["name"], str)
        assert _is_int(cellar["bottleCount"])
    assert isinstance(stats["byType"], dict)
    assert isinstance(stats["byCountry"], list)
    assert isinstance(stats["topProducers"], list)

    # The card's "Drink soon" list and its consume buttons
    ladder = stats["urgencyLadder"]
    assert isinstance(ladder, list)
    for bottle in ladder:
        assert isinstance(bottle["id"], str) and len(bottle["id"]) == 24
        assert isinstance(bottle["name"], str)
        assert isinstance(bottle["status"], str)
        assert "vintage" in bottle


async def test_cellars_shape(client: CellarionClient) -> None:
    data = await client.get_cellars()
    assert _is_int(data["count"])
    assert isinstance(data["cellars"], list)
    assert len(data["cellars"]) == data["count"]
    for cellar in data["cellars"]:
        assert isinstance(cellar["_id"], str)
        assert isinstance(cellar["name"], str)


async def test_notifications_shape(client: CellarionClient) -> None:
    data = await client.get_notifications()
    assert isinstance(data["notifications"], list)
    assert _is_int(data["unreadCount"])


async def test_peak_bottles_shape(client: CellarionClient) -> None:
    data = await client.get_peak_bottles(limit=5)
    bottles = data["bottles"]
    assert _is_int(bottles["count"]) and _is_int(bottles["total"])
    items = bottles["items"]
    assert isinstance(items, list) and len(items) <= 5
    for bottle in items:
        assert isinstance(bottle["_id"], str) and len(bottle["_id"]) == 24
        assert isinstance(bottle["wineDefinition"]["name"], str)
        assert "vintage" in bottle
        assert bottle.get("drinkTo") is None or _is_int(bottle["drinkTo"])


async def test_account_id(client: CellarionClient) -> None:
    """The reauth same-account guard relies on this being a stable string."""
    account_id = await client.get_account_id()
    assert isinstance(account_id, str) and account_id


async def test_push_stream_connects(client: CellarionClient) -> None:
    """The stream must be reachable and identify itself as event-stream."""
    try:
        stream = client.events_stream()
        first = await asyncio.wait_for(stream.__anext__(), timeout=20)
    except CellarionPushNotSupported:
        pytest.fail("the server no longer offers /api/events/stream")
    assert first == "_connected"
    await stream.aclose()


async def test_inventory_shape_and_conditional_get(client: CellarionClient) -> None:
    """The bottles service and card read this; a 304 must follow an unchanged etag."""
    try:
        first = await client.get_inventory()
    except CellarionInventoryNotSupported:
        pytest.skip("the server has no GET /api/inventory yet")
    assert not first.not_modified
    data = first.data
    assert data is not None
    assert set(data) >= INVENTORY_KEYS, set(data)
    assert data["schema"] == 1
    assert isinstance(data["generatedAt"], str)

    cellar_ids = set()
    for cellar in data["cellars"]:
        assert isinstance(cellar["id"], str) and isinstance(cellar["name"], str)
        assert cellar["role"] in {"owner", "editor", "viewer"}
        cellar_ids.add(cellar["id"])
    for rack in data["racks"]:
        assert isinstance(rack["id"], str) and rack["cellar"] in cellar_ids

    wines = data["wines"]
    assert isinstance(wines, dict)
    images: list[str] = []
    for wine in wines.values():
        assert isinstance(wine["name"], str)
        assert isinstance(wine["grapes"], list)
        assert wine["image"] is None or IMAGE_PATH_RE.fullmatch(wine["image"]), wine["image"]
        if wine["image"]:
            images.append(wine["image"])

    assert isinstance(data["bottles"], list)
    for bottle in data["bottles"]:
        assert isinstance(bottle["id"], str) and len(bottle["id"]) == 24
        assert bottle["cellar"] in cellar_ids
        assert bottle["wine"] is None or bottle["wine"] in wines
        assert bottle["wine"] is not None or isinstance(bottle["pending"], dict)
        assert isinstance(bottle["opened"], bool)
        assert isinstance(bottle["personal"], list)
        assert set(bottle["window"]) == {"drinkFrom", "peakFrom", "peakUntil", "drinkTo"}
        assert all(v is None or _is_int(v) for v in bottle["window"].values())
        location = bottle["location"]
        assert location is None or _is_int(location["position"])
        assert bottle["image"] is None or IMAGE_PATH_RE.fullmatch(bottle["image"])
        if bottle["image"]:
            images.append(bottle["image"])

    assert first.etag, "the inventory must carry an ETag"
    second = await client.get_inventory(first.etag)
    assert second.not_modified and second.data is None
    assert second.etag == first.etag

    if images:
        body, content_type = await client.get_image(images[0])
        assert body and content_type.startswith("image/")
