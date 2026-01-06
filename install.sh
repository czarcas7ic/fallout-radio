#!/bin/bash
# =============================================================================
# Fallout Radio - Raspberry Pi Installation Script
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "=============================================="
echo "       Fallout Radio Installation"
echo "=============================================="
echo -e "${NC}"

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo -e "${YELLOW}Warning: This doesn't appear to be a Raspberry Pi.${NC}"
    echo "Some features (GPIO, I2S audio) won't work on other systems."
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
INSTALL_DIR="${INSTALL_DIR:-$SCRIPT_DIR}"

echo -e "${GREEN}[1/7] Installing system dependencies...${NC}"
sudo apt-get update
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-lgpio \
    mpv \
    libsdl2-mixer-2.0-0 \
    git

# Install yt-dlp (latest version via pip is preferred over apt)
echo -e "${GREEN}[2/7] Installing yt-dlp...${NC}"
sudo pip3 install --break-system-packages yt-dlp || sudo pip3 install yt-dlp

echo -e "${GREEN}[3/7] Setting up Python virtual environment...${NC}"
cd "$INSTALL_DIR"
python3 -m venv venv
source venv/bin/activate

echo -e "${GREEN}[4/7] Installing Python packages...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

echo -e "${GREEN}[5/7] Configuring I2S audio (MAX98357A)...${NC}"

# Check if dtoverlay is already configured
if ! grep -q "dtoverlay=max98357a" /boot/config.txt 2>/dev/null && \
   ! grep -q "dtoverlay=max98357a" /boot/firmware/config.txt 2>/dev/null; then

    # Determine config.txt location (differs between Pi OS versions)
    if [ -f /boot/firmware/config.txt ]; then
        CONFIG_FILE="/boot/firmware/config.txt"
    else
        CONFIG_FILE="/boot/config.txt"
    fi

    echo -e "${YELLOW}Adding I2S DAC overlay to $CONFIG_FILE${NC}"
    echo "" | sudo tee -a "$CONFIG_FILE" > /dev/null
    echo "# Fallout Radio - MAX98357A I2S DAC" | sudo tee -a "$CONFIG_FILE" > /dev/null
    echo "dtoverlay=max98357a" | sudo tee -a "$CONFIG_FILE" > /dev/null

    REBOOT_NEEDED=true
else
    echo "I2S DAC overlay already configured."
fi

# Disable onboard audio if using I2S (optional but recommended)
if grep -q "^dtparam=audio=on" "$CONFIG_FILE" 2>/dev/null; then
    echo -e "${YELLOW}Disabling onboard audio in favor of I2S DAC...${NC}"
    sudo sed -i 's/^dtparam=audio=on/dtparam=audio=off/' "$CONFIG_FILE"
fi

echo -e "${GREEN}[6/7] Configuring ALSA software mixing...${NC}"

# Create ALSA config for dmix (allows pygame and mpv to share audio)
cat > ~/.asoundrc << 'ASOUNDRC'
# Software mixing for MAX98357A I2S DAC
# Allows multiple audio applications to play simultaneously

pcm.!default {
    type plug
    slave.pcm "dmixer"
}

pcm.dmixer {
    type dmix
    ipc_key 1024
    slave {
        pcm "hw:0,0"
        period_time 0
        period_size 1024
        buffer_size 4096
        rate 44100
    }
    bindings {
        0 0
        1 1
    }
}

ctl.!default {
    type hw
    card 0
}
ASOUNDRC

echo "ALSA dmix configured in ~/.asoundrc"

echo -e "${GREEN}[7/7] Installing systemd service...${NC}"

# Create systemd service file
sudo tee /etc/systemd/system/fallout-radio.service > /dev/null << EOF
[Unit]
Description=Fallout Radio - Retro Internet Radio
After=network.target sound.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$INSTALL_DIR/venv/bin/python -m app.main
Restart=always
RestartSec=5

# Give time for audio hardware to initialize
ExecStartPre=/bin/sleep 2

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd and enable the service
sudo systemctl daemon-reload
sudo systemctl enable fallout-radio.service

echo ""
echo -e "${GREEN}=============================================="
echo "       Installation Complete!"
echo "==============================================${NC}"
echo ""
echo "Fallout Radio has been installed to: $INSTALL_DIR"
echo ""
echo "Commands:"
echo "  Start:   sudo systemctl start fallout-radio"
echo "  Stop:    sudo systemctl stop fallout-radio"
echo "  Status:  sudo systemctl status fallout-radio"
echo "  Logs:    journalctl -u fallout-radio -f"
echo ""
echo "Web interface will be available at:"
echo "  http://$(hostname -I | awk '{print $1}'):5000"
echo ""

if [ "$REBOOT_NEEDED" = true ]; then
    echo -e "${YELLOW}IMPORTANT: A reboot is required for I2S audio to work.${NC}"
    read -p "Reboot now? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        sudo reboot
    else
        echo "Please reboot manually when ready: sudo reboot"
    fi
fi
