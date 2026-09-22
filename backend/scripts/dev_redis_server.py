"""Redis-compatible TCP server backed by fakeredis, for running the test suite
on machines without Docker or a native Redis. Development only.

    python scripts/dev_redis_server.py [port]
"""
from __future__ import annotations

import sys

from fakeredis import TcpFakeServer

DEFAULT_PORT = 6379


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = TcpFakeServer(("127.0.0.1", port), server_type="redis")
    print(f"fakeredis listening on 127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
