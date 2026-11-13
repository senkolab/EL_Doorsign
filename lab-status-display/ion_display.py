"""Ion trap controls, schematic, and optional door-display clip."""

from io import BytesIO
from math import tau
from pathlib import Path
import time

import cairo
import gi

from door_sign import GLib, Gtk, label

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
from gi.repository import GdkPixbuf, Pango


ION_STATES = {
    "empty": "Trap empty",
    "trapping": "Trapping",
    "trapped": "Ion trapped",
    "unknown": "Trap status unknown",
}
SPECIES = {"137": "Ba-137", "138": "Ba-138"}
ION_CLIP = Path(__file__).with_name("ion-trapped.gif")


def draw_trap_rod(ctx, y, radius, foreground):
    surface = cairo.LinearGradient(0, y - radius, 0, y + radius)
    if foreground:
        surface.add_color_stop_rgb(0, 0.97, 0.81, 0.59)
        surface.add_color_stop_rgb(0.35, 0.84, 0.65, 0.43)
        surface.add_color_stop_rgb(1, 0.47, 0.31, 0.19)
    else:
        surface.add_color_stop_rgb(0, 0.76, 0.59, 0.42)
        surface.add_color_stop_rgb(0.35, 0.64, 0.46, 0.29)
        surface.add_color_stop_rgb(1, 0.34, 0.23, 0.15)
    ctx.set_source(surface)
    ctx.rectangle(0, y - radius, 160, 2 * radius)
    ctx.fill()


def draw_ablation_target(ctx, face_x, face_y):
    radius = 8.6
    depth = 19
    ctx.save()
    ctx.translate(face_x, face_y)
    ctx.rotate(0.15)

    body = cairo.LinearGradient(0, -radius, 0, radius)
    body.add_color_stop_rgb(0, 0.70, 0.77, 0.77)
    body.add_color_stop_rgb(0.38, 0.43, 0.52, 0.55)
    body.add_color_stop_rgb(1, 0.24, 0.32, 0.36)
    ctx.set_source(body)
    ctx.move_to(0, -radius)
    ctx.line_to(depth, -radius)
    ctx.curve_to(depth + 8, -radius, depth + 8, radius, depth, radius)
    ctx.line_to(0, radius)
    ctx.close_path()
    ctx.fill()

    ctx.scale(0.77, 1)
    face = cairo.LinearGradient(0, -radius, 0, radius)
    face.add_color_stop_rgb(0, 0.57, 0.67, 0.69)
    face.add_color_stop_rgb(1, 0.31, 0.42, 0.46)
    ctx.set_source(face)
    ctx.arc(0, 0, radius, 0, tau)
    ctx.fill_preserve()
    ctx.set_source_rgb(0.74, 0.81, 0.80)
    ctx.set_line_width(0.8)
    ctx.stroke()
    ctx.restore()


def draw_green_glow(ctx, x, y, radius, core):
    glow = cairo.RadialGradient(x, y, 0, x, y, radius)
    glow.add_color_stop_rgba(0, 0.55, 1, 0.76, 0.95)
    glow.add_color_stop_rgba(1, 0.25, 1, 0.63, 0)
    ctx.set_source(glow)
    ctx.arc(x, y, radius, 0, tau)
    ctx.fill()
    ctx.set_source_rgb(0.88, 1, 0.91)
    ctx.arc(x, y, core, 0, tau)
    ctx.fill()


