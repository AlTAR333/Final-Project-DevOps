"""Database connection helper shared by API, worker and scripts.

Owner: Tristan.
"""

# TODO(Tristan): choose the driver (e.g. psycopg 3 + psycopg_pool) and pin it in
# api/requirements.txt and worker/requirements.txt.


def connect(database_url: str):
    raise NotImplementedError
