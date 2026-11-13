"""Minimal health endpoint for Kubernetes probes.

Owner: Mink.

/health/live  200 while the worker loop keeps beating; 503 if it has been stuck too long.
/health/ready 200 if the database answers and the jobs table exists; 503 otherwise.
Standard library only, served from a daemon thread next to the worker loop.
"""

import json
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HEALTH_PORT = 8081


class Health:
    def __init__(
        self,
        check_db: Callable[[], None],
        stale_after: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._check_db = check_db  # raises if the database is unusable
        self._stale_after = stale_after
        self._clock = clock
        self._last_beat = clock()

    def beat(self) -> None:
        self._last_beat = self._clock()

    def live(self) -> tuple[int, dict]:
        if self._clock() - self._last_beat > self._stale_after:
            return 503, {"status": "stalled"}
        return 200, {"status": "ok"}

    def ready(self) -> tuple[int, dict]:
        try:
            self._check_db()
        except Exception:  # any DB failure means "cannot process jobs"; never echo the error
            return 503, {"status": "not_ready"}
        return 200, {"status": "ready"}


def _handler(health: Health) -> type[BaseHTTPRequestHandler]:
    routes = {"/health/live": health.live, "/health/ready": health.ready}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (http.server naming)
            route = routes.get(self.path)
            status, body = route() if route else (404, {"status": "not_found"})
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):  # probes every few seconds would flood the logs
            pass

    return Handler


def serve(port: int, health: Health) -> ThreadingHTTPServer:
    """Start serving in a daemon thread and return the server (call .shutdown() to stop)."""
    server = ThreadingHTTPServer(("0.0.0.0", port), _handler(health))
    threading.Thread(target=server.serve_forever, name="health", daemon=True).start()
    return server
