"""Fixture: SQL к СВОИМ таблицам kb-partners — НЕ нарушение (#28).

`service_requests`/`request_history`/`request_messages` принадлежат kb-partners,
поэтому прямые запросы к ним легитимны и НЕ должны триггерить AT-001 (в т.ч.
lowercase).
"""

from sqlalchemy import text


def queries(session):
    session.execute(text("select * from service_requests where status = 'NEW'"))
    session.execute(text("SELECT * FROM request_history WHERE request_id = :id"))
    session.execute(text("update request_messages set is_internal = false where id = :id"))
