"""QuDit Lab door dashboard and SPI touchscreen controls."""

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import subprocess
from threading import Thread
import time
from zoneinfo import ZoneInfo

from door_sign import Gdk, GLib, Gtk, fullscreen_window, label, open_touchscreen, watch_taps
from door_feed import FramePublisher
from ion_display import ION_STATES, SPECIES, IonDisplay
from paladin_shutter import ENABLE_FILE, read_shutter
from remote_control import RemoteControlServer, dashboard_reply
from temperature_display import TemperatureChart
from wavemeter_status import WAVEMETER_LASERS, WavemeterMonitor
from gi.repository import GdkPixbuf


LASERS = ("493", "650", "554", "614", "389")
LOCKED_LASERS = ("493", "650", "554")
LOCK_1762 = "1762_locked"
FIELDS = {laser: (f"{laser} nm", "ON", "OFF") for laser in LASERS}
FIELDS.update({
    "experiment": ("Experiment", "IN PROGRESS", "IDLE"),
    "lock": ("1762 nm", "ON", "OFF"),
    LOCK_1762: ("1762 nm lock", "LOCKED", "UNLOCKED"),
    "class4": ("532 nm", "ON", "OFF"),
})
LASER_COLORS = {
    "493": ("#087384", "#d9f0f3"),
    "650": ("#ad1925", "#f8dfe1"),
    "554": ("#657513", "#eef2d7"),
    "614": ("#ab4315", "#fae4d8"),
    "389": ("#523098", "#eee4fa"),
    "lock": ("#455562", "#e8edf0"),
    "class4": ("#167136", "#dff1e3"),
}
LAB_TIME_ZONE = ZoneInfo("America/Toronto")
CALIBRATION_FILE = Path(__file__).with_name("touch-calibration.json")
TARGETS = ((55, 54), (425, 54), (55, 266), (425, 266))


def calibrate(points):
    """Fit the first three corners and check the fourth against the result."""
    (x0, y0), (x1, y1), (x2, y2), check = points
    a, b, c, d = x1 - x0, x2 - x0, y1 - y0, y2 - y0
    determinant = a * d - b * c
    if abs(determinant) < 100_000:
        raise ValueError("Calibration targets are too close together")

    def to_screen(raw_x, raw_y):
        dx, dy = raw_x - x0, raw_y - y0
        horizontal = (d * dx - b * dy) / determinant
        vertical = (a * dy - c * dx) / determinant
        return round(55 + 370 * horizontal), round(54 + 212 * vertical)

    if math.dist(to_screen(*check), TARGETS[-1]) > 40:
        raise ValueError("Calibration points did not match the four targets")
    return to_screen


def load_calibration():
    try:
        return calibrate(json.loads(CALIBRATION_FILE.read_text()))
    except (OSError, ValueError, TypeError):
        return None


def box(vertical=True, spacing=0, *, equal=False):
    direction = Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL
    container = Gtk.Box(orientation=direction, spacing=spacing)
    container.set_homogeneous(equal)
    return container


def panel(child, style):
    surface = Gtk.EventBox()
    surface.get_style_context().add_class(style)
    surface.add(child)
    return surface


def text_block(title, detail, style):
    content = box(spacing=4)
    content.set_valign(Gtk.Align.CENTER)
    content.pack_start(label(title, style), False, False, 0)
    subtitle = label(detail, "detail")
    content.pack_start(subtitle, False, False, 0)
    return content, subtitle


def lab_clock():
    stamp = box(False, spacing=14)
    date = label("", "clock-date")
    clock = box(False)
    clock.get_style_context().add_class("clock")
    hours = Gtk.Label()
    colon = Gtk.Label(label=":")
    minutes = Gtk.Label()
    for part in (hours, colon, minutes):
        clock.pack_start(part, False, False, 0)
    stamp.pack_start(date, False, False, 0)
    stamp.pack_start(clock, False, False, 0)

    def refresh():
        now = datetime.now(LAB_TIME_ZONE)
        calendar = f"{now:%a, %b} {now.day}, {now:%Y}"
        for part, reading in ((date, calendar), (hours, f"{now:%H}"), (minutes, f"{now:%M}")):
            if part.get_text() != reading:
                part.set_text(reading)
        opacity = 1 if now.microsecond < 500_000 else 0
        if colon.get_opacity() != opacity:
            colon.set_opacity(opacity)
        return GLib.SOURCE_CONTINUE

    refresh()
    source = GLib.timeout_add(50, refresh)
    stamp.connect("destroy", lambda *_: GLib.source_remove(source))
    return stamp


