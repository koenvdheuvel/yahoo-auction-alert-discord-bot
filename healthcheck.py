"""Container readiness probe; independent of bot credentials and SDK imports."""
import os
import sys
from urllib.error import URLError
from urllib.request import urlopen


def main():
    if os.getenv("MONITORING_ENABLED", "true").lower() in {"false", "0", "no"}:
        return 0
    host = os.getenv("MONITORING_HOST", "127.0.0.1")
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    if ":" in host:
        host = f"[{host}]"
    port = os.getenv("MONITORING_PORT", "9100")
    try:
        with urlopen(f"http://{host}:{port}/health/ready", timeout=3) as response:
            return 0 if response.status == 200 else 1
    except (URLError, OSError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
