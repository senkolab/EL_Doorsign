# QuDit Lab door display v1.2.0

The lab touchscreen reports laser, ion trap, and experiment status. A second Raspberry Pi shows the door dashboard over HDMI. The Windows app can update the same status from a PC on the lab network.

## Windows remote control

[Download QuDit Lab Remote for Windows x64](https://github.com/GauravTathed/DoorSignGUI/releases/latest/download/QuDit-Lab-Remote-Windows-x64.zip)

Extract the ZIP and run `QuDit Lab Remote.exe`. Connect to `welcome-pi.local` on port 22 with your Pi account. The app verifies the touchscreen Pi’s SSH host key. If the Pi is reimaged or replaced, verify its new ED25519 fingerprint and update `PI_KEY` in `pc_controller.py` before rebuilding the app.

Turn **1762 nm** ON to enable the separate **1762 nm lock** control. The yellow door notice is shown while 1762 nm is ON and LOCKED. The red 532 nm warning follows the Paladin shutter once its feed is configured. Until then, it follows the operator-reported Class 4 status. These controls update the sign. Use the lab’s approved signage, access controls, and interlocks for laser safety.

## Raspberry Pi installation

Place the contents of this directory in `~/lab-status-display` on each Pi. Install GTK 3 introspection and Python 3 GObject bindings on both systems. The controller also needs `python3-cairo`, `wlr-randr`, and a Raspberry Pi OS desktop using Wayland. The relay viewer supports Python 3.5 and uses the X11 desktop on the deployed Pi 3 Model B.

### Touchscreen controller

On the Raspberry Pi 4 with the 480×320 SPI screen and ADS7846-compatible touch controller, add the following to the `[all]` section of `/boot/firmware/config.txt` and reboot. Keep the existing `dtparam=spi=on` setting.

```ini
dtoverlay=piscreen,drm,rotate=90,speed=16000000
```

Sign in to the graphical desktop as a user with access to the input device and run `~/lab-status-display/start-dashboard.sh`. Tap the four targets if calibration is requested. On the installed unit the launcher sets `SPI-1` to 480×320 landscape at 30 Hz. With just the SPI display attached, the app publishes a 1366×768 door feed. It can also use a directly attached HDMI display in an extended desktop.

The temperature chart reads the three lab sensor series from InfluxDB. The configured endpoint and database are `SOURCE` and `DATABASE` in `temperature_display.py`.

The launcher enables automatic status from IonControl on `senkolab-laser.local:8080`. Set `QUDIT_WAVEMETER_HOST` to override the hostname or set it to an empty string to launch with manual controls. The Pi only reads `/?channel=N` and `/references`; it never changes a laser setpoint.

- **493, 650, and 554 nm** (channels 7, 4, and 3) show **LOCKED** when regulation is active and the measured frequency is less than 5 MHz from the live reference. If both cooling lasers are more than 5 and up to 500 MHz red of their usual 607.432010 and 461.311350 THz values, they show **SWEEP** and the ion panel indicates trapping activity. The reading indicates red detuning, which can also occur when both lasers are held at fixed red offsets.
- **554 nm** also supplies a tuning hint: within ±30 MHz of 541.433326 THz suggests Ba-137, and within ±30 MHz of 541.433050 THz suggests Ba-138. Use the ion controls to confirm ion presence and isotope.
- **614 nm** (channel 8) is free-running. It shows **IN RANGE** between 487.98800 and 487.99150 THz, inclusive, and **MODE HOP** outside that range. It does not have a lock badge.
- Invalid, unavailable, or unchanged measurements show **UNKNOWN**. The API does not timestamp readings, so the Pi requires a change within the last 12 seconds before trusting a measurement. If the measurement is valid but the lock reference or regulation status is unavailable, the lock badge shows **LOCK UNKNOWN**.

The [Paladin Laser Controller](https://github.com/GauravTathed/Paladin-Laser-Controller) can publish its real shutter readback via a dedicated SSH key restricted to `paladin_shutter.py`. The first valid reading enables automatic shutter status across restarts. **OPEN** displays the Class 4 warning; **CLOSED** restores the temperature plot. If the reading is lost or more than eight seconds old, the sign displays **UNKNOWN** and tells visitors to contact the lab operator. Shutter closed does not mean the laser itself is off.

Simulator readings are shown separately as **SIM OPEN** or **SIM CLOSED**. A simulator open reading can show a labeled test notice when the manually reported shutter is off. Real shutter warnings stay visible. A test PC can use the receiver's `--simulator-only` option in its SSH key's forced command. QuDit Lab Remote shows the same readings and disables edits to the automatic tiles.

To connect the hardware feed, open [Paladin Laser Controller v1.2.0](https://github.com/GauravTathed/Paladin-Laser-Controller/releases/tag/v1.2.0). Enter the Pi hostname or IP, SSH port, and Pi account username and password, then click **Connect to Pi**. Paladin reports the shutter status while both the Pi and COM port are connected. On an existing touchscreen Pi, copy the updated dashboard files over the current installation and retain `touch-calibration.json`, `.paladin-enabled`, and the Pi's SSH configuration. Restart the dashboard when the sign can be briefly taken offline.

### HDMI relay

1. On the relay, generate a dedicated SSH key with `ssh-keygen -t ed25519 -f ~/.ssh/qudit-door-relay`. Leave its passphrase empty for unattended startup and keep the private key on the relay.
2. On the controller, add the relay's **public** key to the `pi` user's `~/.ssh/authorized_keys`. Prefix the public key line with `restrict,command="/usr/bin/python3 -B /home/pi/lab-status-display/door_feed.py" `, including the space after the closing quote. The key then serves only the door feed.
3. On the relay, write the controller's verified ED25519 public host key to `~/.ssh/qudit-door-known-hosts` in the form `welcome-pi.local ssh-ed25519 <public-key-data>`. The host key is in `/etc/ssh/ssh_host_ed25519_key.pub` on the controller. The relay reconnects automatically after a network interruption and shows **DO NOT ENTER** while status is unavailable.
4. For the deployed 1366×768 HDMI monitor on the legacy relay OS, set `hdmi_group=2`, `hdmi_mode=81`, `disable_overscan=1`, and `display_hdmi_rotate=2` in `/boot/config.txt`. Use the appropriate mode for any replacement monitor. Connect HDMI to the relay and run `~/lab-status-display/start-door-display.sh` from the graphical desktop or SSH.

### Automatic startup

Enable desktop autologin for the dashboard user on each Pi. Create `~/.config/autostart/qudit-door.desktop` on each Pi, selecting that Pi's launcher in `Exec`.

```ini
[Desktop Entry]
Type=Application
Name=QuDit Lab door status
Exec=/home/pi/lab-status-display/start-dashboard.sh
Terminal=false
```

Use `/home/pi/lab-status-display/start-door-display.sh` on the relay. Status starts at **UNKNOWN** after the controller reboots so the operator can report current conditions.

## Source files

- `qudit_dashboard.py`, `door_sign.py`, `ion_display.py`, and `temperature_display.py` implement the Pi dashboard, touchscreen, and door graphics. `ion-trapped.gif` is the optional trapped-ion clip.
- `door_feed.py`, `relay_display.py`, and `remote_control.py` provide the read-only door feed, HDMI viewer, and SSH interface for the Windows controller.
- `pc_controller.py` is the Windows app source. It uses Tkinter and Paramiko. To build an executable, install Paramiko and PyInstaller into a Windows Python environment and run the following from this directory.

  ```powershell
  python -m PyInstaller --onefile --windowed --name "QuDit Lab Remote" --icon qudit-lab.ico --add-data "qudit-lab.ico:." pc_controller.py
  ```
- `server.py`, `index.html`, `app.js`, and `styles.css` are the original browser prototype. Run `python3 server.py` and visit `http://127.0.0.1:8765/` to try it locally.
