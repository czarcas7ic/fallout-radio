# Fallout Radio

A Raspberry Pi-powered internet radio that streams YouTube audio through a vintage radio chassis, featuring a retro Pip-Boy style web interface.

## Features

- Stream YouTube audio via mpv + yt-dlp
- Rotary encoder control for station switching and volume
- Retro Pip-Boy themed web interface
- Station packs for organizing multiple playlists
- Real-time WebSocket updates
- Tuning sound effects when switching stations
- EBU R128 loudness normalization for consistent volume across stations
- Smart caching for fast station switching and startup
- Auto-start playback on boot (turn volume to 0 to turn off)

## Hardware Requirements

- Raspberry Pi (3B+ or newer recommended)
- MAX98357A I2S DAC amplifier (mono setup)
- Speaker (4-8 ohm, 1.6W+ rating)
- 2x Rotary encoders with push buttons (optional)
- Vintage radio chassis (for aesthetics)

## Hardware Assembly Guide

### Components

| Component       | Model               | Notes                                      |
| --------------- | ------------------- | ------------------------------------------ |
| Raspberry Pi    | Zero 2 W (or 3B+/4) | Any Pi with GPIO and WiFi                  |
| I2S DAC/Amp     | MAX98357A           | Mono setup, 3W max output                  |
| Speaker         | 4Ω 1.6W             | Vintage radio speaker (keep volume < 60%)  |
| Station Encoder | KY-040              | Rotary encoder with push button            |
| Volume Encoder  | KY-040              | Rotary encoder with push button            |
| Power Supply    | 5V 2.5A+            | Micro USB or USB-C depending on Pi         |

### Pin Reference Diagram

![Raspberry Pi Zero J8 Header Pinout](j8header-zero-large.png)

```
Raspberry Pi GPIO Header (40-pin)
(Looking at Pi with USB ports facing down)

                    3V3  (1)  (2)  5V
                  GPIO2  (3)  (4)  5V
                  GPIO3  (5)  (6)  GND
                  GPIO4  (7)  (8)  GPIO14
                    GND  (9)  (10) GPIO15
Station CLK ─── GPIO17 (11)  (12) GPIO18 ─── MAX98357A BCLK
Station DT ──── GPIO27 (13)  (14) GND ─────── Station Encoder GND
Station SW ──── GPIO22 (15)  (16) GPIO23
                    3V3 (17)  (18) GPIO24
                 GPIO10 (19)  (20) GND
                  GPIO9 (21)  (22) GPIO25
                 GPIO11 (23)  (24) GPIO8
                    GND (25)  (26) GPIO7
                  GPIO0 (27)  (28) GPIO1
                  GPIO5 (29)  (30) GND
                  GPIO6 (31)  (32) GPIO12
                 GPIO13 (33)  (34) GND ─────── MAX98357A GND
                 GPIO19 (35)  (36) GPIO16 ─── Volume CLK
Volume DT ──── GPIO26  (37)  (38) GPIO20 ─── Volume SW
                    GND (39)  (40) GPIO21 ─── MAX98357A DIN
```

### Wiring: MAX98357A I2S DAC (Mono Setup)

A single MAX98357A board configured for mono output (L+R mixed).

```
                        Raspberry Pi
                        ────────────
MAX98357A
   VIN  ─────────────── Pin 2 or 4 (5V)
   GND  ─────────────── Pin 34 (GND)
   DIN  ─────────────── Pin 40 (GPIO 21 / PCM_DOUT)
  BCLK  ─────────────── Pin 12 (GPIO 18 / PCM_CLK)
   LRC  ─────────────── Pin 35 (GPIO 19 / PCM_FS)
    SD  ─────────────── Not connected (floating = mono L+R mix)
```

**SD Pin Channel Selection (reference):**

- SD pin floating = Mono (L+R mixed) ← recommended for vintage radio
- SD pin to GND = Left channel only
- SD pin to VIN = Right channel only

**Speaker Connection:**

- Solder vintage speaker to the `+` and `-` terminals on the MAX98357A
- Use 4-8Ω speaker
- Keep volume below 60% if using a 1.6W speaker (MAX98357A outputs up to 3W)

