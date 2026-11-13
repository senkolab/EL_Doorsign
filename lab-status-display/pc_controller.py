"""Portable Windows controls for the QuDit Lab door dashboard."""

import base64
import hashlib
import hmac
import json
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Event, Thread
import tkinter as tk

import paramiko


PI_HOST = "welcome-pi.local"
PI_KEY = "SHA256:dAcXH2+ROWLkrjy/4FWcblc7zwxDLwfrI1IewuT/nCk"
BRIDGE = "python3 -B -u ~/lab-status-display/remote_control.py"
PAPER = "#f5f2e9"
SURFACE = "#fffdf7"
INK = "#172d37"
MUTED = "#526572"
EDGE = "#c9c3b3"
TEAL = "#23564d"
VIOLET = "#34254d"
FONT = "Georgia"


class LabPiHostKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, _client, _hostname, key):
        digest = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if not hmac.compare_digest(f"SHA256:{digest}", PI_KEY):
            raise paramiko.SSHException("The SSH host key does not match welcome-pi")


def ed25519_transport(*args, **kwargs):
    transport = paramiko.Transport(*args, **kwargs)
    transport.get_security_options().key_types = ("ssh-ed25519",)
    return transport


class PiSession:
    def __init__(self, host, port, user, password, events):
        self.requests = Queue()
        self.stop = Event()
        Thread(target=self.run, args=(host, port, user, password, events), daemon=True).start()

    def run(self, host, port, user, password, events):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(LabPiHostKey())
        message = "Disconnected"
        try:
            client.connect(
                host, port=port, username=user, password=password or None,
                allow_agent=not password, look_for_keys=not password,
                timeout=8, banner_timeout=8, auth_timeout=8, transport_factory=ed25519_transport,
            )
            del password
            if self.stop.is_set():
                return
            client.get_transport().set_keepalive(15)
            stdin, stdout, _stderr = client.exec_command(BRIDGE, timeout=9)

            def exchange(request):
                stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
                stdin.flush()
                line = stdout.readline(16385)
                if not line or len(line) > 16384:
                    raise ConnectionError("The Pi dashboard did not return a status")
                response = json.loads(line)
                if not isinstance(response, dict) or "state" not in response or "controls" not in response:
                    error = response.get("error") if isinstance(response, dict) else None
                    raise ConnectionError(error or "The Pi dashboard control channel is unavailable")
                return response

            events.put(("connected", exchange({"action": "get"})))
            while not self.stop.is_set():
                try:
                    action = self.requests.get(timeout=1)
                except Empty:
                    action = None
                if self.stop.is_set():
                    break
                response = exchange(action or {"action": "get"})
                events.put(("action" if action else "status", response))
        except paramiko.AuthenticationException:
            message = "SSH sign-in failed. Check the Pi username and password or SSH key."
        except (EOFError, OSError, paramiko.SSHException, ValueError) as error:
            message = f"Connection ended. {error}"
        finally:
            client.close()
            events.put(("closed", "Disconnected" if self.stop.is_set() else message))


def make_button(parent, text, action, *, background=SURFACE, foreground=INK, size=12):
    return tk.Button(
        parent, text=text, command=action, font=(FONT, size), bg=background, fg=foreground,
        activebackground=background, activeforeground=foreground, disabledforeground="#77818a",
        relief="flat", cursor="hand2", highlightthickness=1, highlightbackground=EDGE,
        padx=12, pady=7,
    )