def reset_touchscreen(button):
    button.set_sensitive(False)

    def reset():
        command = ["wlr-randr", "--output", "SPI-1", "--custom-mode"]
        try:
            for rate in (25, 30):
                try:
                    subprocess.run(
                        [*command, f"320x480@{rate}Hz"],
                        check=True, capture_output=True, text=True, timeout=4,
                    )
                except (OSError, subprocess.SubprocessError) as error:
                    print(f"Touch display reset at {rate} Hz: {getattr(error, 'stderr', None) or error}", flush=True)
                else:
                    if rate == 30:
                        print("Touch display reset to 30 Hz", flush=True)
                if rate == 25:
                    time.sleep(0.4)
        finally:
            GLib.idle_add(button.set_sensitive, True)

    Thread(target=reset, name="touch-display-reset", daemon=True).start()


def caution_band(height):
    band = Gtk.Overlay()
    band.set_size_request(-1, height)
    band.set_margin_start(6)
    band.set_margin_end(6)
    band.add(Gtk.Box())
    pattern = Gtk.Image()
    band.add_overlay(pattern)
    stripe_width = max(18, round(height * 1.35))
    period = stripe_width * 2
    repeat = bytes((255, 213, 32)) * stripe_width + bytes((23, 23, 23)) * stripe_width
    atlas = None
    source = None

    def resize(_band, allocation):
        nonlocal atlas
        width = allocation.width + period
        if allocation.width <= 1 or (atlas is not None and atlas.get_width() == width):
            return
        row = repeat * (width // period + 2)
        pixels = b"".join(row[3 * y:3 * (y + width)] for y in range(height))
        atlas = GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(pixels), GdkPixbuf.Colorspace.RGB, False, 8,
            width, height, width * 3,
        )
        advance()

    def advance():
        if atlas is not None:
            phase = int(time.monotonic() * 72) % period
            pattern.set_from_pixbuf(atlas.new_subpixbuf(phase, 0, atlas.get_width() - period, height))
        return GLib.SOURCE_CONTINUE

    def start(_band):
        nonlocal source
        advance()
        source = GLib.timeout_add(33, advance)

    def stop(_band):
        nonlocal source
        if source is not None:
            GLib.source_remove(source)
            source = None

    band.connect("size-allocate", resize)
    band.connect("map", start)
    band.connect("unmap", stop)
    return band


