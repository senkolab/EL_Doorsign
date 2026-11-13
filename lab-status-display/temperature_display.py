"""Read and display the QuDit Lab Temperature panel's three InfluxDB series."""

from datetime import datetime
from http.client import HTTPException
from io import BytesIO
import json
import math
from threading import Thread
import time
from urllib.parse import urlencode
from urllib.request import urlopen

import cairo
import gi

from door_sign import GLib, Gtk

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf


SOURCE = "http://graphana-pi.local:8086/query"
DATABASE = "lab_HPT"
WINDOW_SECONDS = 48 * 60 * 60
REFRESH_SECONDS = 60
STALE_SECONDS = 15 * 60
SERIES = (
    ("1762nm_vent", "Building AHU", (0.73, 0.24, 0.06), ()),
    ("open_air", "Near the trap", (0.05, 0.32, 0.67), (12, 5)),
    ("open-air-lasers", "Near the lasers", (0.56, 0.12, 0.43), (7, 4)),
)
QUERY = (
    'SELECT mean("temperature") FROM "environment" WHERE time >= now() - 2d '
    'AND "location" =~ /^(1762nm_vent|open_air|open-air-lasers)$/ '
    'GROUP BY time(5m), "location" fill(null)'
)


def fetch_temperature():
    params = urlencode({"db": DATABASE, "epoch": "ms", "q": QUERY})
    with urlopen(f"{SOURCE}?{params}", timeout=6) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("Unexpected temperature response")
    if payload.get("error"):
        raise ValueError(payload["error"])

    known_locations = {key for key, _, _, _ in SERIES}
    data = {}
    for result in payload.get("results", []):
        if result.get("error"):
            raise ValueError(result["error"])
        for record in result.get("series", []):
            location = record.get("tags", {}).get("location")
            if location in known_locations:
                data[location] = [
                    (stamp / 1000, value if value is not None and math.isfinite(value) else None)
                    for stamp, value in record["values"]
                ]
    if not any(value is not None for points in data.values() for _, value in points):
        raise ValueError("No temperature measurements in the last 48 hours")
    return data


def axis_limits(values):
    return (min(values), max(values)) if values else None


def axis_ticks(limits):
    if limits is None:
        return ()
    low, high = limits
    if low == high:
        return (low,)
    target = (high - low) / 5
    magnitude = 10 ** math.floor(math.log10(target))
    step = min((magnitude * factor for factor in (1, 2, 2.5, 5, 10)), key=lambda value: abs(value - target))
    return tuple(step * index for index in range(math.ceil(low / step), math.floor(high / step) + 1))


def value_y(value, limits, top, bottom):
    low, high = limits
    if low == high:
        return (top + bottom) / 2
    return bottom - (bottom - top) * (value - low) / (high - low)


def chart_text(ctx, text, x, y, size, *, align=0, bold=False):
    weight = cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL
    ctx.select_font_face("CMU Serif", cairo.FONT_SLANT_NORMAL, weight)
    ctx.set_font_size(size)
    ctx.move_to(x - ctx.text_extents(text).x_advance * align, y)
    ctx.show_text(text)


def axis_title(ctx, text, x, y, angle, size):
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(angle)
    chart_text(ctx, text, 0, 0, size, align=0.5, bold=True)
    ctx.restore()


