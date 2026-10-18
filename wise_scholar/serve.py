"""Serve the app on 127.0.0.1 and every address in WISE_SCHOLAR_LISTEN. The agents always call back on 127.0.0.1;
a second address (the tailnet one) lets a proxy reach the server without opening it to the LAN."""

import logging
import os
import socket
import sys

import uvicorn

from wise_scholar.backends import PORT

log = logging.getLogger("uvicorn.error")


def _bind(host: str) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.create_server((host, PORT), family=family, backlog=2048)
    sock.set_inheritable(True)
    return sock


def main() -> None:
    config = uvicorn.Config("wise_scholar.app:app", port=PORT)
    try:
        sockets = [_bind("127.0.0.1")]
    except OSError as e:
        log.error("cannot listen on 127.0.0.1:%d: %s", PORT, e)
        sys.exit(1)
    for host in sorted({h.strip() for h in os.environ.get("WISE_SCHOLAR_LISTEN", "").split(",") if h.strip()} - {"127.0.0.1"}):
        try:
            sockets.append(_bind(host))
        except OSError as e:
            # an address that is down (tailscale off) must not take the local app and its agents with it
            log.warning("not listening on %s:%d: %s", host, PORT, e)
    for sock in sockets:
        log.info("listening on %s", sock.getsockname()[:2])
    uvicorn.Server(config).run(sockets=sockets)


if __name__ == "__main__":
    main()
