"""Attach to running processes via the Debug Adapter Protocol (DAP).

When a target process calls ``debugpy.listen(port)``, it speaks DAP.  We
open a lightweight DAP client connection, send the *attach* request, and
keep the socket around so the process stays in debug mode for the
duration of the hallucifix run.
"""

from __future__ import annotations

import json
import logging
import socket
import struct
from dataclasses import dataclass, field

from hallucifix.config import ProcessConfig

log = logging.getLogger(__name__)


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True if a TCP connection can be established."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Minimal DAP client – just enough to attach and stay connected
# ---------------------------------------------------------------------------

_SEQ = 0


def _next_seq() -> int:
    global _SEQ
    _SEQ += 1
    return _SEQ


def _dap_send(sock: socket.socket, command: str, arguments: dict | None = None) -> None:
    """Send a single DAP request over the socket."""
    body: dict = {
        "seq": _next_seq(),
        "type": "request",
        "command": command,
    }
    if arguments:
        body["arguments"] = arguments
    payload = json.dumps(body).encode()
    header = f"Content-Length: {len(payload)}\r\n\r\n".encode()
    sock.sendall(header + payload)


def _dap_recv(sock: socket.socket, timeout: float = 5.0) -> dict | None:
    """Read one DAP message.  Returns the parsed body or None on timeout."""
    sock.settimeout(timeout)
    try:
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = sock.recv(1)
            if not chunk:
                return None
            header += chunk
        # Parse Content-Length
        length = 0
        for line in header.decode().splitlines():
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        if length == 0:
            return None
        data = b""
        while len(data) < length:
            chunk = sock.recv(length - len(data))
            if not chunk:
                return None
            data += chunk
        return json.loads(data)
    except (OSError, json.JSONDecodeError):
        return None


@dataclass
class DebugSession:
    """Holds an open DAP socket for one attached process."""

    process_name: str
    sock: socket.socket
    connected: bool = False

    def close(self) -> None:
        try:
            _dap_send(self.sock, "disconnect", {"terminateDebuggee": False})
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def attach(process: ProcessConfig, host: str = "127.0.0.1") -> DebugSession | None:
    """Attach to a process that is running ``debugpy.listen((host, port))``.

    Returns a :class:`DebugSession` on success, or ``None`` if the port
    isn't reachable or the handshake fails.
    """
    port = process.debugpy_port
    if not _port_open(host, port):
        log.warning(
            "debugpy port %s:%d not reachable for %s – skipping attach",
            host,
            port,
            process.name,
        )
        return None

    try:
        sock = socket.create_connection((host, port), timeout=5.0)
        _dap_send(sock, "initialize", {"adapterID": "hallucifix"})
        resp = _dap_recv(sock)
        if resp is None:
            log.warning("No DAP response from %s – skipping", process.name)
            sock.close()
            return None

        _dap_send(sock, "attach", {"justMyCode": False})
        # Read until we get a response (skip events)
        for _ in range(10):
            msg = _dap_recv(sock)
            if msg and msg.get("type") == "response":
                break

        session = DebugSession(process_name=process.name, sock=sock, connected=True)
        log.info("DAP attached to %s on %s:%d", process.name, host, port)
        return session

    except Exception:
        log.warning("Failed to DAP-attach to %s:%d – skipping", host, port, exc_info=True)
        return None
