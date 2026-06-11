"""Интеграционные тесты CRUD конфигураций каналов (§11.2, M3.2a).

Общие фикстуры `make_client`/`make_principal` — из conftest.py. Доступ — только
admin-скоуп; `inbound_token` не возвращается в выдаче.
"""

from __future__ import annotations

from collections.abc import Callable

from httpx import AsyncClient

from api.auth.principal import PrincipalKind
from api.auth.scopes import STAFF_ADMIN_SCOPE

_CHANNELS = "/api/v1/partners/channels"


def _admin(make_principal: Callable[..., object]) -> object:
    return make_principal(PrincipalKind.OPERATOR, scopes=frozenset({STAFF_ADMIN_SCOPE}))


async def test_create_and_get_channel(
    make_client: Callable[..., AsyncClient], make_principal: Callable[..., object]
) -> None:
    client = make_client(_admin(make_principal))
    resp = await client.post(
        _CHANNELS,
        json={
            "collaborator_id": "c-1",
            "channel_type": "API",
            "priority": 10,
            "config": {"deliver_path": "/orders"},
            "inbound_token": "secret-token",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["collaborator_id"] == "c-1"
    assert body["channel_type"] == "API"
    assert "inbound_token" not in body  # секрет не возвращается
    config_id = body["id"]

    got = await client.get(f"{_CHANNELS}/{config_id}")
    assert got.status_code == 200
    assert got.json()["priority"] == 10
    assert "inbound_token" not in got.json()


async def test_duplicate_channel_409(
    make_client: Callable[..., AsyncClient], make_principal: Callable[..., object]
) -> None:
    client = make_client(_admin(make_principal))
    payload = {"collaborator_id": "c-dup", "channel_type": "API"}
    first = await client.post(_CHANNELS, json=payload)
    second = await client.post(_CHANNELS, json=payload)
    assert first.status_code == 201
    assert second.status_code == 409


async def test_list_channels_filtered_by_collaborator(
    make_client: Callable[..., AsyncClient], make_principal: Callable[..., object]
) -> None:
    client = make_client(_admin(make_principal))
    await client.post(_CHANNELS, json={"collaborator_id": "c-a", "channel_type": "API"})
    await client.post(_CHANNELS, json={"collaborator_id": "c-b", "channel_type": "EMAIL"})
    resp = await client.get(_CHANNELS, params={"collaborator_id": "c-a"})
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["collaborator_id"] == "c-a"


async def test_patch_channel(
    make_client: Callable[..., AsyncClient], make_principal: Callable[..., object]
) -> None:
    client = make_client(_admin(make_principal))
    created = (
        await client.post(_CHANNELS, json={"collaborator_id": "c-p", "channel_type": "API"})
    ).json()
    resp = await client.patch(
        f"{_CHANNELS}/{created['id']}",
        json={
            "priority": 5,
            "is_active": False,
            "config": {"deliver_path": "/v2/orders"},
            "inbound_token": "rotated-token",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["priority"] == 5
    assert body["is_active"] is False
    assert body["config"] == {"deliver_path": "/v2/orders"}
    assert "inbound_token" not in body  # секрет не возвращается даже после ротации


async def test_non_admin_forbidden_403(
    make_client: Callable[..., AsyncClient], make_principal: Callable[..., object]
) -> None:
    client = make_client(make_principal(PrincipalKind.OPERATOR))  # без admin-скоупа
    resp = await client.get(_CHANNELS)
    assert resp.status_code == 403


async def test_get_unknown_channel_404(
    make_client: Callable[..., AsyncClient], make_principal: Callable[..., object]
) -> None:
    import uuid

    client = make_client(_admin(make_principal))
    resp = await client.get(f"{_CHANNELS}/{uuid.uuid4()}")
    assert resp.status_code == 404