def trap_frame(width, height, *, ion=False, beam=False):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    ctx = cairo.Context(surface)
    ctx.scale(width / 160, height / 104)
    ctx.set_source_rgb(0.055, 0.13, 0.15)
    ctx.paint()

    for y in (18, 60):
        draw_trap_rod(ctx, y, 3.7, foreground=False)
    for y in (31, 72):
        draw_trap_rod(ctx, y, 4.1, foreground=True)

    steel = cairo.LinearGradient(0, 43, 0, 53)
    steel.add_color_stop_rgb(0, 0.68, 0.80, 0.82)
    steel.add_color_stop_rgb(0.4, 0.89, 0.95, 0.94)
    steel.add_color_stop_rgb(1, 0.29, 0.44, 0.49)
    needle = ((0, 44.5), (43, 44.5), (72, 48), (43, 51.5), (0, 51.5))
    ctx.set_source(steel)
    for direction in (1, -1):
        x, y = needle[0]
        ctx.move_to(80 + direction * (x - 80), y)
        for x, y in needle[1:]:
            ctx.line_to(80 + direction * (x - 80), y)
        ctx.close_path()
        ctx.fill()

    target_x, target_y = 58, 88
    draw_ablation_target(ctx, target_x, target_y)

    if beam:
        ctx.set_source_rgba(0.21, 1, 0.57, 0.24)
        ctx.move_to(-4, 90)
        ctx.line_to(target_x, target_y - 1)
        ctx.line_to(target_x, target_y + 1)
        ctx.line_to(-4, 100)
        ctx.close_path()
        ctx.fill()
        ctx.set_source_rgb(0.36, 1, 0.65)
        ctx.set_line_width(2.2)
        ctx.move_to(-4, 95)
        ctx.line_to(target_x, target_y)
        ctx.stroke()
        draw_green_glow(ctx, target_x, target_y, 9, 2.2)
        ctx.set_source_rgb(0.99, 0.81, 0.52)
        for x, y, radius in ((61, 83, 1.1), (64, 79, 0.9), (68, 82, 0.8)):
            ctx.arc(x, y, radius, 0, tau)
            ctx.fill()

    if ion:
        draw_green_glow(ctx, 80, 48, 11, 3.2)

    buffer = BytesIO()
    surface.write_to_png(buffer)
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(buffer.getvalue())
    loader.close()
    return loader.get_pixbuf()


def load_ion_clip(width, height):
    data = ION_CLIP.read_bytes()
    loader = GdkPixbuf.PixbufLoader.new_with_type("gif")

    def fit(loader, original_width, original_height):
        scale = min(width / original_width, height / original_height, 1)
        if scale < 1:
            loader.set_size(max(1, round(original_width * scale)), max(1, round(original_height * scale)))

    loader.connect("size-prepared", fit)
    try:
        loader.write(data)
    finally:
        loader.close()
    animation = loader.get_animation()
    if animation is None:
        raise ValueError("Ion clip has no frames")
    return animation


class TrapGraphic:
    def __init__(self, width, *, allow_clip):
        self.width = width
        self.height = round(width * 104 / 160)
        self.allow_clip = allow_clip
        self.empty = trap_frame(width, self.height)
        self.trapped = trap_frame(width, self.height, ion=True)
        self.ablation = trap_frame(width, self.height, beam=True)
        self.timer = None
        self.pulse_started = 0.0
        self.beam_visible = False

        self.widget = Gtk.Stack()
        self.widget.set_size_request(width, self.height)
        self.schematic = Gtk.Image.new_from_pixbuf(self.empty)
        self.clip = Gtk.Image()
        self.widget.add_named(self.schematic, "schematic")
        self.widget.add_named(self.clip, "clip")
        self.widget.connect("destroy", lambda *_: self.stop_pulses())

    def stop_pulses(self):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None

    def update_pulse(self):
        beam_visible = (time.monotonic() - self.pulse_started) % 1.0 < 0.18
        if beam_visible != self.beam_visible:
            self.beam_visible = beam_visible
            self.schematic.set_from_pixbuf(self.ablation if beam_visible else self.empty)
        return GLib.SOURCE_CONTINUE

    def set_state(self, state):
        self.stop_pulses()
        self.widget.set_visible_child_name("schematic")
        self.clip.clear()
        self.schematic.set_from_pixbuf(self.trapped if state == "trapped" else self.empty)
        if state == "trapping":
            self.beam_visible = False
            self.pulse_started = time.monotonic()
            self.update_pulse()
            self.timer = GLib.timeout_add(30, self.update_pulse)
        elif state == "trapped" and self.allow_clip and ION_CLIP.is_file():
            try:
                animation = load_ion_clip(self.width, self.height)
            except (GLib.Error, OSError, ValueError) as error:
                print(f"Ion clip unavailable: {error}", flush=True)
            else:
                self.clip.set_from_animation(animation)
                self.widget.set_visible_child_name("clip")


