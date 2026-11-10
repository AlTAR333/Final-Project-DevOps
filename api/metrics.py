"""Prometheus exposition for /metrics. Metric names live in common.contract.

Owner: Armand. Worker retry/failure counts come from the jobs table (agree with Mink).
"""


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    raise NotImplementedError


def render(conn) -> str:
    raise NotImplementedError
