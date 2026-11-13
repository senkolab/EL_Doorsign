"""Interpret the IonControl wavemeter feed for the lab status display."""

import http.client
import math
from threading import Event, Thread
import time

from wavemeter_probe import CHANNELS, read_frequency, read_references


WAVEMETER_LASERS = tuple(str(laser) for laser in CHANNELS.values())
COOLING_BASELINES = {"493": 607.432010, "650": 461.311350}
IONIZATION_FREQUENCIES = {"137": 541.433326, "138": 541.433050}
LOCK_TOLERANCE = 5e-6  # 5 MHz in THz
SWEEP_LIMIT = 500e-6
IONIZATION_TOLERANCE = 30e-6
RANGE_614 = (487.98800, 487.99150)
POLL_SECONDS = 2
UNCHANGED_SECONDS = 12
READ_ERRORS = (OSError, http.client.HTTPException, ValueError)
REFERENCE_ERRORS = READ_ERRORS + (KeyError, TypeError)


def valid_frequency(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def classify(measured, targets, regulation_active):
    status = {}
    for laser in WAVEMETER_LASERS:
        frequency = measured.get(laser)
        target = targets.get(laser)
        if frequency is None:
            status[laser] = "UNKNOWN"
        elif laser == "614":
            status[laser] = "IN RANGE" if RANGE_614[0] <= frequency <= RANGE_614[1] else "MODE HOP"
        elif regulation_active is False:
            status[laser] = "UNLOCKED"
        elif regulation_active is None or target is None:
            status[laser] = "LOCK UNKNOWN"
        else:
            close = target - LOCK_TOLERANCE < frequency < target + LOCK_TOLERANCE
            status[laser] = "LOCKED" if close else "UNLOCKED"

    def red(laser, baseline):
        frequency = measured.get(laser)
        return frequency is not None and baseline - SWEEP_LIMIT <= frequency < baseline - LOCK_TOLERANCE

    sweeping = all(red(laser, baseline) for laser, baseline in COOLING_BASELINES.items())
    if sweeping:
        for laser in COOLING_BASELINES:
            status[laser] = "SWEEP"
    frequency = measured.get("554")
    isotope = next((name for name, target in IONIZATION_FREQUENCIES.items()
                    if frequency is not None and target - IONIZATION_TOLERANCE <= frequency <= target + IONIZATION_TOLERANCE), None)
    return status, sweeping, isotope


def read_targets(host):
    try:
        reply = read_references(host)
        active = reply["regulation_active"]
        channels = reply["channels"]
        if type(active) is not bool or not isinstance(channels, dict):
            return {}, None
    except REFERENCE_ERRORS:
        return {}, None
    targets = {}
    for channel, laser in CHANNELS.items():
        reference = channels.get(str(channel))
        value = reference.get("reference_thz") if isinstance(reference, dict) else None
        if valid_frequency(value):
            targets[str(laser)] = value
    return targets, active


class WavemeterMonitor:
    def __init__(self, host, publish):
        self.host = host
        self.publish = publish
        self.stop = Event()
        self.last_value = {}
        self.last_change = {}
        Thread(target=self.run, name="wavemeter-status", daemon=True).start()

    def run(self):
        while not self.stop.is_set():
            targets, regulation_active = read_targets(self.host)
            measured = {}
            for channel, laser in CHANNELS.items():
                if self.stop.is_set():
                    return
                try:
                    frequency = read_frequency(self.host, channel)
                except READ_ERRORS:
                    frequency = None
                if not valid_frequency(frequency):
                    self.last_value.pop(laser, None)
                    self.last_change.pop(laser, None)
                    continue
                now = time.monotonic()
                if laser in self.last_value and self.last_value[laser] != frequency:
                    self.last_change[laser] = now
                self.last_value[laser] = frequency
                # The endpoint has no sample timestamp. Require recent variation.
                if laser in self.last_change and now - self.last_change[laser] <= UNCHANGED_SECONDS:
                    measured[str(laser)] = frequency
            if not self.stop.is_set():
                self.publish(*classify(measured, targets, regulation_active))
            self.stop.wait(POLL_SECONDS)