class IonDisplay:
    def __init__(self, is_touch, width, on_select=None):
        self.buttons = {}
        self.species_buttons = []
        self.isotope_rise = "3pt" if is_touch else "8pt"
        self.graphic_state = None
        self.graphic = TrapGraphic(68 if is_touch else min(220, max(72, width // 9)), allow_clip=not is_touch)
        self.widget = Gtk.EventBox()
        self.widget.get_style_context().add_class("ion-card")

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=9 if is_touch else 18)
        row.set_valign(Gtk.Align.CENTER)
        row.pack_start(self.graphic.widget, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        text.set_valign(Gtk.Align.CENTER)
        self.title = label("", "ion-state")
        self.detail = label("", "ion-detail")
        for widget in (self.title, self.detail):
            widget.set_xalign(0)
            widget.set_ellipsize(Pango.EllipsizeMode.END)
            text.pack_start(widget, False, False, 0)
        row.pack_start(text, True, True, 0)

        if is_touch:
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
            content.pack_start(row, True, True, 0)
            self.actions = Gtk.Stack()
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5, homogeneous=True)
            for state, title in (("empty", "Trap\nempty"), ("trapping", "Trapping"), ("trapped", "Ion\ntrapped")):
                button = self.action_button(title)
                if state == "trapped":
                    button.connect("clicked", lambda _: self.actions.set_visible_child_name("species"))
                else:
                    button.connect("clicked", lambda _button, target=state: on_select(target))
                actions.pack_start(button, True, True, 0)
                self.buttons[state] = button

            picker = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5, homogeneous=True)

            def choose_species(_button, isotope):
                self.actions.set_visible_child_name("states")
                on_select("trapped", isotope)

            for isotope, name in SPECIES.items():
                button = self.action_button(name)
                button.connect("clicked", choose_species, isotope)
                picker.pack_start(button, True, True, 0)
                self.species_buttons.append(button)
            back = self.action_button("Back")
            back.connect("clicked", lambda _: self.actions.set_visible_child_name("states"))
            picker.pack_start(back, True, True, 0)
            self.species_buttons.append(back)

            self.actions.add_named(actions, "states")
            self.actions.add_named(picker, "species")
            content.pack_start(self.actions, False, False, 0)
        else:
            content = row
        margin = 7 if is_touch else max(10, min(24, width // 80))
        content.set_margin_start(margin)
        content.set_margin_end(margin)
        content.set_margin_top(margin)
        content.set_margin_bottom(margin)
        self.widget.add(content)

    @staticmethod
    def action_button(title):
        button = Gtk.Button(label=title)
        button.set_size_request(-1, 45)
        button.get_child().set_justify(Gtk.Justification.CENTER)
        button.get_style_context().add_class("ion-action")
        return button

    def set_state(self, state, species=None, *, sweeping=False, tuned_isotope=None):
        inferred_sweep = sweeping and state in ("unknown", "empty")
        self.title.set_text("Trapping sweep" if inferred_sweep else ION_STATES[state])
        detail = ""
        if state != "trapped" and tuned_isotope:
            detail = f"{SPECIES[tuned_isotope]} tuning"
        elif state == "trapping":
            detail = "Ablation pulse"
        elif state == "trapped" and species:
            raised = f'<span size="72%" rise="{self.isotope_rise}">'
            detail = f"{raised}{species}</span>Ba{raised}+</span>"
        if sweeping and state == "trapped":
            detail += " · Red sweep" if detail else "Red sweep"
        self.detail.set_markup(detail)
        self.detail.set_visible(bool(detail))
        graphic_state = state if state in ("trapping", "trapped") else "empty"
        if graphic_state != self.graphic_state:
            self.graphic.set_state(graphic_state)
            self.graphic_state = graphic_state

        style = self.widget.get_style_context()
        for name in ION_STATES:
            style.remove_class(name)
        style.add_class("trapping" if inferred_sweep else state)
        for name, button in self.buttons.items():
            if name == state:
                button.get_style_context().add_class("selected")
            else:
                button.get_style_context().remove_class("selected")
