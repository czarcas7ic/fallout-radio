"""
GPIO handler for Fallout Radio.

Handles rotary encoder input for station selection and volume control.
On non-Pi systems, provides a mock implementation.
"""

import logging
import platform
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .radio_core import RadioCore

logger = logging.getLogger(__name__)

# GPIO Pin assignments (BCM numbering)
# Station Encoder (using pins 11, 13, 15 on header)
STATION_CLK = 17
STATION_DT = 27
STATION_SW = 22

# Volume Encoder
VOLUME_CLK = 16
VOLUME_DT = 26
VOLUME_SW = 20

# Volume step per encoder click
VOLUME_STEP = 1

# Cooldown between station changes (seconds)
STATION_CHANGE_COOLDOWN = 0.75


def is_raspberry_pi() -> bool:
    """Check if we're running on a Raspberry Pi."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            cpuinfo = f.read()
            return "Raspberry Pi" in cpuinfo or "BCM" in cpuinfo
    except FileNotFoundError:
        return False


class GPIOHandler:
    """
    Handles GPIO input from rotary encoders.

    On Raspberry Pi: Uses gpiozero to read actual hardware
    On other systems: Provides a no-op mock implementation
    """

    def __init__(self, radio_core: "RadioCore"):
        """
        Initialize the GPIO handler.

        Args:
            radio_core: RadioCore instance to control
        """
        self._radio_core = radio_core
        self._running = False
        self._is_pi = is_raspberry_pi()
        self._last_station_change = 0.0

        # These will hold gpiozero objects on Pi
        self._station_encoder = None
        self._volume_encoder = None
        self._station_button = None
        self._volume_button = None

        if self._is_pi:
            self._setup_gpio()
        else:
            logger.info("Not running on Raspberry Pi - GPIO disabled")

    def _setup_gpio(self) -> None:
        """Set up GPIO on Raspberry Pi."""
        try:
            from gpiozero import RotaryEncoder, Button

            # Station encoder
            self._station_encoder = RotaryEncoder(
                STATION_CLK,
                STATION_DT,
                max_steps=0,  # No limits
                bounce_time=0.01,  # 10ms debounce
            )
            self._station_encoder.when_rotated_clockwise = self._on_station_cw
            self._station_encoder.when_rotated_counter_clockwise = self._on_station_ccw

            # Station button (optional - could be used for mute or pack switch)
            self._station_button = Button(
                STATION_SW,
                pull_up=True,
                bounce_time=0.05,  # 50ms debounce
            )
            self._station_button.when_pressed = self._on_station_button

            # Volume encoder
            self._volume_encoder = RotaryEncoder(
                VOLUME_CLK,
                VOLUME_DT,
                max_steps=0,
                bounce_time=0.01,
            )
            self._volume_encoder.when_rotated_clockwise = self._on_volume_cw
            self._volume_encoder.when_rotated_counter_clockwise = self._on_volume_ccw

            # Volume button (optional - could be used for mute)
            self._volume_button = Button(
                VOLUME_SW,
                pull_up=True,
                bounce_time=0.05,
            )
            self._volume_button.when_pressed = self._on_volume_button

            logger.info("GPIO setup complete")
            logger.info(f"  Station encoder: CLK={STATION_CLK}, DT={STATION_DT}, SW={STATION_SW}")
            logger.info(f"  Volume encoder: CLK={VOLUME_CLK}, DT={VOLUME_DT}, SW={VOLUME_SW}")

        except ImportError as e:
            logger.error(f"Failed to import gpiozero: {e}")
            logger.error("Install with: pip install gpiozero RPi.GPIO")
            self._is_pi = False
        except Exception as e:
            logger.error(f"Failed to setup GPIO: {e}")
            self._is_pi = False

    # === Station Encoder Callbacks ===

    def _on_station_cw(self) -> None:
        """Handle station encoder clockwise rotation (next station)."""
        now = time.time()
        if now - self._last_station_change < STATION_CHANGE_COOLDOWN:
            return
        self._last_station_change = now
        logger.debug("Station encoder: CW (next)")
        self._radio_core.next_station()

    def _on_station_ccw(self) -> None:
        """Handle station encoder counter-clockwise rotation (previous station)."""
        now = time.time()
        if now - self._last_station_change < STATION_CHANGE_COOLDOWN:
            return
        self._last_station_change = now
        logger.debug("Station encoder: CCW (previous)")
        self._radio_core.previous_station()

    def _on_station_button(self) -> None:
        """Handle station encoder button press (does nothing)."""
        logger.debug("Station button pressed - no action")
        pass

    # === Volume Encoder Callbacks ===

    def _on_volume_cw(self) -> None:
        """Handle volume encoder clockwise rotation (volume up)."""
        current = self._radio_core.get_volume()
        new_volume = min(100, current + VOLUME_STEP)
        logger.debug(f"Volume encoder: CW ({current} -> {new_volume})")
        self._radio_core.set_volume(new_volume)

    def _on_volume_ccw(self) -> None:
        """Handle volume encoder counter-clockwise rotation (volume down)."""
        current = self._radio_core.get_volume()
        new_volume = max(0, current - VOLUME_STEP)
        logger.debug(f"Volume encoder: CCW ({current} -> {new_volume})")
        self._radio_core.set_volume(new_volume)

    def _on_volume_button(self) -> None:
        """Handle volume encoder button press (power toggle)."""
        logger.debug("Volume button pressed - toggling power")
        self._radio_core.toggle_power()

    # === Lifecycle ===

    def start(self) -> None:
        """Start listening for GPIO events."""
        if self._is_pi:
            self._running = True
            logger.info("GPIO handler started")
        else:
            logger.info("GPIO handler start called (no-op on non-Pi)")

    def stop(self) -> None:
        """Stop listening for GPIO events."""
        self._running = False

        if self._is_pi:
            try:
                if self._station_encoder:
                    self._station_encoder.close()
                if self._volume_encoder:
                    self._volume_encoder.close()
                if self._station_button:
                    self._station_button.close()
                if self._volume_button:
                    self._volume_button.close()
                logger.info("GPIO handler stopped")
            except Exception as e:
                logger.error(f"Error stopping GPIO: {e}")
        else:
            logger.info("GPIO handler stop called (no-op on non-Pi)")

    @property
    def is_available(self) -> bool:
        """Check if GPIO is available."""
        return self._is_pi


class MockGPIOHandler:
    """
    Mock GPIO handler for testing on non-Pi systems.

    Can be used with keyboard input for testing the interface.
    """

    def __init__(self, radio_core: "RadioCore"):
        self._radio_core = radio_core
        self._running = False
        self._thread = None
        logger.info("MockGPIOHandler initialized")

    def start(self) -> None:
        """Start the mock handler (optionally with keyboard input)."""
        self._running = True
        logger.info("MockGPIOHandler started")
        logger.info("  Mock controls available via keyboard if enabled")

    def stop(self) -> None:
        """Stop the mock handler."""
        self._running = False
        logger.info("MockGPIOHandler stopped")

    def simulate_station_next(self) -> None:
        """Simulate station encoder CW rotation."""
        self._radio_core.next_station()

    def simulate_station_prev(self) -> None:
        """Simulate station encoder CCW rotation."""
        self._radio_core.previous_station()

    def simulate_volume_up(self) -> None:
        """Simulate volume encoder CW rotation."""
        current = self._radio_core.get_volume()
        self._radio_core.set_volume(min(100, current + VOLUME_STEP))

    def simulate_volume_down(self) -> None:
        """Simulate volume encoder CCW rotation."""
        current = self._radio_core.get_volume()
        self._radio_core.set_volume(max(0, current - VOLUME_STEP))

    @property
    def is_available(self) -> bool:
        """Mock is always 'available' for testing."""
        return True


def create_gpio_handler(radio_core: "RadioCore", force_mock: bool = False) -> GPIOHandler | MockGPIOHandler:
    """
    Factory function to create the appropriate GPIO handler.

    Args:
        radio_core: RadioCore instance to control
        force_mock: If True, always use MockGPIOHandler

    Returns:
        GPIOHandler on Pi, MockGPIOHandler otherwise
    """
    if force_mock or not is_raspberry_pi():
        return MockGPIOHandler(radio_core)
    return GPIOHandler(radio_core)
