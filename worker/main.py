"""Worker loop. Run with: python -m worker.main

Owner: Mink. Claims jobs, processes them, retries with backoff, exits cleanly on SIGTERM.
"""


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
