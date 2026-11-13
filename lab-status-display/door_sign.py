"""Run the manual two-screen sign from the Pi's Wayland desktop."""

import fcntl
import os
import struct
from pathlib import Path

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk


TOUCH_NAME = "ADS7846 Touchscreen"
EVIOCGRAB = 0x40044590
INPUT_EVENT = struct.Struct("@llHHi")
EV_SYN, SYN_REPORT, SYN_DROPPED = 0, 0, 3
EV_KEY, BTN_TOUCH = 1, 330
EV_ABS, ABS_X, ABS_Y = 3, 0, 1


def open_touchscreen():
    devices = [
        Path("/dev/input") / entry.name
        for entry in Path("/sys/class/input").glob("event*")
        if (entry / "device/name").read_text().strip() == TOUCH_NAME
    ]
    if len(devices) != 1:
        raise RuntimeError(f"Expected one {TOUCH_NAME}, found {len(devices)}")
    fd = os.open(devices[0], os.O_RDONLY | os.O_NONBLOCK)
    try:
        # Route touches to the control panel while it is running.
        fcntl.ioctl(fd, EVIOCGRAB, 1)
    except OSError:
        os.close(fd)
        raise
    print(f"Reading touchscreen at {devices[0]}", flush=True)
    return fd


def watch_taps(fd, on_tap, on_disconnect, *, with_position=False):
    pressed = False
    dropped = False
    position = [None, None]

    def read_events(source, condition):
        nonlocal pressed, dropped
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            on_disconnect()
            return False
        try:
            events = os.read(source, INPUT_EVENT.size * 64)
        except BlockingIOError:
            return True
        except OSError:
            events = b""
        if not events:
            on_disconnect()
            return False

        for _, _, event_type, code, value in INPUT_EVENT.iter_unpack(events):
            if (event_type, code) == (EV_SYN, SYN_DROPPED):
                pressed = False
                dropped = True
                position[:] = [None, None]
            elif (event_type, code) == (EV_SYN, SYN_REPORT):
                dropped = False
            elif not dropped and event_type == EV_ABS and code in (ABS_X, ABS_Y):
                position[code] = value
            elif not dropped and (event_type, code) == (EV_KEY, BTN_TOUCH):
                if value == 1:
                    pressed = True
                elif value == 0 and pressed:
                    pressed = False
                    if not with_position:
                        on_tap()
                    elif None not in position:
                        on_tap(*position)
        return True

    return GLib.io_add_watch(
        fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, read_events
    )


def fullscreen_window(title, child, screen, index):
    window = Gtk.Window(title=title)
    window.set_decorated(False)
    window.connect("destroy", Gtk.main_quit)
    window.add(child)
    window.fullscreen_on_monitor(screen, index)
    return window


def label(text, style):
    widget = Gtk.Label(label=text)
    widget.set_justify(Gtk.Justification.CENTER)
    widget.get_style_context().add_class(style)
    return widget


def run():
    display = Gdk.Display.get_default()
    screen = Gdk.Screen.get_default()
    if display is None or display.get_n_monitors() != 2:
        raise RuntimeError("The sign needs the touchscreen and HDMI in an extended desktop")
    monitors = [display.get_monitor(index) for index in range(2)]
    geometries = [monitor.get_geometry() for monitor in monitors]
    touchscreen = [
        index for index, geometry in enumerate(geometries)
        if (geometry.width, geometry.height) == (480, 320)
    ]
    if len(touchscreen) != 1:
        raise RuntimeError("Expected one 480 x 320 touchscreen in landscape orientation")
    touch_index = touchscreen[0]
    door_index = 1 - touch_index
    door_size = geometries[door_index]
    sign_font = min(door_size.width // 9, door_size.height // 5)

    button = Gtk.ToggleButton()
    button.get_style_context().add_class("controller")
    button_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    button_box.set_valign(Gtk.Align.CENTER)
    button_box.pack_start(label("LAB DOOR SIGN", "controller-label"), False, False, 0)
    action = label("", "action")
    status = label("", "status")
    button_box.pack_start(action, False, False, 0)
    button_box.pack_start(status, False, False, 0)
    button.add(button_box)

    door = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    door.set_valign(Gtk.Align.CENTER)
    door.pack_start(label("36 W CLASS 4 LASER  ·  MANUAL DEMO SIGN", "door-label"), False, False, 0)
    headline = label("", "headline")
    instructions = label("", "instructions")
    door.pack_start(headline, False, False, 0)
    door.pack_start(instructions, False, False, 0)

    controller_window = fullscreen_window("Touch controller", button, screen, touch_index)
    door_window = fullscreen_window("Laser door sign", door, screen, door_index)
    door_style = door_window.get_style_context()
    door_style.add_class("door")
    provider = Gtk.CssProvider()
    provider.load_from_data(f"""
        .controller {{ background: #153c39; color: #f2fff9; border-radius: 0; }}
        .controller:checked {{ background: #641e29; color: #fff4ed; }}
        .controller:disabled {{ background: #283443; color: #e1ebf4; }}
        .controller-label, .status {{ font-size: 19px; }}
        .action {{ font-size: 38px; font-weight: bold; }}
        .door {{ background: #101c2b; color: #f1f6fc; }}
        .door.active {{ background: #78131c; color: #fff7ec; }}
        .door.offline {{ background: #593e14; color: #fff5de; }}
        .controller label {{ color: #f2fff9; font-family: "DejaVu Sans"; }}
        .controller:checked label {{ color: #fff4ed; }}
        .controller:disabled label {{ color: #e1ebf4; }}
        .door label {{ color: #f1f6fc; font-family: "DejaVu Sans"; }}
        .door.active label {{ color: #fff7ec; }}
        .door.offline label {{ color: #fff5de; }}
        .door-label {{ font-size: {max(16, sign_font // 5)}px; font-weight: bold; }}
        .headline {{ font-size: {sign_font}px; font-weight: bold; }}
        .door.offline .headline {{ font-size: {sign_font * 3 // 4}px; }}
        .instructions {{ font-size: {max(17, sign_font // 4)}px; }}
    """.encode())
    Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def update_sign(toggle):
        active = toggle.get_active()
        state = "ON" if active else "OFF"
        action.set_text("Turn sign off" if active else "Turn sign on")
        status.set_text(f"Sign shows LASER {state}")
        headline.set_text(f"LASER {state}")
        if active:
            door_style.add_class("active")
            instructions.set_text(
                "DANGER · Do not enter without approved laser eyewear.\nAuthorized personnel only."
            )
        else:
            door_style.remove_class("active")
            instructions.set_text("Follow posted lab entry procedures.")
        print(f"Sign {state}", flush=True)

    def touch_disconnected():
        button.set_sensitive(False)
        action.set_text("Touch unavailable")
        status.set_text("Check the touchscreen connection")
        door_style.remove_class("active")
        door_style.add_class("offline")
        headline.set_text("STATUS UNKNOWN")
        instructions.set_text("Contact the lab operator before entering.")

    def quit_on_escape(_window, event):
        if event.keyval == Gdk.KEY_Escape:
            Gtk.main_quit()
            return True
        return False

    fd = open_touchscreen()
    try:
        watch_taps(fd, lambda: button.set_active(not button.get_active()), touch_disconnected)
        button.connect("toggled", update_sign)
        update_sign(button)
        display.connect("monitor-removed", lambda *_: Gtk.main_quit())
        for window in (controller_window, door_window):
            window.connect("key-press-event", quit_on_escape)
            window.show_all()
        Gtk.main()
    finally:
        os.close(fd)


if __name__ == "__main__":
    run()
