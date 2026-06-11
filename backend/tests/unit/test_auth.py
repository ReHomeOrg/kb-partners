"""Тесты auth-слоя: Principal/scopes, JWKS-кеш, JwtVerifier, dependencies.

JWT-тесты — оффлайн: генерируем RSA-ключ, собираем JWKS вручную и инжектим
fetcher в `JwksCache` (без живого Keycloak).
"""

from __future__ import annotations

import json
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from api.auth.dependencies import build_verifier, get_current_principal
from api.auth.jwks import JwksCache, JwksUnknownKeyError
from api.auth.jwt_verifier import JwtVerifier, claims_to_principal
from api.auth.principal import Principal, PrincipalKind
from api.auth.scopes import AGENT_SCOPE, PARTNER_SCOPE, STAFF_ADMIN_SCOPE
from api.config import Settings
from api.errors import ProblemException

_KID = "test-key-1"


def _make_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks_for(key: rsa.RSAPrivateKey) -> dict[str, object]:
    pub_jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    pub_jwk["kid"] = _KID
    return {"keys": [pub_jwk]}


def _sign(key: rsa.RSAPrivateKey, claims: dict[str, object]) -> str:
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": _KID})


# --- Principal / scopes ---------------------------------------------------


def test_principal_role_properties() -> None:
    op = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR)
    assert op.is_operator and not op.is_partner and not op.is_agent

    partner = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.PARTNER, partner_id="c-1")
    assert partner.is_partner

    agent = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.AGENT, on_behalf_of=uuid.uuid4())
    assert agent.is_agent

    admin = Principal(
        user_id=uuid.uuid4(), kind=PrincipalKind.OPERATOR, scopes=frozenset({STAFF_ADMIN_SCOPE})
    )
    assert admin.is_staff_admin


def test_principal_scope_derived_roles() -> None:
    p = Principal(
        user_id=uuid.uuid4(),
        kind=PrincipalKind.REQUESTER,
        scopes=frozenset({PARTNER_SCOPE, AGENT_SCOPE}),
    )
    assert p.is_partner and p.is_agent


# --- claims_to_principal --------------------------------------------------


def test_claims_to_principal_full() -> None:
    sub = uuid.uuid4()
    act = uuid.uuid4()
    p = claims_to_principal(
        {
            "sub": str(sub),
            "kbp_kind": "agent",
            "kbp_partner_id": "collab-42",
            "kbp_act_sub": str(act),
            "scope": "agent operator",
        }
    )
    assert p.user_id == sub
    assert p.kind is PrincipalKind.AGENT
    assert p.partner_id == "collab-42"
    assert p.on_behalf_of == act
    assert "operator" in p.scopes


def test_claims_to_principal_defaults_and_bad_sub() -> None:
    p = claims_to_principal({"sub": str(uuid.uuid4())})
    assert p.kind is PrincipalKind.REQUESTER
    assert p.partner_id is None and p.on_behalf_of is None

    with pytest.raises(ProblemException):
        claims_to_principal({"sub": "not-a-uuid"})


# --- JWKS cache -----------------------------------------------------------


async def test_jwks_cache_fetches_and_rotates() -> None:
    key = _make_key()
    jwks = _jwks_for(key)
    calls = {"n": 0}

    async def fetcher(_url: str) -> dict[str, object]:
        calls["n"] += 1
        return jwks

    cache = JwksCache("http://x/certs", ttl_seconds=300, fetcher=fetcher)
    assert await cache.get_key(_KID) is not None
    # повторный вызов в пределах TTL — без нового fetch
    await cache.get_key(_KID)
    assert calls["n"] == 1
    with pytest.raises(JwksUnknownKeyError):
        await cache.get_key("unknown-kid")


# --- JwtVerifier ----------------------------------------------------------


async def test_verifier_accepts_valid_token() -> None:
    key = _make_key()
    jwks = _jwks_for(key)

    async def fetcher(_url: str) -> dict[str, object]:
        return jwks

    cache = JwksCache("http://x/certs", ttl_seconds=300, fetcher=fetcher)
    verifier = JwtVerifier(
        jwks=cache, issuer="iss", audience="kb-partners", algorithms=["RS256"], leeway=0
    )
    sub = uuid.uuid4()
    token = _sign(
        key,
        {
            "sub": str(sub),
            "iss": "iss",
            "aud": "kb-partners",
            "exp": 9999999999,
            "kbp_kind": "operator",
        },
    )
    principal = await verifier.verify(token)
    assert principal.user_id == sub
    assert principal.is_operator


async def test_verifier_rejects_bad_audience() -> None:
    key = _make_key()
    jwks = _jwks_for(key)

    async def fetcher(_url: str) -> dict[str, object]:
        return jwks

    cache = JwksCache("http://x/certs", ttl_seconds=300, fetcher=fetcher)
    verifier = JwtVerifier(
        jwks=cache, issuer="iss", audience="kb-partners", algorithms=["RS256"], leeway=0
    )
    token = _sign(key, {"sub": str(uuid.uuid4()), "iss": "iss", "aud": "other", "exp": 9999999999})
    with pytest.raises(ProblemException):
        await verifier.verify(token)


async def test_verifier_rejects_token_without_kid() -> None:
    key = _make_key()

    async def fetcher(_url: str) -> dict[str, object]:
        return _jwks_for(key)

    cache = JwksCache("http://x/certs", ttl_seconds=300, fetcher=fetcher)
    verifier = JwtVerifier(jwks=cache, issuer="", audience="", algorithms=["RS256"], leeway=0)
    token = jwt.encode({"sub": str(uuid.uuid4()), "exp": 9999999999}, key, algorithm="RS256")
    with pytest.raises(ProblemException):
        await verifier.verify(token)


# --- dependencies ---------------------------------------------------------


def test_build_verifier_none_when_unconfigured() -> None:
    assert build_verifier(Settings(auth_jwks_url="")) is None
    assert build_verifier(Settings(auth_jwks_url="http://x/certs")) is not None


async def test_get_current_principal_401_paths() -> None:
    # auth не сконфигурирован (дефолтный Settings: пустой jwks url) → 401
    with pytest.raises(ProblemException):
        await get_current_principal(credentials=None)
