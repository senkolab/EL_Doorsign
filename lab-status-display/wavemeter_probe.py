"""Measure HighFinesse WS/7 frequency stability over HTTP or from the local DLL."""

import argparse
import ctypes
import http.client
import json
import math
import statistics
import sys
import time


CHANNELS = {3: 554, 4: 650, 7: 493, 8: 614}
# Wavelength event identifiers from the HighFinesse WS/7 API.
WAVELENGTH_EVENTS = {90: 3, 91: 4, 94: 7, 95: 8}
C_NM_THz = 299_792.458
NOTIFICATION = 1
INSTALL_WAIT_EVENT = 2
REMOVE_WAIT_EVENT = 3
EVENT_TIMEOUT_MS = 250
HTTP_PORT = 8080
HTTP_POLL_SECONDS = 1.0


def bind(library, name, *argument_types):
    function = getattr(library, name)
    function.argtypes = argument_types
    function.restype = ctypes.c_long
    return function


def collect(library, seconds):
    integer = ctypes.c_long
    real = ctypes.c_double
    instantiate = bind(library, "Instantiate", integer, integer, integer, integer)
    wait = bind(library, "WaitForWLMEvent", ctypes.POINTER(integer),
                ctypes.POINTER(integer), ctypes.POINTER(real))
    if instantiate(NOTIFICATION, INSTALL_WAIT_EVENT, EVENT_TIMEOUT_MS, 0) <= 0:
        raise RuntimeError("Could not subscribe to measurements. Check that HighFinesse is running.")

    readings = {channel: [] for channel in CHANNELS}
    invalid = dict.fromkeys(CHANNELS, 0)
    last_stamp = {}
    event, timestamp, wavelength = integer(), integer(), real()
    end = time.monotonic() + seconds
    try:
        while time.monotonic() < end:
            result = wait(ctypes.byref(event), ctypes.byref(timestamp), ctypes.byref(wavelength))
            if result == -1:
                continue
            if result not in (1, 2):
                raise RuntimeError(f"HighFinesse event stream stopped (API code {result}).")
            channel = WAVELENGTH_EVENTS.get(event.value)
            if channel is None or last_stamp.get(channel) == timestamp.value:
                continue
            last_stamp[channel] = timestamp.value
            if math.isfinite(wavelength.value) and wavelength.value > 0:
                readings[channel].append(C_NM_THz / wavelength.value)
            else:
                invalid[channel] += 1
    finally:
        instantiate(NOTIFICATION, REMOVE_WAIT_EVENT, 0, 0)
    return readings, invalid


def read_response(host, port, path, limit):
    connection = http.client.HTTPConnection(host, port, timeout=2.0)
    try:
        connection.request("GET", path)
        with connection.getresponse() as response:
            if response.status != 200:
                raise OSError(f"HTTP {response.status}")
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("unexpected response length")
        return raw
    finally:
        connection.close()


def read_frequency(host, channel):
    return float(read_response(host, HTTP_PORT, f"/?channel={channel}", 128))


def read_references(host, port=HTTP_PORT):
    return json.loads(read_response(host, port, "/references", 16_384))


def compare_references(host, port):
    payload = read_references(host, port)
    print(f"HighFinesse regulation: {'active' if payload['regulation_active'] else 'inactive'}")
    for channel, laser in sorted(CHANNELS.items(), key=lambda item: item[1]):
        reference = payload["channels"].get(str(channel))
        label = f"{laser} nm (CH {channel})"
        if reference is None:
            print(f"{label}: no mapped regulation reference")
            continue
        label += f", PID port {reference['port']}"
        target = reference["reference_thz"]
        if target is None:
            print(f"{label}: {reference.get('error', 'no constant reference')}; "
                  f"course {reference['course']!r}, unit {reference['unit']}")
            continue
        try:
            measured = read_frequency(host, channel)
        except (OSError, http.client.HTTPException, ValueError) as error:
            print(f"{label}: reference {target:.9f} THz, measurement unavailable ({error})")
            continue
        if not math.isfinite(measured) or measured <= 0:
            print(f"{label}: reference {target:.9f} THz, no valid measurement")
            continue
        offset = (measured - target) * 1e6
        print(f"{label}: reference {target:.9f} THz, measured {measured:.9f} THz, "
              f"offset {offset:+.3f} MHz")


def poll_server(host, seconds):
    readings = {channel: [] for channel in CHANNELS}
    invalid = dict.fromkeys(CHANNELS, 0)
    failures = dict.fromkeys(CHANNELS, 0)
    last_error = None
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        next_poll = time.monotonic() + HTTP_POLL_SECONDS
        for channel in CHANNELS:
            try:
                frequency = read_frequency(host, channel)
            except (OSError, http.client.HTTPException, ValueError) as error:
                failures[channel] += 1
                last_error = error
                continue
            if math.isfinite(frequency) and frequency > 0:
                readings[channel].append(frequency)
            else:
                invalid[channel] += 1
        time.sleep(max(0, min(next_poll, end) - time.monotonic()))
    return readings, invalid, failures, last_error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=30, help="capture duration (default 30)")
    parser.add_argument("--server", metavar="HOST", help="poll the IonControl wavemeter server on port 8080")
    parser.add_argument("--references", action="store_true", help="compare current frequencies with the regulation references")
    parser.add_argument("--reference-port", type=int, default=HTTP_PORT,
                        help="HTTP port for /references (default 8080)")
    args = parser.parse_args()
    if args.seconds < 1:
        parser.error("--seconds must be at least 1")
    if args.references:
        if not args.server:
            parser.error("--references requires --server")
        try:
            compare_references(args.server, args.reference_port)
        except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError) as error:
            parser.exit(1, f"Could not read references from {args.server}:{args.reference_port}: {error}\n")
        return
    if args.server:
        print(f"Polling {args.server}:{HTTP_PORT} for {args.seconds} seconds...", flush=True)
        readings, invalid, failures, last_error = poll_server(args.server, args.seconds)
        if last_error is not None:
            print(f"Last request error: {last_error}", file=sys.stderr)
    else:
        if sys.platform != "win32":
            parser.error("Specify --server on the Pi, or run this on the HighFinesse Windows PC.")
        print(f"Collecting fresh measurements for {args.seconds} seconds...", flush=True)
        try:
            readings, invalid = collect(ctypes.WinDLL("wlmData.dll"), args.seconds)
        except (AttributeError, OSError, RuntimeError) as error:
            parser.exit(1, f"Wavemeter check failed: {error}\n")

    for channel, laser in sorted(CHANNELS.items(), key=lambda item: item[1]):
        samples = readings[channel]
        summary = f"{laser} nm (CH {channel}): {len(samples)} valid, {invalid[channel]} invalid"
        if args.server:
            summary += f", {failures[channel]} request errors"
        if samples:
            summary += f", mean {statistics.mean(samples):.9f} THz"
        if len(samples) >= 2:
            summary += f", sample std dev {statistics.stdev(samples) * 1e6:.3f} MHz"
        else:
            summary += ", insufficient samples for standard deviation"
        if args.server and len(samples) >= 2 and min(samples) == max(samples):
            summary += " (all readings identical; freshness unknown)"
        print(summary)
    if args.server and not any(readings.values()):
        parser.exit(1, "No usable wavemeter readings.\n")


if __name__ == "__main__":
    main()
