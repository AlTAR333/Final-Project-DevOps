"""HTTP application and routes. Run with: python -m api.app

Owner: Armand. Contract: docs/assignment/API_CONTRACT_EN.md

  GET  /health/live              -> health.live
  GET  /health/ready             -> health.ready
  GET  /api/v1/catalog           -> catalog.get_catalog
  GET  /api/v1/inventory/{sku}   -> catalog.get_inventory
  POST /api/v1/orders            -> validation.validate_order, then orders.place_order (Tristan)
  GET  /api/v1/orders/{order_id} -> orders.get_order (Tristan)
  GET  /metrics                  -> metrics.render
"""

# TODO(Armand): choose the web framework, pin it in api/requirements.txt,
# serve on common.contract.API_PORT and enforce MAX_BODY_BYTES.


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
