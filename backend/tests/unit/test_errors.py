"""Тесты RFC 7807 ProblemException и рендера problem+json."""

from __future__ import annotations

import pytest

from api.errors import PROBLEM_CONTENT_TYPE, ProblemException, render_problem


@pytest.mark.parametrize(
    ("factory", "status", "title"),
    [
        (ProblemException.bad_request, 400, "Bad Request"),
        (ProblemException.unauthorized, 401, "Unauthorized"),
        (ProblemException.forbidden, 403, "Forbidden"),
        (ProblemException.not_found, 404, "Not Found"),
        (ProblemException.conflict, 409, "Conflict"),
        (ProblemException.unprocessable, 422, "Unprocessable Entity"),
    ],
)
def test_factories(factory, status, title) -> None:  # type: ignore[no-untyped-def]
    exc = factory("detail text")
    assert exc.status == status
    assert exc.title == title
    assert exc.detail == "detail text"


def test_render_problem_body_and_media_type() -> None:
    exc = ProblemException.conflict("boom")
    resp = render_problem(exc)
    assert resp.status_code == 409
    assert resp.media_type == PROBLEM_CONTENT_TYPE


def test_render_problem_includes_errors_list() -> None:
    exc = ProblemException(
        status=422,
        title="Unprocessable Entity",
        type_="https://api.rehome.one/errors/unprocessable-entity",
        errors=[{"field": "category", "message": "required"}],
    )
    resp = render_problem(exc)
    assert resp.status_code == 422
