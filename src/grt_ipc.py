"""
grt_ipc.py - GRT plugin IPC client.

GRT launches the plugin with `--ipcport <port>` (TCP on 127.0.0.1) or, on Linux,
`--ipcfile <path>` (a Unix socket file), as GRT's plugin API documents.
Messages are JSON objects sent over the socket. The format observed in the
reference plugins is a single JSON object per command, e.g.:

    {"Load_File": {"filepath": "C:\\path\\to\\out.grtload"}}
    {"Get_TabOnTop": null}
    {"Get_Tab": {"tabhandle": "..."}}

Inbound events arrive the same way and are dispatched by their key, e.g.
    {"Event_MenuAction": {...}}
    {"Event_ToolbarAction": {...}}
    {"Event_ColorPresetChange": {...}}
    {"Event_WindowClosed": {...}}

Multiple JSON objects may be concatenated on the wire ("}{"); this client
splits them with a brace-depth scanner rather than assuming framing.

This module is intentionally dependency-free (stdlib sockets + json) so it
freezes cleanly with PyInstaller.
"""

import json
import socket
import threading


def parse_connect_args(argv):
    """Where to connect: ("tcp", port) from `--ipcport`, ("unix", path) from `--ipcfile`, or None."""
    for i, a in enumerate(argv):
        for flag in ("--ipcport", "--ipcfile"):
            if a == flag:
                value = argv[i + 1] if i + 1 < len(argv) else None
            elif a.startswith(flag + "="):
                value = a.split("=", 1)[1]
            else:
                continue
            if not value:
                return None
            if flag == "--ipcfile":
                return ("unix", value)
            try:
                return ("tcp", int(value))
            except ValueError:
                return None
    return None


def _split_json_objects(buf):
    """Yield (obj_text, rest) splitting concatenated top-level JSON objects.

    Returns a list of complete object strings plus the trailing remainder
    that has not yet been fully received.
    """
    objs = []
    depth = 0
    in_str = False
    esc = False
    start = None
    i = 0
    for i, ch in enumerate(buf):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                objs.append(buf[start:i + 1])
                start = None
    if objs:
        last_end = buf.rfind(objs[-1]) + len(objs[-1])
        remainder = buf[last_end:]
    else:
        remainder = buf
    return objs, remainder


class GRTClient:
    """Minimal client for the GRT plugin socket protocol."""

    def __init__(self, address, on_event=None):
        self.address = address   # from parse_connect_args
        self.on_event = on_event
        self.sock = None
        self._rx_thread = None
        self._running = False
        self._buf = ""
        self.connected = False

    def connect(self, timeout=5.0):
        kind, where = self.address
        if kind == "unix":
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            try:
                self.sock.connect(where)
            except OSError:
                self.sock.close()
                self.sock = None
                raise
        else:
            self.sock = socket.create_connection(("127.0.0.1", where), timeout=timeout)
        self.sock.settimeout(None)
        self.connected = True
        self._running = True
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()
        return True

    def close(self):
        self._running = False
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
        self.connected = False

    def _send_obj(self, obj):
        if not self.sock:
            raise RuntimeError("Not connected to GRT")
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        self.sock.sendall(data)

    def send_command(self, name, payload=None):
        """Send {name: payload}. payload may be None -> {name: null}."""
        self._send_obj({name: payload})

    def load_file(self, filepath):
        """Ask GRT to open a .grtload file (the documented Load_File command).

        GRT's Load_File expects forward slashes in the path (per the plugin-api
        spec example: "C:/loads/....grtload"), so normalize separators.
        """
        normalized = filepath.replace("\\", "/")
        self.send_command("Load_File", {"filepath": normalized})

    def get_tab_on_top(self):
        self.send_command("Get_TabOnTop", None)

    def get_tab(self, tabhandle):
        self.send_command("Get_Tab", {"tabhandle": tabhandle})

    def _rx_loop(self):
        while self._running:
            try:
                chunk = self.sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            self._buf += chunk.decode("utf-8", errors="replace")
            objs, self._buf = _split_json_objects(self._buf)
            for text in objs:
                try:
                    msg = json.loads(text)
                except json.JSONDecodeError:
                    continue
                self._dispatch(msg)
        self.connected = False
        if self.on_event:
            self.on_event("Event_Disconnected", {})

    def _dispatch(self, msg):
        if not isinstance(msg, dict):
            return
        for name, payload in msg.items():
            if self.on_event:
                self.on_event(name, payload)
