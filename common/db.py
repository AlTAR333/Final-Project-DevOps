"""Database connection helper shared by API, worker and scripts.

Owner: Tristan.
"""

import psycopg


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, autocommit=True)
