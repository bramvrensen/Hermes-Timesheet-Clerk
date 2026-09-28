"""Require both the review page and the control API to be available."""
from urllib.request import urlopen


def main() -> None:
    for url in ("http://127.0.0.1:8501/_stcore/health", "http://127.0.0.1:8502/healthz"):
        with urlopen(url, timeout=3) as response:
            if response.status != 200:
                raise SystemExit(1)


if __name__ == "__main__":
    main()
