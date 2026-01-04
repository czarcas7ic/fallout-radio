# Fallout Radio Pi - Project Plan

## Overview

A Raspberry Pi-powered internet radio that streams YouTube audio through a vintage radio chassis. Features a rotary encoder for station switching with realistic tuning sounds, a second rotary encoder for volume control, and a retro-themed web interface for managing station packs.

## Hardware

- Raspberry Pi Zero 2 W
- MAX98357A I2S DAC/Amplifier
- 3" 4Ω speaker
- 2x KY-040 rotary encoders (station selector + volume)
- 5V 2.5A power supply

## Software Stack

- **OS**: Raspberry Pi OS Lite (64-bit)
- **Audio Streaming**: mpv with yt-dlp backend
- **Sound Effects**: pygame.mixer (low-latency local audio)
- **Backend**: Python with Flask + Flask-SocketIO
- **Frontend**: HTML/CSS/JS with retro styling
- **Process Manager**: systemd

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Raspberry Pi                           │
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐ │
│  │   Flask     │    │   Radio     │    │      mpv        │ │
│  │   Web UI    │◄──►│   Core      │◄──►│   (yt-dlp)      │ │
│  │  :5000      │    │             │    │                 │ │
│  └─────────────┘    └──────▲──────┘    └─────────────────┘ │
│                            │                               │
│                     ┌──────┴──────┐                        │
│                     │    GPIO     │                        │
│                     │  Handlers   │                        │
│                     └──────▲──────┘                        │
│                            │                               │
└────────────────────────────┼───────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
        ┌─────┴─────┐                ┌──────┴────┐
        │  Station  │                │  Volume   │
        │  Encoder  │                │  Encoder  │
        └───────────┘                └───────────┘
```

## File Structure

```
/home/pi/fallout-radio/
├── app/
│   ├── __init__.py
│   ├── main.py                 # Flask app entry point
│   ├── radio_core.py           # Core radio logic (playback, station management)
│   ├── gpio_handler.py         # Rotary encoder handling
│   ├── audio_player.py         # mpv wrapper
│   ├── config.py               # Configuration management
│   └── static/
│       ├── css/
│       │   └── style.css       # Retro UI styling
│       ├── js/
│       │   └── app.js          # Frontend interactivity
│       ├── sounds/
│       │   └── tuning.mp3      # Brief tuning blip sound
│       └── images/
│           └── dial.svg        # Tuner dial graphic
│   └── templates/
│       ├── base.html           # Base template with navigation
│       ├── now_playing.html    # Current station display
│       ├── packs.html          # Station pack management
│       ├── pack_editor.html    # Edit individual pack
│       └── settings.html       # App settings
├── data/
│   ├── packs.json              # Station pack definitions
│   └── settings.json           # User settings
├── scripts/
│   ├── install.sh              # Installation script
│   └── setup_gpio.sh           # GPIO configuration
├── systemd/
│   └── fallout-radio.service   # systemd service file
├── requirements.txt
└── README.md
```

## Data Models

### packs.json

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
          "url": "https://www.youtube.com/watch?v=XXXXX",
          "type": "live"
        },
        {
          "id": "mojave",
          "name": "Mojave Music Radio",
          "url": "https://www.youtube.com/watch?v=XXXXX",
          "type": "video"
        }
      ]
    },
    {
      "id": "lofi",
      "name": "Lofi Beats",
      "stations": []
    }
  ],
  "active_pack_id": "fallout"
}
```

### settings.json

```json
{
  "default_volume": 50,
  "wrap_stations": false
}
```

## GPIO Pin Assignments

| Component | Pin | GPIO |
|-----------|-----|------|
| Station Encoder CLK | 11 | GPIO 17 |
| Station Encoder DT | 12 | GPIO 18 |
| Station Encoder SW | 13 | GPIO 27 |
| Volume Encoder CLK | 15 | GPIO 22 |
| Volume Encoder DT | 16 | GPIO 23 |
| Volume Encoder SW | 18 | GPIO 24 |
| MAX98357A BCLK | 12 | GPIO 18 |
| MAX98357A LRCLK | 35 | GPIO 19 |
| MAX98357A DIN | 40 | GPIO 21 |

Note: Station encoder and MAX98357A share GPIO 18. Will need to reassign station encoder CLK to GPIO 5 (pin 29) or another free pin.

### Revised GPIO (avoiding conflicts):

| Component | Pin | GPIO |
|-----------|-----|------|
| Station Encoder CLK | 29 | GPIO 5 |
| Station Encoder DT | 31 | GPIO 6 |
| Station Encoder SW | 33 | GPIO 13 |
| Volume Encoder CLK | 36 | GPIO 16 |
| Volume Encoder DT | 37 | GPIO 26 |
| Volume Encoder SW | 38 | GPIO 20 |