### Wiring: Station Rotary Encoder (KY-040)

Controls station switching. Rotate to change stations (button unused).

```
KY-040 Encoder     Raspberry Pi
──────────────     ────────────
   CLK  ─────────── Pin 11 (GPIO 17)
    DT  ─────────── Pin 13 (GPIO 27)
    SW  ─────────── Pin 15 (GPIO 22)
     +  ─────────── Pin 17 (3.3V)
   GND  ─────────── Pin 14 (GND)
```

### Wiring: Volume Rotary Encoder (KY-040)

Controls volume. Press button toggles power on/off.

```
KY-040 Encoder     Raspberry Pi
──────────────     ────────────
   CLK  ─────────── Pin 36 (GPIO 16)
    DT  ─────────── Pin 37 (GPIO 26)
    SW  ─────────── Pin 38 (GPIO 20)
     +  ─────────── Pin 17 (3.3V)
   GND  ─────────── Pin 39 (GND)
```

### Complete Wiring Summary

| Component           | Pin  | Raspberry Pi Pin | GPIO    |
| ------------------- | ---- | ---------------- | ------- |
| DAC VIN             | VIN  | Pin 2 or 4       | 5V      |
| DAC GND             | GND  | Pin 34           | GND     |
| DAC DIN             | DIN  | Pin 40           | GPIO 21 |
| DAC BCLK            | BCLK | Pin 12           | GPIO 18 |
| DAC LRC             | LRC  | Pin 35           | GPIO 19 |
| DAC SD              | SD   | Not connected    | (float) |
| Station Encoder CLK | CLK  | Pin 11           | GPIO 17 |
| Station Encoder DT  | DT   | Pin 13           | GPIO 27 |
| Station Encoder SW  | SW   | Pin 15           | GPIO 22 |
| Station Encoder +   | +    | Pin 17           | 3.3V    |
| Station Encoder GND | GND  | Pin 14           | GND     |
| Volume Encoder CLK  | CLK  | Pin 36           | GPIO 16 |
| Volume Encoder DT   | DT   | Pin 37           | GPIO 26 |
| Volume Encoder SW   | SW   | Pin 38           | GPIO 20 |
| Volume Encoder +    | +    | Pin 17           | 3.3V    |
| Volume Encoder GND  | GND  | Pin 39           | GND     |

### Assembly Tips

1. **Use Dupont jumper wires** for prototyping - female-to-female for connecting to both Pi header and encoder pins

2. **Solder header pins** to the MAX98357A board if not pre-soldered

3. **Test audio first** before adding encoders:

   ```bash
   speaker-test -t wav -c 1
   ```

4. **Encoder orientation matters** - if rotation is reversed, swap CLK and DT wires

5. **Secure connections** - hot glue or heat shrink tubing prevents wires from loosening

6. **Power considerations**:
   - Use a quality 5V 2.5A+ power supply
   - If experiencing audio crackling, try a better power supply
   - MAX98357A draws power from 5V, encoders from 3.3V

7. **Volume limit for vintage speakers**:
   - If using a 1.6W speaker, keep volume below 60% to avoid damage
   - The MAX98357A can output up to 3W, which would overdrive a 1.6W speaker

### Physical Layout Example

```
┌─────────────────────────────────────────────┐
│              Vintage Radio Case             │
│                                             │
│  ┌─────────┐                  ┌─────────┐   │
│  │ Station │                  │ Volume  │   │
│  │ Encoder │                  │ Encoder │   │
│  └────┬────┘                  └────┬────┘   │
│       │                            │        │
│       │      ┌──────────────┐      │        │
│       └──────┤ Raspberry Pi ├──────┘        │
│              │   Zero 2 W   │               │
│              └──────┬───────┘               │
│                     │                       │
│              ┌──────┴──────┐                │
│              │  MAX98357A  │                │
│              │   (MONO)    │                │
│              └──────┬──────┘                │
│                     │                       │
│           ┌─────────┴─────────┐             │
│           │  Vintage Speaker  │             │
│           │    (4Ω 1.6W)      │             │
│           └───────────────────┘             │
│                                             │
└─────────────────────────────────────────────┘
```

