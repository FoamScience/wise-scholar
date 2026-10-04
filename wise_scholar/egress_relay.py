"""Runs inside the sandbox, in front of a command the learner allowed: listens on the sandbox's own loopback as an
HTTP proxy and hands every connection to the server's proxy socket, which decides where it may go.

usage: egress_relay.py SOCKET COMMAND [ARG...]"""

import asyncio
import os
import sys

PORT = 3128


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


async def relay(reader, writer):
    try:
        up_reader, up_writer = await asyncio.open_unix_connection(sys.argv[1])
    except OSError:
        writer.close()
        return
    await asyncio.gather(pipe(reader, up_writer), pipe(up_reader, writer))


async def main() -> int:
    await asyncio.start_server(relay, "127.0.0.1", PORT)
    proxy = f"http://127.0.0.1:{PORT}"
    names = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
    env = {**os.environ, **{name: proxy for name in names}, **{name.lower(): proxy for name in names}}
    command = await asyncio.create_subprocess_exec(*sys.argv[2:], env=env)
    code = await command.wait()
    # Ended by a signal: the same exit code a shell would report.
    return 128 - code if code < 0 else code


sys.exit(asyncio.run(main()))