class RemoteApp:
    def __init__(self, root):
        self.root = root
        self.events = Queue()
        self.session = None
        self.connected = False
        self.pending = False
        self.state = None
        self.controls = None
        self.paladin = {}
        self.tiles = {}
        self.ion_buttons = {}
        self.isotope_buttons = []

        root.title("QuDit Lab Remote")
        if sys.platform == "win32":
            root.iconbitmap(str(Path(__file__).with_name("qudit-lab.ico")))
        root.configure(bg=PAPER)
        root.geometry("960x650")
        root.minsize(790, 545)
        shell = tk.Frame(root, bg=PAPER, padx=20, pady=16)
        shell.pack(fill="both", expand=True)
        tk.Label(shell, text="QuDit Lab Remote", font=(FONT, 28), bg=PAPER, fg=INK, anchor="w").pack(fill="x")

        login = tk.Frame(shell, bg=SURFACE, highlightthickness=1, highlightbackground=EDGE, padx=12, pady=9)
        login.pack(fill="x", pady=(10, 0))
        login.columnconfigure(0, weight=2)
        login.columnconfigure(3, weight=2)
        self.host = tk.StringVar(value=PI_HOST)
        self.port = tk.StringVar(value="22")
        self.user = tk.StringVar(value="pi")
        self.password = tk.StringVar()
        self.entries = []
        for column, (title, variable, width, show) in enumerate((
            ("Pi hostname or IP", self.host, 23, ""), ("SSH port", self.port, 7, ""),
            ("Username", self.user, 12, ""), ("SSH password", self.password, 21, "•"),
        )):
            tk.Label(login, text=title, bg=SURFACE, fg=MUTED, font=(FONT, 10), anchor="w").grid(row=0, column=column, sticky="ew", padx=(0, 10))
            entry = tk.Entry(login, textvariable=variable, width=width, show=show, font=(FONT, 12), relief="solid", borderwidth=1, bg="#ffffff", fg=INK)
            entry.grid(row=1, column=column, sticky="ew", padx=(0, 10), ipady=4)
            self.entries.append(entry)
        self.connection_button = make_button(login, "Connect", self.connection_action, background=TEAL, foreground="white")
        self.connection_button.grid(row=0, column=4, rowspan=2, sticky="ns")
        self.feedback = tk.Label(shell, text="Disconnected", bg=PAPER, fg=MUTED, font=(FONT, 11), anchor="w", wraplength=720, justify="left")
        self.feedback.pack(fill="x", pady=(8, 8))

        self.board = tk.Frame(shell, bg=PAPER)
        self.board.pack(fill="both", expand=True)
        tk.Label(self.board, text="Connect to the Pi to load the door sign controls.", bg=PAPER, fg=MUTED, font=(FONT, 14)).pack(expand=True)
        self.warning = tk.Label(shell, bg="#8f202b", fg="#fff7ee", font=(FONT, 12, "bold"), pady=9)
        tk.Label(shell, text="These controls report status on the door display.", bg=PAPER, fg=MUTED, font=(FONT, 10), anchor="w").pack(fill="x", pady=(8, 0))

        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(50, self.read_events)
        self.entries[-1].focus_set()

    def connection_action(self):
        if self.session is not None:
            self.session.stop.set()
            self.connected = False
            self.pending = False
            self.state = None
            self.connection_button.configure(text="Disconnecting…", state="disabled")
            self.feedback.configure(text="Disconnecting…", fg=MUTED)
            self.render()
            return

        host, user = self.host.get().strip(), self.user.get().strip()
        try:
            port = int(self.port.get())
            if not host or not user or not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.feedback.configure(text="Enter a hostname, username, and SSH port from 1 to 65535.", fg="#8f202b")
            return
        password = self.password.get()
        self.password.set("")
        self.set_login_enabled(False)
        self.connection_button.configure(text="Cancel", state="normal")
        self.feedback.configure(text=f"Connecting to {host}…", fg=MUTED)
        self.session = PiSession(host, port, user, password, self.events)

    def set_login_enabled(self, enabled):
        for entry in self.entries:
            entry.configure(state="normal" if enabled else "disabled")

    def read_events(self):
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except Empty:
                break
            if kind == "closed":
                self.session = None
                self.connected = False
                self.pending = False
                self.state = None
                self.paladin = {}
                self.set_login_enabled(True)
                self.connection_button.configure(text="Connect", state="normal")
                self.feedback.configure(text=payload, fg=MUTED if payload == "Disconnected" else "#8f202b")
                self.render()
                continue
            if self.session is None or self.session.stop.is_set():
                continue
            if kind == "connected":
                self.connected = True
                self.connection_button.configure(text="Disconnect", state="normal")
                self.feedback.configure(text=f"Connected to {self.host.get()}", fg=TEAL)
            if self.controls != payload["controls"]:
                self.controls = payload["controls"]
                self.build_board()
            self.state = payload["state"]
            self.paladin = payload.get("paladin", {})
            if kind == "action":
                self.pending = False
                success = payload["ok"]
                self.feedback.configure(
                    text=f"Connected to {self.host.get()}" if success else payload.get("error", "The status could not be updated"),
                    fg=TEAL if success else "#8f202b",
                )
            self.render()
        self.root.after(50, self.read_events)

    def build_board(self):
        for child in self.board.winfo_children():
            child.destroy()
        self.tiles.clear()
        self.ion_buttons.clear()
        self.isotope_buttons.clear()
        self.board.rowconfigure(0, weight=1)
        for column, weight in enumerate((2, 5, 2)):
            self.board.columnconfigure(column, weight=weight, uniform="board")

        left = tk.Frame(self.board, bg=PAPER)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        center = tk.Frame(self.board, bg=PAPER)
        center.grid(row=0, column=1, sticky="nsew", padx=6)
        right = tk.Frame(self.board, bg=PAPER)
        right.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        for key in self.controls["lasers"]:
            self.make_tile(left, key)
        self.make_tile(right, "lock")
        lock_status = self.controls.get("lock_status")
        if lock_status:
            self.make_tile(right, lock_status)
        self.make_tile(right, "class4")

        ion = tk.Frame(center, bg=VIOLET, padx=13, pady=12)
        ion.pack(fill="both", expand=True, pady=(0, 6))
        ion.columnconfigure(0, weight=1)
        ion.rowconfigure(0, weight=1)
        self.ion_title = tk.Label(ion, font=(FONT, 22), bg=VIOLET, fg="#fff8ff", anchor="w")
        self.ion_title.grid(row=0, column=0, sticky="sew")
        self.isotope = tk.Label(ion, font=(FONT, 16), bg=VIOLET, fg="#e5ccff", anchor="w")
        self.isotope.grid(row=1, column=0, sticky="ew", pady=(2, 8))
        self.ion_actions = tk.Frame(ion, bg=VIOLET)
        self.ion_actions.grid(row=2, column=0, sticky="ew")
        self.isotope_actions = tk.Frame(ion, bg=VIOLET)
        for frame in (self.ion_actions, self.isotope_actions):
            for column in range(3):
                frame.columnconfigure(column, weight=1, uniform="ion")
        for index, mode in enumerate(("empty", "trapping", "trapped")):
            action = self.show_isotopes if mode == "trapped" else lambda mode=mode: self.set_ion(mode)
            button = make_button(self.ion_actions, self.controls["ion_states"][mode], action, size=11)
            button.grid(row=0, column=index, sticky="ew", padx=(0, 4))
            self.ion_buttons[mode] = button
        for index, (key, title) in enumerate(self.controls["species"].items()):
            button = make_button(self.isotope_actions, title, lambda key=key: self.set_ion("trapped", key), size=11)
            button.grid(row=0, column=index, sticky="ew", padx=(0, 4))
            self.isotope_buttons.append(button)
        back = make_button(self.isotope_actions, "Back", self.hide_isotopes, size=11)
        back.grid(row=0, column=2, sticky="ew")
        self.isotope_buttons.append(back)
        self.make_tile(center, "experiment")

    def make_tile(self, parent, key):
        tile = make_button(parent, "", lambda: self.toggle(key), size=16)
        tile.pack(fill="both", expand=True, pady=(0, 6))
        self.tiles[key] = tile

    def show_isotopes(self):
        self.ion_actions.grid_remove()
        self.isotope_actions.grid(row=2, column=0, sticky="ew")

    def hide_isotopes(self):
        self.isotope_actions.grid_remove()
        self.ion_actions.grid()

    def toggle(self, key):
        value = self.state[key]
        self.send({"action": "set_field", "key": key, "expected": value, "value": not value})

    def set_ion(self, mode, species=None):
        self.hide_isotopes()
        self.send({"action": "set_ion", "state": mode, "species": species, "expected": [self.state["ion"], self.state["species"]]})

    def send(self, request):
        if self.connected and not self.pending:
            self.pending = True
            self.session.requests.put(request)
            self.render()

    def render(self):
        if not self.controls:
            return
        state = self.state or {}
        enabled = "normal" if self.connected and not self.pending else "disabled"
        lock_status = self.controls.get("lock_status")
        automatic = self.controls.get("automatic", ())
        simulated = self.paladin.get("simulated_shutter")
        for key, tile in self.tiles.items():
            title, on, off = self.controls["fields"][key]
            value = state.get(key)
            status = "—" if not self.state else "UNKNOWN" if value is None else on if value else off
            if value and key in self.controls["locked"]:
                status = f"{status}  ·  LOCKED"
            if key == "class4" and simulated is not None:
                status += "\nSIM OPEN" if simulated else "\nSIM CLOSED"
            color = self.controls["colors"].get(key, (TEAL,))[0]
            background, foreground = (color, "#fffdf7") if value else (SURFACE, color)
            read_only = key in automatic or (key == lock_status and state.get("lock") is not True)
            tile.configure(
                text=f"{title}\n{status}", bg=background, fg=foreground,
                activebackground=background, activeforeground=foreground,
                disabledforeground=foreground if key in automatic and self.connected else MUTED,
                cursor="arrow" if read_only else "hand2",
                state="disabled" if read_only else enabled,
            )
        ion = state.get("ion", "unknown")
        self.ion_title.configure(text=self.controls["ion_states"][ion])
        isotope = {"137": "¹³⁷Ba⁺", "138": "¹³⁸Ba⁺"}.get(state.get("species"), "")
        self.isotope.configure(text=isotope if ion == "trapped" else "Ablation pulse" if ion == "trapping" else "")
        for mode, button in self.ion_buttons.items():
            color = "#6e4d9b" if ion == mode else SURFACE
            foreground = "#fff9ff" if ion == mode else VIOLET
            button.configure(state=enabled, bg=color, fg=foreground, activebackground=color, activeforeground=foreground)
        for button in self.isotope_buttons:
            button.configure(state=enabled)

        if self.state and state.get("class4") is not False:
            if self.paladin.get("automatic"):
                text = "DANGER · 532 nm shutter open" if state["class4"] else "532 nm shutter status unknown"
            else:
                text = "DANGER · 532 nm Class 4 laser on" if state["class4"] else "532 nm status unknown"
            self.warning.configure(text=text)
            self.warning.pack(fill="x", before=self.board)
        else:
            self.warning.pack_forget()

    def close(self):
        if self.session is not None:
            self.session.stop.set()
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    RemoteApp(window)
    window.mainloop()