## Raspberry Pi Setup (From Scratch)

If you're starting with a fresh Pi and SD card, follow these steps first.

### 1. Download Raspberry Pi Imager

Download and install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on your computer.

### 2. Flash the SD Card

1. Insert your SD card into your computer
2. Open Raspberry Pi Imager
3. Click **Choose Device** → Select your Pi model (e.g., Raspberry Pi Zero 2 W)
4. Click **Choose OS** → **Raspberry Pi OS (other)** → **Raspberry Pi OS Lite (64-bit)**
   - Use the Lite version (no desktop) for best performance
5. Click **Choose Storage** → Select your SD card
6. Click **Next**

### 3. Configure Settings (Important!)

When prompted "Would you like to apply OS customisation settings?", click **Edit Settings**:

**General tab:**

- Set hostname: `fallout-radio`
- Set username and password (remember these!)
- Configure wireless LAN:
  - SSID: Your WiFi network name (**must be 2.4GHz, not 5GHz**)
  - Password: Your WiFi password
  - Country: Your country code (e.g., US)

> **Note:** The Raspberry Pi Zero 2 W only supports 2.4GHz WiFi. If your router has both 2.4GHz and 5GHz networks, make sure to use the 2.4GHz one (often has "2G" in the name or no suffix).

**Services tab:**

- Enable SSH: ✓
- Use password authentication

Click **Save**, then **Yes** to apply settings, then **Yes** to flash.

### 4. First Boot

1. Insert the SD card into your Pi
2. Connect power - wait 1-2 minutes for first boot
3. Find your Pi on the network:

   ```bash
   # On Mac/Linux:
   ping fallout-radio.local

   # Or check your router's connected devices
   ```

### 5. Connect via SSH

```bash
ssh pi@fallout-radio.local
# Or use the username you set in Imager
```

Enter the password you configured. You're now ready to install Fallout Radio!

## Installation

### Quick Install (Raspberry Pi)

```bash
git clone https://github.com/czarcas7ic/fallout-radio.git
cd fallout-radio
./install.sh
```

The installer will:

1. Install system dependencies (mpv, python3, etc.)
2. Set up Python virtual environment
3. Configure I2S audio overlay for MAX98357A
4. Install and enable the systemd service

### Manual Installation

```bash
# Install dependencies
sudo apt-get update
sudo apt-get install python3 python3-pip python3-venv mpv libsdl2-mixer-2.0-0
sudo pip3 install yt-dlp

# Clone and setup
git clone https://github.com/yourusername/fallout-radio.git
cd fallout-radio
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure I2S audio (add to /boot/config.txt or /boot/firmware/config.txt)
# dtoverlay=max98357a

# Run
python -m app.main
```

### Development (macOS/Linux)

```bash
# Install mpv
brew install mpv  # macOS
# or: sudo apt install mpv  # Linux

# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt

# Run (uses mock GPIO handler)
python -m app.main
```

## Usage

### Web Interface

Access the web interface at `http://<pi-ip>:5000`

- **Now Playing**: View current station, switch stations, adjust volume
- **Packs**: Manage station packs (create, edit, delete)
- **Settings**: Configure default volume

### Service Management

```bash
# Start/stop/restart
sudo systemctl start fallout-radio
sudo systemctl stop fallout-radio
sudo systemctl restart fallout-radio

# View status
sudo systemctl status fallout-radio

# View logs
journalctl -u fallout-radio -f
```

### Physical Controls

- **Station Encoder**: Rotate to switch stations (button does nothing)
- **Volume Encoder**: Rotate to adjust volume, press to cycle through packs
  - Turn volume to 0 → Radio turns off
  - Turn volume up from 0 → Radio turns on (resumes last station)
  - Press button → Switch to next pack (wraps from last to first)

## Configuration

### Station Packs

Station packs are stored in `data/packs.json`. Each pack contains:

- `id`: Unique identifier
- `name`: Display name
- `stations`: Array of stations with `id`, `name`, and `url`

