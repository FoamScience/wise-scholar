"""The way out of the sandbox for a command the learner allowed: an HTTP proxy on a Unix socket that connects to
ports 80 and 443 of public IPv4 addresses and to nothing else. The sandbox itself keeps having no network."""

import asyncio
import ipaddress
import json
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

CONNECT_PORT = 443
HTTP_PORT = 80
HEAD_LIMIT = 65536
HEAD_TIMEOUT = 10
CONNECT_TIMEOUT = 5
LOOKUP_TIMEOUT = 5
# The command can open the socket itself, as often as it likes: more than this many at once are turned away.
CONNECTIONS = 64
# Name lookups run in the event loop's shared thread pool and cannot be cancelled: only a few at a time.
LOOKUPS = 8
REFUSED = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


def _local(address: str) -> bool:
    """Whether an address belongs to this machine: only such an address can be bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.bind((address, 0))
        except OSError:
            return False
    return True


def local_networks() -> list[ipaddress.IPv4Network]:
    """The networks this machine sits on directly, from `ip addr`; empty where that tool is missing."""
    try:
        listing = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=5).stdout
        entries = [a for interface in json.loads(listing or "[]") for a in interface.get("addr_info", [])]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return [ipaddress.ip_network(f"{a['local']}/{a['prefixlen']}", strict=False) for a in entries]


def allowed(address: str, networks: list[ipaddress.IPv4Network] = []) -> bool:
    """Public IPv4 only. Private, loopback, link-local and carrier-NAT ranges are out, and so is all of IPv6:
    there every device of the local network has a global address, and NAT64 prefixes lead back to private IPv4.
    Out too: this machine's own addresses, and hosts on a network it is attached to, where some sites use public
    addresses. Not recognisable from here: the outer address of the router in front of this machine."""
    ip = ipaddress.ip_address(address)
    return ip.version == 4 and ip.is_global and not any(ip in network for network in networks) and not _local(address)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


class Proxy:
    """One proxy for one allowed command; close() also ends the tunnels that are still open."""

    def __init__(self) -> None:
        self._server: asyncio.Server | None = None
        self._clients = 0
        self._writers: set[asyncio.StreamWriter] = set()
        self._networks: list[ipaddress.IPv4Network] = []
        self._lookups = asyncio.Semaphore(LOOKUPS)

    async def start(self, path: Path) -> None:
        self._networks = await asyncio.to_thread(local_networks)
        self._server = await asyncio.start_unix_server(self._serve, path, limit=HEAD_LIMIT)

    def close(self) -> None:
        if self._server:
            self._server.close()
        for writer in list(self._writers):
            writer.transport.abort()

    async def _dial(self, host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
        """Connect to the first allowed address of a host. The address checked is the address dialled, so a name
        that resolves to the local network or to this machine gets nowhere."""
        try:
            async with self._lookups:
                lookup = asyncio.get_running_loop().getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
                found = await asyncio.wait_for(lookup, LOOKUP_TIMEOUT)
        except (OSError, TimeoutError):
            return None
        for *_, (address, _port) in found:
            if not allowed(address, self._networks):
                continue
            try:
                return await asyncio.wait_for(asyncio.open_connection(address, port), CONNECT_TIMEOUT)
            except (OSError, TimeoutError):
                continue
        return None

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self._clients >= CONNECTIONS:
            writer.transport.abort()
            return
        self._clients += 1
        self._writers.add(writer)
        upstream = None
        try:
            upstream = await self._tunnel(reader, writer)
        finally:
            self._clients -= 1
            self._writers.discard(writer)
            self._writers.discard(upstream)
            writer.close()

    async def _tunnel(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> asyncio.StreamWriter | None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT)
            request, _, headers = head.partition(b"\r\n")
            method, target, version = request.decode("latin-1").split(" ")
            if method == "CONNECT":
                host, _, port = target.rpartition(":")
                wanted, forward = CONNECT_PORT, b""
            else:
                url = urlsplit(target)
                host, port, wanted = url.hostname or "", url.port or HTTP_PORT, HTTP_PORT
                path = (url.path or "/") + ("?" + url.query if url.query else "")
                kept = [h for h in headers.split(b"\r\n") if h and not h.lower().startswith((b"proxy-", b"connection:"))]
                # One request per connection: the next one could name another host, which was not checked.
                forward = b"\r\n".join([f"{method} {path} {version}".encode("latin-1"), *kept, b"Connection: close", b"", b""])
            # Web ports only: a tunnel to any port would be plain outbound TCP (mail, SSH) from this machine.
            upstream = await self._dial(host.strip("[]"), wanted) if host and int(port) == wanted else None
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, ValueError, OSError):
            return None
        if not upstream:
            writer.write(REFUSED)
            return None
        up_reader, up_writer = upstream
        self._writers.add(up_writer)
        if method == "CONNECT":
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        else:
            up_writer.write(forward)
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))
        return up_writer


async def serve(path: Path) -> Proxy:
    proxy = Proxy()
    await proxy.start(path)
    return proxy
