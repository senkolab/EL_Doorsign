"""Fullscreen viewer for the QuDit door feed, compatible with Python 3.5."""

import os
from pathlib import Path
import select
import subprocess
from threading import Event, Thread
import time

import gi

from door_feed import FRAME_LENGTH, MAX_FRAME, REQUEST_FRAME

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk


STALE_AFTER = 1.8
FRAME_INTERVAL = 0.11
SSH_DIR = Path.home() / ".ssh"
SSH = [
    "ssh", "-F", "/dev/null", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
    "-o", "StrictHostKeyChecking=yes", "-o", "CheckHostIP=no", "-o", "IdentitiesOnly=yes",
    "-o", "HostKeyAlgorithms=ssh-ed25519",
    "-o", "GlobalKnownHostsFile=/dev/null", "-o", "UserKnownHostsFile=" + str(SSH_DIR / "qudit-door-known-hosts"),
    "-i", str(SSH_DIR / "qudit-door-relay"), "pi@welcome-pi.local", "door-feed",
]


def read_exact(pipe, length, deadline):
    data = bytearray()
    while len(data) < length:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([pipe], [], [], remaining)[0]:
            raise TimeoutError("door feed stopped responding")
        part = os.read(pipe.fileno(), length - len(data))
        if not part:
            raise ConnectionError("door feed closed")
        data.extend(part)
    return bytes(data)


class DoorFeed:
    def __init__(self):
        self.latest = (0, b"")
        self.stop = Event()

    def watch(self):
        last_error = None
        while not self.stop.is_set():
            try:
                self.connect()
            except (OSError, ValueError) as error:
                if str(error) != last_error:
                    print("Door feed: {}".format(error), flush=True)
                    last_error = str(error)
            self.latest = (0, b"")
            self.stop.wait(1)

    def connect(self):
        ssh = subprocess.Popen(SSH, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        try:
            deadline = time.monotonic() + 5
            while not self.stop.is_set():
                started = time.monotonic()
                ssh.stdin.write(REQUEST_FRAME)
                length, = FRAME_LENGTH.unpack(read_exact(ssh.stdout, FRAME_LENGTH.size, deadline))
                if length > MAX_FRAME:
                    raise ValueError("invalid door frame size")
                jpeg = read_exact(ssh.stdout, length, deadline)
                received = time.monotonic()
                self.latest = (received, jpeg) if received - started < STALE_AFTER else (0, b"")
                self.stop.wait(max(0, FRAME_INTERVAL - (received - started)))
                deadline = time.monotonic() + STALE_AFTER
        finally:
            ssh.kill()
            ssh.wait()
            ssh.stdin.close()
            ssh.stdout.close()


class DoorDisplay:
    def __init__(self, feed):
        self.feed = feed
        self.last_frame = 0
        self.last_jpeg = b""
        self.pixbuf = None
        self.rendered = None

        self.window = Gtk.Window(title="QuDit Lab door display")
        self.window.set_decorated(False)
        self.window.set_keep_above(True)
        self.window.connect("realize", self.hide_pointer)
        self.window.connect("destroy", Gtk.main_quit)
        self.window.get_style_context().add_class("door-viewer")
        view = Gtk.Overlay()
        self.window.add(view)
        self.canvas = Gtk.Layout()
        self.canvas.get_style_context().add_class("door-viewer")
        self.image = Gtk.Image()
        self.canvas.put(self.image, 0, 0)
        self.canvas.connect("size-allocate", lambda *_: self.fit())
        view.add(self.canvas)

        self.offline = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.offline.set_halign(Gtk.Align.CENTER)
        self.offline.set_valign(Gtk.Align.CENTER)
        self.offline.get_style_context().add_class("door-offline")
        for content, style in (("DO NOT ENTER", "warning"), ("532 nm laser status unavailable", "status"),
                               ("Contact the lab operator before entering.", "detail")):
            label = Gtk.Label(label=content)
            label.set_line_wrap(True)
            label.get_style_context().add_class(style)
            self.offline.pack_start(label, False, False, 0)
        view.add_overlay(self.offline)

        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .door-viewer { background: #1a1513; }
            .door-offline { color: #fff3d7; padding: 24px; }
            .door-offline .warning { color: #ffcd54; font-size: 40px; font-weight: bold; }
            .door-offline .status { font-size: 20px; font-weight: bold; }
            .door-offline .detail { font-size: 16px; }
        """)
        Gtk.StyleContext.add_provider_for_screen(self.window.get_screen(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window.fullscreen()
        self.window.show_all()
        self.show_offline()

    @staticmethod
    def hide_pointer(window):
        cursor = Gdk.Cursor.new_for_display(window.get_display(), Gdk.CursorType.BLANK_CURSOR)
        window.get_window().set_cursor(cursor)

    def show_offline(self):
        self.offline.show()
        self.pixbuf = None
        self.last_jpeg = b""
        self.rendered = None
        self.image.clear()

    def refresh(self):
        received, jpeg = self.feed.latest
        if not jpeg or time.monotonic() - received >= STALE_AFTER:
            if self.pixbuf is not None:
                self.show_offline()
        elif jpeg != self.last_jpeg:
            self.last_frame = received
            self.last_jpeg = jpeg
            try:
                loader = GdkPixbuf.PixbufLoader.new_with_type("jpeg")
                loader.write(jpeg)
                loader.close()
                self.pixbuf = loader.get_pixbuf()
            except GLib.Error:
                self.show_offline()
            else:
                self.offline.hide()
                self.fit()
        return True

    def fit(self):
        if self.pixbuf is None:
            return
        width, height = self.canvas.get_allocated_width(), self.canvas.get_allocated_height()
        if min(width, height) < 2:
            return
        frame = self.last_frame, width, height
        if frame == self.rendered:
            return
        self.rendered = frame
        original_width, original_height = self.pixbuf.get_width(), self.pixbuf.get_height()
        scale = min(width / original_width, height / original_height)
        scaled_width, scaled_height = round(original_width * scale), round(original_height * scale)
        self.canvas.move(self.image, (width - scaled_width) // 2, (height - scaled_height) // 2)
        if scale == 1:
            self.image.set_from_pixbuf(self.pixbuf)
        else:
            scaled = self.pixbuf.scale_simple(scaled_width, scaled_height, GdkPixbuf.InterpType.BILINEAR)
            self.image.set_from_pixbuf(scaled)


def main():
    feed = DoorFeed()
    viewer = DoorDisplay(feed)
    reader = Thread(target=feed.watch, name="door-feed", daemon=True)
    reader.start()
    GLib.timeout_add(85, viewer.refresh)
    print("QuDit door viewer ready", flush=True)
    try:
        Gtk.main()
    finally:
        feed.stop.set()
        reader.join(6)


if __name__ == "__main__":
    main()
