"""Platform-клиент реестра партнёров kb-platform (E3, FR-3.1).

Публичная поверхность: `PlatformClient` Protocol + DTO `CollaboratorCandidate` +
HTTP-реализация `HttpPlatformClient`. Провизорный контракт kb-platform изолирован
в `adapter.py` (ADR-0002). Связь — только по HTTP (арх-константа ADR-0001).
"""

from __future__ import annotations

from api.clients.platform.adapter import HttpPlatformClient
from api.clients.platform.models import CollaboratorCandidate, ServiceOrderRef
from api.clients.platform.protocol import PlatformClient

__all__ = ["PlatformClient", "HttpPlatformClient", "CollaboratorCandidate", "ServiceOrderRef"]
