"""DTO клиента kb-support (E7, FR-7.2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimRef:
    """Ссылка на претензию COMPENSATION в kb-support."""

    id: str
    status: str