def draw_temperature_chart(width, height, data, end, timezone, feed_error):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    font = min(24, max(11, min(width // 49, height // 14)))
    pad = font * 1.15
    ctx.set_source_rgb(0.09, 0.17, 0.29)
    chart_text(ctx, "QuDit Lab Temperature", pad, font * 1.48, font * 1.42, bold=True)

    if not data:
        message = "Temperature feed unavailable" if feed_error else "Loading temperature data…"
        chart_text(ctx, message, width / 2, height / 2, font, align=0.5)
        return surface

    start = end - WINDOW_SECONDS
    visible = {key: [(stamp, value) for stamp, value in points if start <= stamp <= end] for key, points in data.items()}
    latest = {
        key: next(((stamp, value) for stamp, value in reversed(visible.get(key, ())) if value is not None), None)
        for key, _, _, _ in SERIES
    }
    delayed = any(reading is None or end - reading[0] > STALE_SECONDS for reading in latest.values())
    note = ""
    if feed_error:
        note = "Feed unavailable · showing last available data"
    elif delayed:
        note = "Some sensors have delayed data"

    chart_text(ctx, "48 hours · 5-minute averages", width - pad, font * 1.42, font * 0.84, align=1)
    left, right = font * 3.9, width - font * 3.9
    top = font * 2.20
    legend_y = height - font * (1.20 if note else 0.48)
    bottom = legend_y - font * 2.35
    axes = (
        axis_limits([value for _, value in visible.get(SERIES[0][0], ()) if value is not None]),
        axis_limits([value for key, _, _, _ in SERIES[1:] for _, value in visible.get(key, ()) if value is not None]),
    )

    ctx.set_source_rgb(0.946, 0.965, 0.986)
    ctx.rectangle(left, top, right - left, bottom - top)
    ctx.fill()
    middle_y = (top + bottom) / 2
    ctx.set_source_rgb(*SERIES[0][2])
    axis_title(ctx, "AHU °C", font * 1.1, middle_y, -math.pi / 2, font * 0.84)
    ctx.set_source_rgb(0.15, 0.23, 0.35)
    axis_title(ctx, "Lab °C", width - font * 1.1, middle_y, math.pi / 2, font * 0.84)
    for index in range(5):
        fraction = index / 4
        x = left + (right - left) * fraction
        ctx.set_source_rgb(0.78, 0.83, 0.88)
        ctx.set_line_width(1)
        ctx.move_to(x, top)
        ctx.line_to(x, bottom)
        ctx.stroke()
        if width >= 680 or index % 2 == 0:
            ctx.set_source_rgb(0.17, 0.25, 0.37)
            stamp = datetime.fromtimestamp(start + WINDOW_SECONDS * fraction, timezone)
            chart_text(ctx, stamp.strftime("%b %d %H:%M"), x, bottom + font * 1.02, font * 0.78, align=0.5)

    for side, limits in enumerate(axes):
        for tick in axis_ticks(limits):
            y = value_y(tick, limits, top, bottom)
            if side == 0 or axes[0] is None:
                ctx.set_source_rgb(0.75, 0.81, 0.87)
                ctx.move_to(left, y)
                ctx.line_to(right, y)
                ctx.stroke()
            x = left - font * 0.38 if side == 0 else right + font * 0.38
            ctx.set_source_rgb(*(SERIES[0][2] if side == 0 else (0.15, 0.23, 0.35)))
            chart_text(ctx, f"{tick:g}", x, y + font * 0.27, font * 0.84, align=1 if side == 0 else 0)

    ctx.set_source_rgb(0.41, 0.50, 0.61)
    ctx.set_line_width(1.25)
    ctx.rectangle(left, top, right - left, bottom - top)
    ctx.stroke()

    ctx.save()
    ctx.rectangle(left, top - 1.5, right - left, bottom - top + 3)
    ctx.clip()
    for index, (key, _, color, dash) in enumerate(SERIES):
        limits = axes[0 if index == 0 else 1]
        if limits is None:
            continue
        ctx.set_source_rgb(*color)
        ctx.set_line_width(max(2.0, font / 8))
        ctx.set_dash(dash)
        connected = False
        for stamp, value in visible.get(key, ()):
            if value is None:
                connected = False
                continue
            x = left + (right - left) * (stamp - start) / WINDOW_SECONDS
            y = value_y(value, limits, top, bottom)
            if connected:
                ctx.line_to(x, y)
            else:
                ctx.move_to(x, y)
            connected = True
        ctx.stroke()
    ctx.restore()

    for index, (key, name, color, dash) in enumerate(SERIES):
        x = pad + index * (width - 2 * pad) / 3
        ctx.set_source_rgb(*color)
        ctx.set_line_width(3)
        ctx.set_dash(dash)
        ctx.move_to(x, legend_y - font * 0.24)
        ctx.line_to(x + font * 0.95, legend_y - font * 0.24)
        ctx.stroke()
        sample = latest[key]
        reading = "—" if sample is None else f"{sample[1]:.1f} °C"
        chart_text(ctx, f"{name} · {reading}", x + font * 1.28, legend_y, font * 0.88, bold=True)

    if note:
        ctx.set_source_rgb(0.47, 0.27, 0.09)
        chart_text(ctx, note, width - pad, height - font * 0.35, font * 0.72, align=1)
    return surface


class TemperatureChart:
    def __init__(self, timezone):
        self.timezone = timezone
        self.data = {}
        self.end = None
        self.feed_error = False
        self.pending = False
        self.timer = None
        self.render_source = None
        self.size = (0, 0)

        # The bitmap follows the panel size and stays anchored at its top left.
        self.widget = Gtk.Layout()
        self.widget.set_size_request(-1, 150)
        self.image = Gtk.Image()
        self.widget.put(self.image, 0, 0)
        self.widget.connect("map", self.start)
        self.widget.connect("unmap", self.stop)
        self.widget.connect("size-allocate", self.resize)

    def start(self, _widget):
        self.queue_render()
        self.refresh()
        self.timer = GLib.timeout_add_seconds(REFRESH_SECONDS, self.refresh)

    def stop(self, _widget):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        if self.render_source is not None:
            GLib.source_remove(self.render_source)
            self.render_source = None

    def refresh(self):
        if not self.pending:
            self.pending = True
            Thread(target=self.read, name="lab-temperature", daemon=True).start()
        return GLib.SOURCE_CONTINUE

    def read(self):
        try:
            data = fetch_temperature()
        except (OSError, HTTPException, ValueError, TypeError, KeyError) as error:
            print(f"Temperature feed: {error}", flush=True)
            GLib.idle_add(self.receive, None, time.time())
        else:
            GLib.idle_add(self.receive, data, time.time())

    def receive(self, data, end):
        self.pending = False
        self.feed_error = data is None
        if data is not None:
            self.data, self.end = data, end
        self.queue_render()
        return GLib.SOURCE_REMOVE

    def resize(self, _widget, allocation):
        size = (allocation.width, allocation.height)
        if size != self.size:
            self.size = size
            self.queue_render()

    def queue_render(self):
        if self.render_source is None and self.widget.get_mapped():
            self.render_source = GLib.idle_add(self.render, priority=GLib.PRIORITY_HIGH_IDLE)

    def render(self):
        self.render_source = None
        width, height = self.size
        if width < 100 or height < 100:
            return GLib.SOURCE_REMOVE
        surface = draw_temperature_chart(width, height, self.data, self.end, self.timezone, self.feed_error)
        buffer = BytesIO()
        surface.write_to_png(buffer)
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(buffer.getvalue())
        loader.close()
        self.image.set_from_pixbuf(loader.get_pixbuf())
        return GLib.SOURCE_REMOVE