Example:

```json
{
  "packs": [
    {
      "id": "fallout",
      "name": "Fallout Radio",
      "stations": [
        {
          "id": "gnr",
          "name": "Galaxy News Radio",
          "url": "https://www.youtube.com/watch?v=..."
        }
      ]
    }
  ],
  "active_pack_id": "fallout"
}
```

### Settings

Settings are stored in `data/settings.json`:

- `default_volume`: Initial volume (0-100), default: 40
- `max_volume`: Maximum volume limit (1-100), default: 100. Use to protect low-wattage speakers (e.g., 60 for a 1.6W speaker with 3W amp)
- `static_volume`: Tuning static volume as percentage of main volume (0-100), default: 60
- `wrap_stations`: Whether to wrap around when reaching first/last station, default: true
- `loudness_normalization`: EBU R128 loudness normalization for consistent volume across stations, default: true

## API Reference

### REST Endpoints

| Method | Endpoint                       | Description                                              |
| ------ | ------------------------------ | -------------------------------------------------------- |
| GET    | `/api/state`                   | Get current radio state                                  |
| GET    | `/api/packs`                   | List all packs                                           |
| POST   | `/api/packs`                   | Create new pack                                          |
| GET    | `/api/packs/:id`               | Get pack details                                         |
| PUT    | `/api/packs/:id`               | Update pack                                              |
| DELETE | `/api/packs/:id`               | Delete pack                                              |
| POST   | `/api/packs/:id/stations`      | Add station                                              |
| PUT    | `/api/packs/:id/stations/:sid` | Update station                                           |
| DELETE | `/api/packs/:id/stations/:sid` | Delete station                                           |
| POST   | `/api/packs/:id/activate`      | Set active pack                                          |
| GET    | `/api/settings`                | Get settings                                             |
| PUT    | `/api/settings`                | Update settings                                          |
| POST   | `/api/control/volume`          | Set volume `{"level": 50}`                               |
| POST   | `/api/control/station`         | Switch station `{"direction": "next"}` or `{"index": 1}` |

### WebSocket Events

| Event            | Direction        | Description                |
| ---------------- | ---------------- | -------------------------- |
| `state_update`   | Server -> Client | Radio state changed        |
| `get_state`      | Client -> Server | Request current state      |
| `set_volume`     | Client -> Server | Set volume `{"level": 50}` |
| `switch_station` | Client -> Server | Switch station             |
| `activate_pack`  | Client -> Server | Activate pack              |

## Project Structure

```
fallout-radio/
├── app/
│   ├── __init__.py
│   ├── main.py           # Flask app and routes
│   ├── audio_player.py   # mpv and pygame audio
│   ├── radio_core.py     # Core state management
│   ├── gpio_handler.py   # Rotary encoder handling
│   ├── config.py         # Configuration helpers
│   ├── static/
│   │   ├── css/style.css # Pip-Boy themed CSS
│   │   ├── js/app.js     # Frontend JavaScript
│   │   └── sounds/       # Sound effects
│   └── templates/        # Jinja2 templates
├── data/
│   ├── packs.json        # Station packs
│   └── settings.json     # User settings
├── install.sh            # Pi installation script
├── requirements.txt      # Pi dependencies
└── requirements-dev.txt  # Dev dependencies
```

## Troubleshooting

### No audio output

1. Check I2S DAC wiring
2. Verify `dtoverlay=max98357a` in config.txt
3. Reboot after config changes
4. Test with: `speaker-test -t wav -c 1`
5. Ensure SD pin is floating (not connected) for mono output

### YouTube streams not working

1. Update yt-dlp: `pip install -U yt-dlp`
2. Check internet connectivity
3. Some videos may be region-locked or age-restricted

### Web interface not loading

1. Check service status: `systemctl status fallout-radio`
2. Check logs: `journalctl -u fallout-radio -f`
3. Verify port 5000 is not in use

### GPIO not responding

1. Ensure running on Raspberry Pi
2. Check encoder wiring matches pin configuration
3. Verify gpiozero and RPi.GPIO are installed

## License

MIT License
