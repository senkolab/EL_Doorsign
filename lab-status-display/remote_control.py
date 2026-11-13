"""Bridge SSH standard input/output to the Pi dashboard's private control socket."""

from concurrent.futures import Future, TimeoutError
import json
import os
from pathlib import Path
import socket
from socketserver import StreamRequestHandler, ThreadingUnixStreamServer
import sys
from threading import Thread


MAX_REQUEST = 4096
MAX_REPLY = 16384
SOCKET_TIMEOUT = 8


def socket_path():
    return Path(f"/run/user/{os.getuid()}/qudit-lab-control.sock")


def encode_message(payload):
    return json.dumps(payload, separators=(",", ":")).encode() + b"\n"


def dashboard_reply(request, snapshot, set_field, set_ion):
    current = snapshot()
    controls = current["controls"]
    state = current["state"]
    action = request.get("action")

    def error(message):
        return {"ok": False, "error": message, **current}

    if action == "get":
        return {"ok": True, **current}

    if action == "set_field":
        key = request.get("key")
        value = request.get("value")
        if not isinstance(key, str) or key not in controls["fields"] or type(value) is not bool:
            return error("Invalid dashboard status")
        if key in controls.get("automatic", ()):
            source = "the Paladin controller" if key == "class4" else "the wavemeter"
            return error(f"{controls['fields'][key][0]} is updated by {source}.")
        if "expected" not in request or request["expected"] is not state[key]:
            return error("This tile changed on the Pi. Review its status and try again.")
        if key == controls.get("lock_status") and state["lock"] is not True:
            return error("Turn on the 1762 nm tile before setting its lock status.")
        set_field(key, value)
    elif action == "set_ion":
        target = request.get("state")
        isotope = request.get("species")
        if target not in ("empty", "trapping", "trapped"):
            return error("Invalid ion state")
        if target == "trapped" and (not isinstance(isotope, str) or isotope not in controls["species"]):
            return error("Choose an isotope for Ion trapped")
        if target != "trapped" and isotope is not None:
            return error("Isotopes apply to Ion trapped")
        if request.get("expected") != [state["ion"], state["species"]]:
            return error("The ion state changed on the Pi. Review it and try again.")
        set_ion(target, isotope)
    else:
        return error("Unknown dashboard action")

    return {"ok": True, **snapshot()}


class ControlRequestHandler(StreamRequestHandler):
    timeout = SOCKET_TIMEOUT

    def handle(self):
        try:
            raw = self.rfile.readline(MAX_REQUEST + 1)
            if not raw.endswith(b"\n") or len(raw) > MAX_REQUEST:
                raise ValueError
            request = json.loads(raw)
            if not isinstance(request, dict):
                raise ValueError
        except (ValueError, OSError):
            response = {"ok": False, "error": "Invalid dashboard request"}
        else:
            response = self.server.dispatch_request(request)
        try:
            self.wfile.write(encode_message(response))
        except OSError:
            pass


class RemoteControlServer(ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, on_request, dispatch):
        self.on_request = on_request
        self.dispatch = dispatch
        self.path = socket_path()
        if self.path.is_socket() and not self.path.is_symlink():
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.5)
                try:
                    probe.connect(str(self.path))
                except ConnectionRefusedError:
                    self.path.unlink()
                else:
                    raise OSError("A dashboard already owns the control socket")
        super().__init__(str(self.path), ControlRequestHandler, bind_and_activate=False)
        try:
            self.server_bind()
            self.path.chmod(0o600)
            self.server_activate()
        except OSError:
            self.server_close()
            raise

    def start(self):
        Thread(target=self.serve_forever, name="dashboard-control", daemon=True).start()

    def close(self):
        self.shutdown()
        self.server_close()
        self.path.unlink(missing_ok=True)

    def dispatch_request(self, request):
        result = Future()

        def apply():
            if result.set_running_or_notify_cancel():
                try:
                    result.set_result(self.on_request(request))
                except Exception as error:
                    result.set_exception(error)
            return False

        self.dispatch(apply)
        try:
            try:
                return result.result(timeout=4)
            except TimeoutError:
                if result.cancel():
                    return {"ok": False, "error": "The dashboard is busy. Try again."}
                return result.result()
        except Exception as error:
            print(f"Remote dashboard request failed: {error}", file=sys.stderr, flush=True)
            return {"ok": False, "error": "The dashboard could not apply the request"}


def bridge():
    """Forward one small JSON request per line over a single SSH channel."""
    while raw := sys.stdin.buffer.readline(MAX_REQUEST + 1):
        if not raw.endswith(b"\n") or len(raw) > MAX_REQUEST:
            sys.stdout.buffer.write(encode_message({"ok": False, "error": "Request too large"}))
            sys.stdout.buffer.flush()
            return
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(SOCKET_TIMEOUT)
                connection.connect(str(socket_path()))
                connection.sendall(raw)
                with connection.makefile("rb") as stream:
                    response = stream.readline(MAX_REPLY + 1)
            if not response.endswith(b"\n") or len(response) > MAX_REPLY:
                raise ConnectionError
        except OSError:
            response = encode_message({"ok": False, "error": "The Pi dashboard control channel is unavailable"})
        sys.stdout.buffer.write(response)
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    bridge()
