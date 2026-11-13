"""Unit tests for api.health (owner: Armand). Fake connection, no database."""

from api.health import live, ready


class FakeResult:
    def __init__(self, value):
        self._value = value

    def fetchone(self):
        return (self._value,)


class FakeConn:
    """Answers the two readiness queries in order: tables exist, then seed present."""

    def __init__(self, *answers, error=None):
        self.answers = list(answers)
        self.error = error

    def execute(self, sql, params=None):
        if self.error:
            raise self.error
        return FakeResult(self.answers.pop(0))


def test_live_is_static_and_needs_no_database():
    assert live() == {"status": "ok"}


def test_ready_when_migrated_and_seeded():
    assert ready(FakeConn(True, True)) == (200, {"status": "ready"})


def test_not_ready_when_tables_missing():
    assert ready(FakeConn(False)) == (503, {"status": "not_ready"})


def test_not_ready_when_seed_missing():
    assert ready(FakeConn(True, False)) == (503, {"status": "not_ready"})


def test_not_ready_when_database_unreachable():
    conn = FakeConn(error=ConnectionError("connection refused: postgresql://user:secret@db"))
    status, body = ready(conn)
    assert (status, body) == (503, {"status": "not_ready"})
    assert "secret" not in str(body)  # the driver error never leaks into the response
