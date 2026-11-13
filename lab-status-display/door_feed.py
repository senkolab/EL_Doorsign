"""Publish and serve the most recent door display frame over a read-only SSH session."""

import os
from pathlib import Path
from queue import Empty, Queue
import struct
import sys
from threading import Thread
import time


FRAME_LENGTH = struct.Struct("!I")
FRAME_TIME = struct.Struct("!d")
MAX_FRAME = 2000000
MAX_FRAME_AGE = 1.5
REQUEST_FRAME = b"F"


def frame_path():
    return Path("/run/user/{}/qudit-door-frame".format(os.getuid()))


class FramePublisher:
    def __init__(self, window, glib):
        self.window = window
        self.glib = glib
        self.path = frame_path()
        self.frames = Queue(maxsize=1)
        self.encoder = Thread(target=self.encode, name="door-frame-encoder", daemon=True)
        self.encoder.start()
        self.timer = glib.timeout_add(110, self.capture)

    def capture(self):
        if not self.frames.full():
            pixbuf = self.window.get_pixbuf()
            if pixbuf is not None:
                self.frames.put_nowait((time.monotonic(), pixbuf))
        return True

    def encode(self):
        temporary = self.path.with_suffix(".{}.tmp".format(os.getpid()))
        while True:
            frame = self.frames.get()
            if frame is None:
                break
            timestamp, pixbuf = frame
            try:
                success, jpeg = pixbuf.save_to_bufferv("jpeg", ["quality"], ["92"])
                if success and 0 < len(jpeg) <= MAX_FRAME:
                    temporary.write_bytes(FRAME_TIME.pack(timestamp) + jpeg)
                    temporary.replace(self.path)
            except Exception as error:
                print("Door frame encoding failed: {}".format(error), flush=True)
                break
        if temporary.exists():
            temporary.unlink()

    def close(self):
        self.glib.source_remove(self.timer)
        if self.encoder.is_alive():
            try:
                self.frames.get_nowait()
            except Empty:
                pass
            self.frames.put_nowait(None)
            self.encoder.join()
        if self.path.exists():
            self.path.unlink()


def current_jpeg(path):
    try:
        with path.open("rb") as source:
            header = source.read(FRAME_TIME.size)
            if len(header) != FRAME_TIME.size:
                return b""
            timestamp, = FRAME_TIME.unpack(header)
            if not 0 <= time.monotonic() - timestamp <= MAX_FRAME_AGE:
                return b""
            jpeg = source.read(MAX_FRAME + 1)
            return jpeg if len(jpeg) <= MAX_FRAME else b""
    except OSError:
        return b""


def serve():
    path = frame_path()
    while sys.stdin.buffer.read(1) == REQUEST_FRAME:
        jpeg = current_jpeg(path)
        try:
            sys.stdout.buffer.write(FRAME_LENGTH.pack(len(jpeg)))
            sys.stdout.buffer.write(jpeg)
            sys.stdout.buffer.flush()
        except BrokenPipeError:
            return


if __name__ == "__main__":
    serve()
