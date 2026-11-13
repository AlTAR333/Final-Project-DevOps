"""Shared pytest fixtures (owner: Tristan). Integration tests use an isolated test database only."""

import os
import uuid

import pytest

from common.db import connect
from common.models import OrderRequest
from scripts.reset_test_data import check_safe, reset


@pytest.fixture(scope="session")
def database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    return url


@pytest.fixture
def db(database_url):
    with connect(database_url) as conn:
        check_safe(os.environ.get("APP_ENV", "dev"), conn.info.dbname)
        reset(conn)
        yield conn


@pytest.fixture
def make_order():
    def _make(items, customer_id="CUST-042"):
        payload = {
            "customer_id": customer_id,
            "items": [{"sku": s, "quantity": q} for s, q in items],
        }
        return OrderRequest(customer_id=customer_id, items=list(items), payload=payload)

    return _make


@pytest.fixture
def new_key():
    return lambda: "test-" + uuid.uuid4().hex
