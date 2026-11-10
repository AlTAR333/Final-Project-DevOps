"""Values fixed by docs/assignment/API_CONTRACT_EN.md, shared by API and worker.

Owner: all three. Any change needs a PR reviewed by every team member.
"""

from enum import StrEnum

API_PORT = 8080
MAX_BODY_BYTES = 16 * 1024
IDEMPOTENCY_KEY_MIN_LEN = 8
IDEMPOTENCY_KEY_MAX_LEN = 128
CUSTOMER_ID_MAX_LEN = 64
ITEMS_MIN, ITEMS_MAX = 1, 10
QUANTITY_MIN, QUANTITY_MAX = 1, 20


class OrderStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    DEAD = "dead"  # dead letter / operator review; stock stays reserved


class ErrorCode(StrEnum):
    INVALID_JSON = "INVALID_JSON"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_QUANTITY = "INVALID_QUANTITY"
    INVALID_SKU = "INVALID_SKU"
    IDEMPOTENCY_REQUIRED = "IDEMPOTENCY_REQUIRED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    SKU_NOT_FOUND = "SKU_NOT_FOUND"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"


# Required /metrics series. Labels must never contain customer IDs or idempotency keys.
METRIC_ORDERS_CREATED = "fulfillops_orders_created_total"
METRIC_ORDERS_FAILED = "fulfillops_orders_failed_total"
METRIC_WORKER_RETRIES = "fulfillops_worker_retries_total"
METRIC_HTTP_REQUESTS = "fulfillops_http_requests_total"
METRIC_HTTP_DURATION = "fulfillops_http_request_duration_seconds"
