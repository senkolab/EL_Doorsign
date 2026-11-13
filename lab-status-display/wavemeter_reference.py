"""Read the HighFinesse regulation references on the Windows wavemeter VM."""

import argparse
import ctypes
import json
import math
import sys
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, HTTPServer

DEVIATION_UNIT = 1041
DEVIATION_CHANNEL = 1063
FREQUENCY_UNIT = 2
REFERENCE_PORT = 8081
UNITS = {0: "nm (vacuum)", 1: "nm (air)", 2: "THz", 3: "cm^-1", 4: "eV"}


class RegulationReader:
    def __init__(self, dll):
        integer = ctypes.c_long
        real = ctypes.c_double
        self.get_course = dll.GetPIDCourseNum
        self.get_course.argtypes = [integer, ctypes.POINTER(ctypes.c_char)]
        self.get_course.restype = integer
        self.get_setting = dll.GetPIDSetting
        self.get_setting.argtypes = [integer, integer, ctypes.POINTER(integer), ctypes.POINTER(real)]
        self.get_setting.restype = integer
        self.get_mode = dll.GetDeviationMode
        self.get_mode.argtypes = [ctypes.c_bool]
        self.get_mode.restype = ctypes.c_bool
        self.convert = dll.ConvertUnit
        self.convert.argtypes = [real, integer, integer]
        self.convert.restype = real

    def setting(self, key, port):
        integer, real = ctypes.c_long(), ctypes.c_double()
        status = self.get_setting(key, port, ctypes.byref(integer), ctypes.byref(real))
        if status != 1:
            raise RuntimeError(f"PID setting {key} on port {port} returned API code {status}")
        return integer.value

    def references(self):
        channels = {}
        available_ports = 0
        last_error = None
        for port in range(1, 9):
            try:
                channel = self.setting(DEVIATION_CHANNEL, port)
            except RuntimeError as error:
                # A WS/7 can have fewer regulation outputs than optical inputs.
                last_error = error
                continue
            available_ports += 1
            if channel <= 0:
                continue
            reference = {"port": port, "course": None, "unit": None, "reference_thz": None}
            try:
                unit = self.setting(DEVIATION_UNIT, port)
                reference["unit"] = UNITS.get(unit)
                buffer = ctypes.create_string_buffer(1024)
                status = self.get_course(port, buffer)
                if status != 0:
                    raise RuntimeError(f"GetPIDCourseNum returned API code {status}")
                course = buffer.value.decode("ascii", errors="replace").strip()
                reference["course"] = course
                reference["reference_thz"] = self.constant_frequency(course, unit)
            except RuntimeError as error:
                reference["error"] = str(error)
            channels[str(channel)] = reference
        if not available_ports:
            raise RuntimeError(f"No regulation ports could be read ({last_error})")
        return {"regulation_active": self.get_mode(False), "channels": channels}

    def constant_frequency(self, course, unit):
        if unit not in UNITS:
            return None
        try:
            value = float(course.replace(",", "."))
        except ValueError:
            # HighFinesse also accepts time-dependent formulas in this field.
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        frequency = value if unit == FREQUENCY_UNIT else self.convert(value, unit, FREQUENCY_UNIT)
        return frequency if math.isfinite(frequency) and frequency > 0 else None


@lru_cache(maxsize=1)
def local_reader():
    return RegulationReader(ctypes.WinDLL("wlmData.dll"))


def serve_references(handler):
    """Handle the regulation reference route in the IonControl HTTP server."""
    if handler.path != "/references":
        handler.send_error(400, "Use /references without query parameters")
        return
    try:
        data = local_reader().references()
    except (AttributeError, OSError, RuntimeError) as error:
        handler.log_error("%s", error)
        handler.send_error(503, "Regulation references unavailable")
        return
    body = json.dumps(data, allow_nan=False).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class ReferenceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.partition("?")[0] == "/references":
            serve_references(self)
        else:
            self.send_error(404)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", metavar="VM_IP", help="also serve the readout at /references")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Run this on the Windows PC running the HighFinesse software.")
    try:
        print(json.dumps(local_reader().references(), indent=2), flush=True)
        if args.listen:
            with HTTPServer((args.listen, REFERENCE_PORT), ReferenceHandler) as server:
                print(f"Serving read-only references on {args.listen}:{REFERENCE_PORT}", flush=True)
                server.serve_forever()
    except KeyboardInterrupt:
        return
    except (AttributeError, OSError, RuntimeError) as error:
        parser.exit(1, f"Wavemeter reference read failed: {error}\n")


if __name__ == "__main__":
    main()