## Core Modules

### audio_player.py

Responsibilities:
- Start/stop mpv subprocess for YouTube streams
- Handle YouTube URL extraction via yt-dlp
- Play local sound effects via pygame.mixer (low-latency)
- Volume control via amixer
- Detect stream failures

Key methods:
```python
class AudioPlayer:
    def play_url(url: str) -> bool           # Start streaming a YouTube URL
    def play_tuning_sound() -> None          # Play brief tuning blip (pygame)
    def stop() -> None                       # Stop current stream
    def set_volume(level: int) -> None       # 0-100
    def get_volume() -> int
    def is_playing() -> bool
    def get_stream_status() -> str           # "playing", "buffering", "stopped", "error"
```

### radio_core.py

Responsibilities:
- Manage current state (current pack, current station, volume)
- Handle station switching logic
- Coordinate tuning sounds based on settings
- Load/save packs and settings
- Expose state to web UI

Key methods:
```python
class RadioCore:
    def get_current_state() -> dict
    def switch_to_station(index: int) -> None
    def next_station() -> None
    def previous_station() -> None
    def set_active_pack(pack_id: str) -> None
    def get_packs() -> list
    def create_pack(name: str) -> Pack
    def update_pack(pack_id: str, data: dict) -> Pack
    def delete_pack(pack_id: str) -> None
    def update_settings(settings: dict) -> None
    def set_volume(level: int) -> None
```

### gpio_handler.py

Responsibilities:
- Monitor rotary encoder rotation and button presses
- Debounce inputs
- Call appropriate RadioCore methods

```python
class GPIOHandler:
    def __init__(radio_core: RadioCore)
    def start() -> None  # Start monitoring in background thread
    def stop() -> None
```

## Web UI Pages

### 1. Now Playing (`/`)

Display:
- Current pack name
- Visual tuner dial showing current station position
- Current station name
- Station status indicator (playing, buffering, error)
- Volume level indicator

Style:
- Retro vacuum tube / pip-boy aesthetic
- Amber or green monochrome color scheme
- Scanline overlay effect
- Vintage font (VT323 or similar)

### 2. Station Packs (`/packs`)

Display:
- List of all packs with station count
- Visual indicator for active pack
- Create new pack button
- Edit/delete options per pack

Actions:
- Click pack to set as active
- Edit button opens pack editor
- Delete button with confirmation

### 3. Pack Editor (`/packs/<pack_id>`)

Display:
- Pack name (editable)
- List of stations with drag handles for reordering
- Each station shows name, URL, type (live/video)
- Add station form

Actions:
- Edit pack name inline
- Drag to reorder stations
- Edit station (inline or modal)
- Delete station
- Add new station
- Save changes

### 4. Settings (`/settings`)

Options:
- **Station Wrap**: Toggle (wrap from last station to first, or stop at ends)
- **Default Volume**: Slider (0-100%)

## API Endpoints

### State

```
GET  /api/state              # Get current state (pack, station, volume, status)
```

### Packs

```
GET  /api/packs              # List all packs
POST /api/packs              # Create new pack
GET  /api/packs/<id>         # Get single pack
PUT  /api/packs/<id>         # Update pack
DELETE /api/packs/<id>       # Delete pack
POST /api/packs/<id>/activate  # Set as active pack
```

### Stations (within a pack)

```
POST /api/packs/<id>/stations           # Add station
PUT  /api/packs/<id>/stations/<sid>     # Update station
DELETE /api/packs/<id>/stations/<sid>   # Delete station
POST /api/packs/<id>/stations/reorder   # Reorder stations
```

### Settings

```
GET  /api/settings           # Get current settings
PUT  /api/settings           # Update settings
```

### Control

```
POST /api/control/volume     # Set volume {"level": 0-100}
POST /api/control/station    # Switch station {"index": 0-5, or "direction": "next"/"prev"}
```

## Tuning Behavior

### Station Positions

```
Position 0: OFF (complete silence)
Position 1: Station 1
Position 2: Station 2
Position 3: Station 3
Position 4: Station 4
Position 5: Station 5
(Additional positions if pack has more stations)
```

### Station Switching

1. User turns encoder (discrete clicks)
2. Brief tuning sound plays (via pygame, ~100-200ms)
3. Previous stream stops
4. New stream starts (or silence if OFF/empty pack)

The tuning sound plays instantly on encoder click, providing tactile audio feedback while the stream switches in the background.

### Stream Failure Handling

1. mpv process exits unexpectedly or reports error
2. AudioPlayer detects failure, updates status to "error"
3. Web UI shows "Connection Lost" status
4. User can manually retry by switching stations or refreshing

## UI Design Specifications

### Color Palette

