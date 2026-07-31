"""Юнит-тесты клиента kb-files (вложения #5) через httpx.MockTransport."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.files.adapter import HttpKbFilesClient
from api.clients.retry import RetryPolicy

Handler = Callable[[httpx.Request], httpx.Response]
SleepFn = Callable[[float], Awaitable[None]]


@pytest.fixture
def noop_sleep() -> SleepFn:
    async def _sleep(_seconds: float) -> None:
        return None

    return _sleep


def _client(handler: Handler, sleep: SleepFn) -> HttpKbFilesClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://files")
    resilient = ResilientHttpClient(
        client_name="kb_files",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30, now=lambda: 0.0),
        retry=RetryPolicy(attempts=1),
        sleep=sleep,
        monotonic=lambda: 0.0,
    )
    return HttpKbFilesClient(http_client=resilient, token_provider=StaticTokenProvider("tok"))


async def test_get_metadata_maps_and_authorizes(noop_sleep: SleepFn) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET"
        assert req.url.path == "/api/v1/files/f-1"
        assert req.headers["authorization"] == "Bearer tok"
        return httpx.Response(
            200,
            json={
                "id": "f-1",
                "owner_scope": "partner:request:r-1",
                "content_type": "image/png",
                "size_bytes": 1234,
                "filename": "photo.png",
            },
        )

    meta = await _client(handler, noop_sleep).get_metadata("f-1")
    assert meta is not None
    assert meta.file_id == "f-1"
    assert meta.owner_scope == "partner:request:r-1"
    assert meta.content_type == "image/png"
    assert meta.size_bytes == 1234
    assert meta.filename == "photo.png"


async def test_get_metadata_404_degrades(noop_sleep: SleepFn) -> None:
    meta = await _client(lambda req: httpx.Response(404), noop_sleep).get_metadata("nope")
    assert meta is None


async def test_get_metadata_malformed_degrades(noop_sleep: SleepFn) -> None:
    meta = await _client(lambda req: httpx.Response(200, content=b"x"), noop_sleep).get_metadata(
        "f"
    )
    assert meta is None


async def test_get_download_url_maps(noop_sleep: SleepFn) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/files/f-1/download-url"
        return httpx.Response(
            200, json={"file_id": "f-1", "url": "https://s3/x?sig=y", "expires_in_seconds": 900}
        )

    url = await _client(handler, noop_sleep).get_download_url("f-1")
    assert url is not None
    assert url.url == "https://s3/x?sig=y"
    assert url.expires_in_seconds == 900


async def test_get_download_url_5xx_degrades(noop_sleep: SleepFn) -> None:
    url = await _client(lambda req: httpx.Response(503), noop_sleep).get_download_url("f-1")
    assert url is None
