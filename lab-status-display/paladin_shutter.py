"""Accept one shutter reading over restricted SSH and expire it locally."""

import os
from pathlib import Path
import sys
import tempfile
import time


MAX_AGE = 8
READINGS = {"open": True, "closed": False, "unknown": None}
ENABLE_FILE = Path(__file__).with_name(".paladin-enabled")


def reading_path(simulated=False):
    name = "qudit-paladin-simulator" if simulated else "qudit-paladin-shutter"
    return Path(f"/run/user/{os.getuid()}") / name


def record(reading, *, simulated=False):
    if reading not in READINGS:
        raise ValueError("Invalid shutter reading")
    path = reading_path(simulated)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(f"{time.monotonic():.9f} {reading}\n")
            stream.close()
            temporary.replace(path)
            if not simulated and reading != "unknown":
                ENABLE_FILE.touch(mode=0o600, exist_ok=True)
        finally:
            temporary.unlink(missing_ok=True)


def read_shutter(*, simulated=False):
    try:
        timestamp, reading = reading_path(simulated).read_text(encoding="ascii").split()
        if 0 <= time.monotonic() - float(timestamp) < MAX_AGE:
            return READINGS.get(reading)
    except (OSError, ValueError):
        pass
    return None


if __name__ == "__main__":
    try:
        payload = sys.stdin.buffer.readline(16)
        if not payload.endswith(b"\n"):
            raise ValueError("Invalid shutter message")
        message = payload.rstrip(b"\r\n").decode("ascii")
        if message != "probe":
            simulated = message.startswith("sim-")
            if not simulated and "--simulator-only" in sys.argv[1:]:
                raise ValueError("This SSH key accepts simulator readings only")
            record(message.removeprefix("sim-"), simulated=simulated)
    except (OSError, ValueError) as error:
        sys.exit(str(error))
    print("OK", flush=True)