```css
--bg-dark: #1a1a0e;        /* Dark olive background */
--bg-panel: #2a2a1a;       /* Panel background */
--text-primary: #00ff41;   /* Bright green (pip-boy style) */
--text-dim: #00aa2a;       /* Dimmed green */
--accent: #ffb000;         /* Amber accent */
--danger: #ff4444;         /* Error red */
--scanline: rgba(0,0,0,0.1);
```

### Typography

```css
@import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');

body {
  font-family: 'VT323', monospace;
  font-size: 18px;
}
```

### Visual Effects

- CRT scanline overlay (CSS pseudo-element with repeating gradient)
- Subtle screen flicker animation
- Glow effect on active elements
- Rounded "vacuum tube" style containers
- Nixie tube style numbers for volume/station display

### Tuner Dial Component

- Circular or semi-circular dial
- Station markers around the edge
- Illuminated indicator for current position
- Smooth animation when switching stations
- OFF position clearly marked

## Installation Process

### 1. Flash Raspberry Pi OS Lite

- Use Raspberry Pi Imager
- Enable SSH
- Configure WiFi
- Set hostname to `fallout-radio`

### 2. Run Install Script

```bash
curl -sSL https://raw.githubusercontent.com/.../install.sh | bash
```

Or manually:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3-pip python3-venv mpv git

# Install yt-dlp
sudo pip3 install yt-dlp --break-system-packages

# Enable I2S audio for MAX98357A
echo "dtparam=i2s=on" | sudo tee -a /boot/config.txt
echo "dtoverlay=max98357a" | sudo tee -a /boot/config.txt

# Disable onboard audio
sudo sed -i 's/dtparam=audio=on/dtparam=audio=off/' /boot/config.txt

# Clone project
git clone https://github.com/.../fallout-radio.git /home/pi/fallout-radio
cd /home/pi/fallout-radio

# Create venv and install Python deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Install systemd service
sudo cp systemd/fallout-radio.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable fallout-radio
sudo systemctl start fallout-radio

# Reboot for audio changes
sudo reboot
```

### 3. Access Web UI

Navigate to `http://fallout-radio.local:5000` from any device on the same network.

## Development Phases

### Phase 1: Core Audio Playback
- [ ] AudioPlayer class with mpv/yt-dlp
- [ ] Play YouTube URLs (live and regular)
- [ ] Volume control
- [ ] Basic error handling

### Phase 2: Radio Core Logic
- [ ] Pack and station data management
- [ ] Station switching logic
- [ ] Settings management
- [ ] State persistence

### Phase 3: GPIO Integration
- [ ] Rotary encoder reading
- [ ] Station encoder → station switching
- [ ] Volume encoder → volume control
- [ ] Debouncing

### Phase 4: Web UI - Backend
- [ ] Flask app setup with Flask-SocketIO
- [ ] All API endpoints
- [ ] WebSocket events for real-time state updates

### Phase 5: Web UI - Frontend
- [ ] Base template with retro styling
- [ ] Now Playing page
- [ ] Station Packs page
- [ ] Pack Editor page
- [ ] Settings page
- [ ] Tuner dial component

### Phase 6: Tuning Effects
- [ ] Source/create tuning sound file
- [ ] Integrate tuning sound with station switching

### Phase 7: Polish
- [ ] Installation script
- [ ] systemd service
- [ ] Documentation
- [ ] Testing on actual hardware

## Dependencies

### requirements.txt

```
flask>=3.0.0
flask-socketio>=5.3.0
gpiozero>=2.0
RPi.GPIO>=0.7.1
pygame>=2.5.0
```

### System packages

```
mpv
yt-dlp (via pip)
```

## Development Environment (macOS)

Primary development happens on macOS with mocked hardware:

- **GPIO**: Mocked via keyboard input or web UI controls
- **Audio**: mpv + pygame work natively on macOS
- **Web UI**: Fully functional locally

```python
# In gpio_handler.py
import platform

def is_raspberry_pi():
    return platform.machine().startswith('aarch64') or platform.machine().startswith('arm')

if not is_raspberry_pi():
    # GPIO calls are no-ops or use mock implementation
    # Physical controls tested only on Pi
```

### Local Development Setup (Mac)

```bash
# Install system dependencies
brew install mpv

# Create venv and install Python deps
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt  # Excludes RPi.GPIO, gpiozero

# Run the app
python -m app.main
```

### Deployment to Pi

```bash
# From development machine
rsync -avz --exclude 'venv' --exclude '__pycache__' \
  ./ pi@fallout-radio.local:/home/pi/fallout-radio/
```

## Future Enhancements (Out of Scope for v1)

- Physical OLED display showing current station
- LED indicators per station
- Multiple audio output options (Bluetooth, AirPlay)
- Mobile app
- Voice announcements for station changes
- Recording/scheduling
- Integration with other streaming services (Spotify, etc.)
