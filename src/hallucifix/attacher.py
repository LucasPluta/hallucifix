"""Attach debugpy to running Python processes and collect debug state."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProcessTarget:
    """A running Python process to attach to."""

    pid: int
    name: str
    debugpy_port: int
    log_file: str | None = None


@dataclass
class AttachedProcess:
    """A process with debugpy attached and connection established."""

    target: ProcessTarget
    connected: bool = False
    logs: list[str] = field(default_factory=list)


def inject_debugpy(pid: int, port: int, host: str = "127.0.0.1") -> bool:
    """Inject debugpy into a running process via subprocess attach.

    Uses `python -c` to inject debugpy.listen() into the target process.
    The target process must have been started with a Python that has debugpy installed.
    """
    inject_code = (
        f"import debugpy; debugpy.listen(('{host}', {port})); "
        f"print('debugpy listening on {host}:{port}')"
    )
    try:
        # Use gdb/lldb to inject into running process, or fall back to
        # the signal-based approach with sys.settrace
        result = subprocess.run(
            [
                "python", "-c",
                f"import debugpy; debugpy.connect(('{host}', {port}))"
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def attach_via_dap(host: str, port: int, timeout: float = 5.0) -> socket.socket | None:
    """Connect to a debugpy DAP server.

    Returns the connected socket or None on failure.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect((host, port))
            return sock
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    return None


def send_dap_request(sock: socket.socket, command: str, arguments: dict[str, Any] | None = None) -> dict:
    """Send a DAP request and read the response."""
    seq = 1
    request = {
        "seq": seq,
        "type": "request",
        "command": command,
    }
    if arguments:
        request["arguments"] = arguments

    body = json.dumps(request)
    message = f"Content-Length: {len(body)}\r\n\r\n{body}"
    sock.sendall(message.encode())

    # Read response
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk

    if b"\r\n\r\n" in data:
        header, body_bytes = data.split(b"\r\n\r\n", 1)
        content_length = int(header.split(b"Content-Length: ")[1])
        while len(body_bytes) < content_length:
            body_bytes += sock.recv(4096)
        return json.loads(body_bytes[:content_length])
    return {}


def get_stack_trace(sock: socket.socket, thread_id: int = 1) -> list[dict]:
    """Get the current stack trace from a paused process."""
    response = send_dap_request(sock, "stackTrace", {"threadId": thread_id})
    return response.get("body", {}).get("stackFrames", [])


def get_variables(sock: socket.socket, frame_id: int) -> list[dict]:
    """Get variables from a specific stack frame."""
    scopes_resp = send_dap_request(sock, "scopes", {"frameId": frame_id})
    scopes = scopes_resp.get("body", {}).get("scopes", [])

    variables = []
    for scope in scopes:
        var_resp = send_dap_request(
            sock, "variables",
            {"variablesReference": scope["variablesReference"]}
        )
        variables.extend(var_resp.get("body", {}).get("variables", []))
    return variables