def dashboard(is_touch, width, height, on_click=None, on_ion=None, *, reset_button=None):
    gap = 5 if is_touch else max(8, height // 54)
    view = box(spacing=gap)
    view.get_style_context().add_class("touch" if is_touch else "door")
    for side in ("start", "end", "top", "bottom"):
        getattr(view, f"set_margin_{side}")(gap + 3)
    head = box(False, gap)
    head.pack_start(label("QuDit Lab" if is_touch else "Welcome to QuDit Lab", "heading"), False, False, 0)
    head.pack_end(reset_button if is_touch else lab_clock(), False, False, 0)
    view.pack_start(head, False, False, 0)
    if not is_touch:
        rule = Gtk.Separator()
        rule.get_style_context().add_class("heading-rule")
        view.pack_start(rule, False, False, 0)

    layout = box(False, gap)
    left = box(spacing=gap, equal=True)
    right = box(spacing=gap, equal=True)
    center = box(spacing=gap, equal=is_touch)
    left.set_size_request(int(width * 0.16), -1)
    right.set_size_request(int(width * (0.22 if is_touch else 0.16)), -1)
    layout.pack_start(left, False, False, 0)
    layout.pack_start(center, True, True, 0)
    layout.pack_start(right, False, False, 0)
    view.pack_start(layout, True, True, 0)

    cards = {}
    for key, (title, _, _) in FIELDS.items():
        if key == LOCK_1762 and not is_touch:
            continue
        content = box(spacing=4)
        content.set_valign(Gtk.Align.CENTER)
        content.pack_start(label(title, "tile-name"), False, False, 0)
        badges = box(False, 3 if is_touch else 8)
        badges.set_halign(Gtk.Align.CENTER)
        status = label("UNKNOWN", "detail")
        status.get_style_context().add_class("readout")
        badges.pack_start(status, False, False, 0)
        locked = None
        if key in LOCKED_LASERS or (key == "lock" and not is_touch):
            locked = label("LOCKED", "readout")
            locked.set_no_show_all(True)
            badges.pack_start(locked, False, False, 0)
        content.pack_start(badges, False, False, 0)
        if key == "class4":
            content.pack_start(label("CLASS 4 · 36 W", "class4-note"), False, False, 0)
            locked = label("", "readout")
            locked.set_halign(Gtk.Align.CENTER)
            locked.set_no_show_all(True)
            content.pack_start(locked, False, False, 0)
        if is_touch:
            card = Gtk.Button()
            card.get_style_context().add_class("tile")
            card.add(content)
            card.connect("clicked", lambda _button, field=key: on_click(field))
        else:
            card = panel(content, "tile")
        color = "lock" if key == LOCK_1762 else key
        if color in LASER_COLORS:
            card.get_style_context().add_class(f"laser-{color}")
        cards[key] = card, status, locked

    for key in LASERS:
        left.pack_start(cards[key][0], True, True, 0)
    for key in (("lock", LOCK_1762, "class4") if is_touch else ("lock", "class4")):
        right.pack_start(cards[key][0], True, True, 0)
    activity = center if is_touch else box(False, gap, equal=True)
    ion_display = IonDisplay(is_touch, width, on_ion)
    activity.pack_start(ion_display.widget, True, True, 0)
    activity.pack_start(cards["experiment"][0], True, True, 0)

    door_message = None
    if not is_touch:
        activity.set_size_request(-1, int(height * 0.22))
        center.pack_start(activity, False, False, 0)
        entry_notice, _ = text_block(
            "Please open the door slowly",
            "Laser locks are sensitive to pressure spikes.",
            "entry-notice-title",
        )
        entry_body = box()
        stripe_height = max(12, height // 50)
        top_band = caution_band(stripe_height)
        top_band.set_margin_top(6)
        bottom_band = caution_band(stripe_height)
        bottom_band.set_margin_bottom(6)
        entry_body.pack_start(top_band, False, False, 0)
        entry_body.pack_start(entry_notice, True, True, 0)
        entry_body.pack_start(bottom_band, False, False, 0)
        entry_body.show_all()
        entry_panel = panel(entry_body, "entry-notice")
        entry_panel.set_no_show_all(True)
        entry_panel.set_size_request(-1, int(height * 0.17))
        center.pack_start(entry_panel, False, False, 0)
        notice, message = text_block("", "", "warning-title")
        warning_panel = panel(notice, "warning")

        temperature = TemperatureChart(LAB_TIME_ZONE).widget

        lower_panel = Gtk.Stack()
        lower_panel.set_homogeneous(False)
        lower_panel.add_named(warning_panel, "warning")
        lower_panel.add_named(panel(temperature, "temperature"), "temperature")
        center.pack_start(lower_panel, True, True, 0)
        door_message = (
            lower_panel, warning_panel, notice.get_children()[0], message,
            entry_panel, entry_notice.get_children()[0],
        )
    return view, cards, door_message, ion_display


def install_styles(screen, width, height):
    size = max(13, min(height // 27, width // 44))
    laser_styles = "\n".join(
        f"""
        .qudit .tile.laser-{key} {{ border-left: 4px solid {color}; }}
        .door .tile.laser-{key} {{ border-left-width: 8px; }}
        .qudit .tile.laser-{key} .tile-name {{ color: {color}; }}
        .qudit .tile.laser-{key}.enabled {{ background: {color}; border-color: {color}; }}
        .qudit .tile.laser-{key}.enabled .tile-name {{ color: #fffdf7; }}
        .qudit .tile.laser-{key}.enabled .readout {{ background: {tint}; color: {color}; }}
        """
        for key, (color, tint) in LASER_COLORS.items()
    )
    provider = Gtk.CssProvider()
    provider.load_from_data(f"""
        .qudit {{ background: #f5f2e9; }}
        .qudit label {{ color: #23343c; font-family: 'CMU Serif', 'Latin Modern Roman', serif; }}
        .qudit .heading {{ color: #172d37; font-weight: bold; }}
        .heading-rule {{ background: #aaa794; min-height: 1px; }}
        .touch .heading {{ font-size: 22px; }}
        .touch .reset-display {{ background: #fffdf7; border: 1px solid #a7b5a9; border-radius: 6px; padding: 2px 9px; box-shadow: none; }}
        .touch .reset-display label {{ font-size: 14px; font-weight: bold; }}
        .door .heading {{ font-size: {size * 3 // 2}px; }}
        .door .clock-date, .door .clock label {{ font-size: {size * 5 // 4}px; }}
        .door .clock-date {{ color: #425b66; }}
        .door .clock label {{ font-weight: bold; color: #233d48; }}
        .qudit .tile, .temperature, .ion-card {{ background: #fffdf7; border: 1px solid #c9c3b3; border-radius: 9px; }}
        .qudit button.tile {{ padding: 2px; box-shadow: none; text-shadow: none; }}
        .qudit .tile.enabled {{ background: #23564d; border-color: #23564d; }}
        .qudit .tile.enabled .tile-name {{ color: #fffdf7; }}
        .qudit .tile .readout {{ background: #eeebe2; color: #354952; border-radius: 18px; font-weight: bold; }}
        .touch .tile .readout {{ padding: 1px 4px; font-size: 10px; }}
        .door .tile .readout {{ padding: 3px 13px; font-size: {max(11, size * 2 // 3)}px; }}
        .qudit .tile.enabled .readout {{ background: #e3f0e9; color: #204b41; }}
        .qudit .tile.unset .readout {{ background: #f5ead2; color: #67471c; }}
        {laser_styles}
        .qudit .tile.automatic:disabled {{ opacity: 1; }}
        .qudit .tile.attention .readout {{ background: #ffdf83; color: #522b05; }}
        .qudit .tile.sweep .readout {{ background: #d7f1e6; color: #124639; }}
        .qudit .tile.enabled.hazard {{ border-color: #8f202b; }}
        .qudit .tile.hazard label {{ color: #fff7ee; }}
        .qudit .tile.hazard .tile-name {{ color: #fff7ee; }}
        .qudit .tile.enabled.hazard .readout {{ background: #fff2e9; color: #831d28; }}
        .touch .tile-name {{ font-size: 15px; font-weight: bold; }}
        .touch .detail {{ font-size: 12px; }}
        .touch .class4-note {{ font-size: 10px; }}
        .door .tile-name {{ font-size: {size}px; font-weight: bold; }}
        .door .detail {{ font-size: {max(11, size * 2 // 3)}px; }}
        .door .class4-note {{ font-size: {max(10, size // 2)}px; }}
        .entry-notice {{ background: #ffdf66; border: 2px solid #8d6416; border-radius: 9px; }}
        .entry-notice label {{ color: #2d230f; }}
        .door .entry-notice-title {{ font-size: {size * 6 // 5}px; font-weight: bold; }}
        .ion-card {{ background: #f0ecf5; border-color: #a99abc; }}
        .ion-card.trapped {{ background: #34254d; border-color: #7c619c; }}
        .ion-card.trapping {{ background: #183447; border-color: #587e95; }}
        .ion-card .ion-state {{ color: #322448; font-weight: bold; }}
        .ion-card.trapped .ion-state, .ion-card.trapping .ion-state {{ color: #fff8ff; }}
        .ion-card.trapped .ion-detail {{ color: #e5ccff; }}
        .ion-card.trapping .ion-detail {{ color: #c0e7f3; }}
        .touch .ion-state {{ font-size: 16px; }}
        .touch .ion-detail {{ font-size: 14px; }}
        .door .ion-state {{ font-size: {size}px; }}
        .door .ion-detail {{ font-size: {max(14, size * 4 // 5)}px; }}
        .qudit .ion-action {{ background: #f5effa; border: 1px solid #a99abc; border-radius: 6px; padding: 2px; box-shadow: none; }}
        .qudit .ion-action label {{ color: #382954; font-size: 13px; font-weight: bold; }}
        .qudit .ion-action.selected {{ background: #6e4d9b; border-color: #9f82c7; }}
        .qudit .ion-action.selected label {{ color: #fff9ff; }}
        .temperature {{ background: #fcfdff; border-color: #9eafc2; }}
        .warning {{ border-radius: 10px; }}
        .warning.hazard {{ background: #8f202b; border: 3px solid #61131c; }}
        .warning.hazard label {{ color: #fff7ee; }}
        .warning.unset {{ background: #f8ecd1; border: 1px solid #a57b37; }}
        .warning.unset label {{ color: #603b10; }}
        .door .warning-title {{ font-size: {size * 2}px; font-weight: bold; }}
        .qudit .crosshair {{ background: #ffe08b; color: #1d2330; border-radius: 18px; font-size: 25px; font-weight: bold; }}
        .qudit .calibration-hint {{ font-size: 18px; }}
    """.encode())
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def update_door_message(door_message, class4_state, locked, *, paladin=False, simulated=None):
    lower_panel, notice, title, detail, entry_panel, entry_title = door_message
    entry_title.set_text(
        "Please open the door slowly" if class4_state is False else "If authorized to enter, open the door slowly"
    )
    entry_panel.set_visible(locked is True)
    simulation_warning = class4_state is False and not paladin and simulated is True
    show_temperature = class4_state is False and not simulation_warning
    lower_panel.set_visible_child_name("temperature" if show_temperature else "warning")
    style = notice.get_style_context()
    style.remove_class("hazard")
    style.remove_class("unset")
    if class4_state is True:
        style.add_class("hazard")
        title.set_text("DANGER · SHUTTER OPEN" if paladin else "DANGER · LASER ON")
        detail.set_text("532 nm Class 4 laser · 36 W\nDo not enter without approved laser eyewear. Authorized personnel only.")
    elif class4_state is None:
        style.add_class("unset")
        title.set_text("532 nm shutter status unknown" if paladin else "532 nm status unknown")
        detail.set_text("Do not enter. Contact the lab operator." if paladin else "Contact the lab operator before entering.")
    elif simulation_warning:
        style.add_class("unset")
        title.set_text("SIMULATION · SHUTTER OPEN")
        detail.set_text("Paladin Simulator test signal")


def run(initial_class4, force_calibration, initial_states, relay=False, wavemeter_host=None, paladin=False):
    display, screen = Gdk.Display.get_default(), Gdk.Screen.get_default()
    if display is None:
        raise RuntimeError("Start the Pi desktop before launching the dashboard")
    monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
    geometry = [monitor.get_geometry() for monitor in monitors]
    panels = [i for i, rect in enumerate(geometry) if (rect.width, rect.height) == (480, 320)]
    if len(panels) != 1:
        raise RuntimeError("Expected one landscape 480×320 touchscreen")
    touch_index = panels[0]
    relay = relay or len(monitors) == 1
    if relay:
        door_width, door_height = 1366, 768
    else:
        if len(monitors) != 2:
            raise RuntimeError("Use the SPI touchscreen and HDMI in an extended desktop")
        door_index = 1 - touch_index
        hdmi = geometry[door_index]
        door_width, door_height = hdmi.width, hdmi.height
    install_styles(screen, door_width, door_height)

    states = dict.fromkeys(FIELDS)
    states["class4"] = {"on": True, "off": False, "unknown": None}[initial_class4]
    states.update((key, value) for key, value in initial_states.items() if key in FIELDS)
    if states["lock"] is True:
        states[LOCK_1762] = initial_states.get(LOCK_1762, True)
    else:
        states[LOCK_1762] = states["lock"]
    saved_ion = initial_states.get("ion")
    ion_state = saved_ion if isinstance(saved_ion, str) else {True: "trapped", False: "empty", None: "unknown"}[saved_ion]
    ion_species = initial_states.get("species") if ion_state == "trapped" else None
    wavemeter_status = dict.fromkeys(WAVEMETER_LASERS, "UNKNOWN") if wavemeter_host else {}
    sweeping = False
    tuned_isotope = None
    simulated_shutter = None
    for key in wavemeter_status:
        states[key] = None
    automatic = [*wavemeter_status]
    fields = FIELDS.copy()
    if paladin:
        automatic.append("class4")
        fields["class4"] = ("532 nm shutter", "OPEN", "CLOSED")
        states["class4"] = None

    def update(key):
        state = states[key]
        auto_status = wavemeter_status.get(key)
        _, on, off = fields[key]
        for cards in (touch_cards, door_cards):
            if key not in cards:
                continue
            card, value, locked = cards[key]
            value.set_text(auto_status or ("UNKNOWN" if state is None else on if state else off))
            if locked is not None and key in LOCKED_LASERS:
                locked.set_visible(auto_status is None and state is True)
            if key == "class4":
                locked.set_text("SIM OPEN" if simulated_shutter is True else "SIM CLOSED")
                locked.set_visible(simulated_shutter is not None)
            style = card.get_style_context()
            for css in ("enabled", "unset", "hazard", "attention", "sweep"):
                style.remove_class(css)
            if state is None:
                style.add_class("unset")
            elif state:
                style.add_class("enabled")
                if key == "class4":
                    style.add_class("hazard")
            if auto_status in ("UNLOCKED", "LOCK UNKNOWN", "MODE HOP"):
                style.add_class("attention")
            elif auto_status == "SWEEP":
                style.add_class("sweep")
        power_on = states["lock"] is True
        lock_state = states[LOCK_1762]
        if key in ("lock", LOCK_1762):
            touch_cards[LOCK_1762][0].set_sensitive(power_on)
            lock_badge = door_cards["lock"][2]
            lock_badge.set_text({True: "LOCKED", False: "UNLOCKED", None: "LOCK UNKNOWN"}[lock_state])
            lock_badge.set_visible(power_on)
        if key in ("class4", "lock", LOCK_1762):
            update_door_message(
                door_message, states["class4"], power_on and lock_state is True,
                paladin=paladin, simulated=simulated_shutter,
            )

    def set_field(key, value):
        if key in automatic or (key == LOCK_1762 and states["lock"] is not True):
            return
        if states[key] is value:
            return
        states[key] = value
        if key == "lock":
            states[LOCK_1762] = False
            update(LOCK_1762)
        update(key)
        print(f"{key}: {'ON' if states[key] else 'OFF'}", flush=True)

    def toggle(key):
        set_field(key, not states[key])

    def refresh_ion():
        for card in (touch_ion, door_ion):
            card.set_state(ion_state, ion_species, sweeping=sweeping, tuned_isotope=tuned_isotope)

    def select_ion(state, species=None):
        nonlocal ion_state, ion_species
        if (state, species) == (ion_state, ion_species):
            return
        ion_state, ion_species = state, species
        refresh_ion()
        print(f"ion: {state}" + (f" {SPECIES[species]}" if species else ""), flush=True)

    def apply_wavemeter(status, sweep, isotope):
        nonlocal sweeping, tuned_isotope
        for key, reading in status.items():
            if wavemeter_status[key] != reading:
                wavemeter_status[key] = reading
                states[key] = None if reading == "UNKNOWN" else True
                update(key)
        if (sweeping, tuned_isotope) != (sweep, isotope):
            sweeping, tuned_isotope = sweep, isotope
            refresh_ion()
        return GLib.SOURCE_REMOVE

    def refresh_shutter():
        nonlocal paladin, simulated_shutter
        simulation = read_shutter(simulated=True)
        changed = simulation is not simulated_shutter
        simulated_shutter = simulation
        if not paladin and ENABLE_FILE.is_file():
            paladin = True
            automatic.append("class4")
            fields["class4"] = ("532 nm shutter", "OPEN", "CLOSED")
            make_automatic("class4")
            changed = True
            print("Paladin shutter feed enabled", flush=True)
        if paladin:
            reading = read_shutter()
            if reading is not states["class4"]:
                states["class4"] = reading
                changed = True
        if changed:
            update("class4")
        return GLib.SOURCE_CONTINUE

    reset_button = Gtk.Button(label="Reset display")
    reset_button.set_size_request(112, 38)
    reset_button.get_style_context().add_class("reset-display")
    reset_button.connect("clicked", reset_touchscreen)
    controls, touch_cards, _, touch_ion = dashboard(True, 480, 320, toggle, select_ion, reset_button=reset_button)
    door, door_cards, door_message, door_ion = dashboard(False, door_width, door_height)

    def make_automatic(key):
        tile = touch_cards[key][0]
        tile.set_sensitive(False)
        tile.get_style_context().add_class("automatic")

    for key in automatic:
        make_automatic(key)
    touch_buttons = [card for card, _, _ in touch_cards.values()]
    touch_buttons.extend(touch_ion.buttons.values())
    touch_buttons.extend(touch_ion.species_buttons)
    touch_buttons.append(reset_button)

    position_map = None if force_calibration else load_calibration()
    points = []
    stack = Gtk.Stack()
    stack.set_homogeneous(False)
    stack.add_named(controls, "controls")
    calibration = Gtk.Fixed()
    calibration.set_size_request(480, 320)
    crosshair = label("+", "crosshair")
    crosshair.set_size_request(36, 36)
    calibration.put(crosshair, TARGETS[0][0] - 18, TARGETS[0][1] - 18)
    hint = label("Touch the crosshair · 1 of 4", "calibration-hint")
    hint.set_size_request(480, 52)
    calibration.put(hint, 0, 133)
    stack.add_named(calibration, "calibration")

    controller_window = fullscreen_window("QuDit Lab touch controls", stack, screen, touch_index)
    if relay:
        door_window = Gtk.OffscreenWindow()
        door_window.set_default_size(door_width, door_height)
        door_window.add(door)
    else:
        door_window = fullscreen_window("QuDit Lab door display", door, screen, door_index)
    for window in (controller_window, door_window):
        window.get_style_context().add_class("qudit")

    def monitor_removed(_display, monitor):
        if not relay or monitor == monitors[touch_index]:
            Gtk.main_quit()

    display.connect("monitor-removed", monitor_removed)

    def tap(raw_x, raw_y):
        nonlocal position_map
        if position_map is None:
            points.append([raw_x, raw_y])
            print(f"Calibration {len(points)}/4: {raw_x}, {raw_y}", flush=True)
            if len(points) == len(TARGETS):
                try:
                    position_map = calibrate(points)
                except ValueError:
                    points.clear()
                    hint.set_text("Try again · touch the crosshair")
                else:
                    temporary = CALIBRATION_FILE.with_suffix(".tmp")
                    temporary.write_text(json.dumps(points))
                    temporary.replace(CALIBRATION_FILE)
                    stack.set_visible_child_name("controls")
                    print("Touch calibration saved", flush=True)
                    return
            else:
                hint.set_text(f"Touch the crosshair · {len(points) + 1} of 4")
            x, y = TARGETS[len(points)]
            calibration.move(crosshair, x - 18, y - 18)
            return

        x, y = position_map(raw_x, raw_y)
        for card in touch_buttons:
            if not card.get_mapped() or not card.is_sensitive():
                continue
            origin = card.translate_coordinates(controller_window, 0, 0)
            if origin is None:
                continue
            left, top = origin
            if left <= x < left + card.get_allocated_width() and top <= y < top + card.get_allocated_height():
                card.clicked()
                return

    def touch_disconnected():
        for key in states:
            if key not in automatic:
                states[key] = None
                update(key)
        select_ion("unknown")
        controls.set_sensitive(False)
        hint.set_text("Touchscreen disconnected")
        crosshair.hide()
        stack.set_visible_child_name("calibration")

    controls_spec = {
        "lasers": LASERS,
        "locked": [key for key in LOCKED_LASERS if key not in wavemeter_status],
        "automatic": automatic,
        "lock_status": LOCK_1762,
        "colors": {**LASER_COLORS, LOCK_1762: LASER_COLORS["lock"]},
        "ion_states": ION_STATES,
        "species": SPECIES,
    }

    def snapshot():
        # The installed Windows client already displays the server's per-tile labels.
        current_fields = {**fields, **{
            key: (FIELDS[key][0], reading, FIELDS[key][2])
            for key, reading in wavemeter_status.items()
        }}
        return {
            "state": {**states, "ion": ion_state, "species": ion_species},
            "controls": {**controls_spec, "fields": current_fields},
            "wavemeter": {"statuses": dict(wavemeter_status), "sweeping": sweeping, "tuned_isotope": tuned_isotope},
            "paladin": {"automatic": paladin, "simulated_shutter": simulated_shutter},
        }

    fd = open_touchscreen()
    remote = None
    publisher = None
    monitor = None
    try:
        watch_taps(fd, tap, touch_disconnected, with_position=True)
        for window in (controller_window, door_window):
            window.show_all()
        for key in states:
            update(key)
        refresh_ion()
        stack.set_visible_child_name("controls" if position_map else "calibration")
        try:
            remote = RemoteControlServer(
                lambda request: dashboard_reply(request, snapshot, set_field, select_ion), GLib.idle_add,
            )
            remote.start()
            print("SSH dashboard control ready", flush=True)
        except OSError as error:
            print(f"SSH dashboard control unavailable: {error}", flush=True)
        if relay:
            publisher = FramePublisher(door_window, GLib)
            print("Door relay feed ready", flush=True)
        if wavemeter_host:
            monitor = WavemeterMonitor(wavemeter_host, lambda *status: GLib.idle_add(apply_wavemeter, *status))
        refresh_shutter()
        GLib.timeout_add(250, refresh_shutter)
        print(f"QuDit dashboard ready ({'calibrated' if position_map else 'awaiting calibration'})", flush=True)
        Gtk.main()
    finally:
        if monitor is not None:
            monitor.stop.set()
        if publisher is not None:
            publisher.close()
        if remote is not None:
            remote.close()
        os.close(fd)


def read_initial_states(raw):
    try:
        states = json.loads(raw)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected a JSON object of statuses") from error
    if not isinstance(states, dict):
        raise argparse.ArgumentTypeError("Expected a JSON object of statuses")
    for key, value in states.items():
        if key == "ion" and isinstance(value, str) and value in ION_STATES:
            continue
        if key == "species" and isinstance(value, str) and value in SPECIES:
            continue
        if (key in FIELDS or key == "ion") and (value is None or isinstance(value, bool)):
            continue
        raise argparse.ArgumentTypeError(f"Invalid value or tile in initial statuses: {key}")
    return states


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--class4", choices=("on", "off", "unknown"), default="unknown")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--relay", action="store_true", help="Render the door display for the relay Pi")
    parser.add_argument("--wavemeter", metavar="HOST", help="Read automatic laser status from IonControl")
    parser.add_argument("--paladin", action="store_true", help="Use the Paladin shutter feed for the 532 nm tile")
    parser.add_argument("--initial-states", type=read_initial_states, default={})
    args = parser.parse_args()
    run(args.class4, args.calibrate, args.initial_states, args.relay, args.wavemeter, args.paladin)
