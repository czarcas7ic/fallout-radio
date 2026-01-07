"""
Core radio logic for Fallout Radio.

Manages station packs, playback state, and coordinates audio playback.
"""

import logging
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable

from . import config
from .audio_player import AudioPlayer

logger = logging.getLogger(__name__)


@dataclass
class Station:
    """Represents a radio station."""
    id: str
    name: str
    url: str

    @classmethod
    def from_dict(cls, data: dict) -> "Station":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", "Unnamed Station"),
            url=data.get("url", ""),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Pack:
    """Represents a station pack (collection of stations)."""
    id: str
    name: str
    stations: list[Station] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Pack":
        stations = [Station.from_dict(s) for s in data.get("stations", [])]
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", "Unnamed Pack"),
            stations=stations,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "stations": [s.to_dict() for s in self.stations],
        }


class RadioCore:
    """
    Core radio controller.

    Manages station packs, current playback state, and coordinates
    with the audio player for streaming and sound effects.
    """

    def __init__(self, audio_player: Optional[AudioPlayer] = None):
        """
        Initialize the radio core.

        Args:
            audio_player: AudioPlayer instance. If None, creates a new one.
        """
        self._audio_player = audio_player or AudioPlayer()
        self._audio_player.set_status_callback(self._on_audio_status_change)
        self._audio_player.set_playback_ended_callback(self._on_playback_ended)
        self._lock = threading.RLock()

        # State
        self._packs: list[Pack] = []
        self._active_pack_id: Optional[str] = None
        self._current_station_index: int = 0  # 0 = OFF, 1+ = station
        self._settings: dict = {}
        self._max_volume: int = 100  # Cached for quick access
        self._last_station_before_off: int = 1  # Remember station when turning off via volume

        # Callbacks for state changes (used by WebSocket)
        self._state_change_callbacks: list[Callable[[], None]] = []

        # Virtual timeline: maps station URL -> unix timestamp when it "started"
        # This makes non-live stations feel like live radio broadcasts
        self._virtual_start_times: dict[str, float] = {}

        # Counter to track station switches (for cancelling transitions)
        self._switch_counter: int = 0

        # Initialization state for duration prefetching
        self._initializing: bool = True
        self._init_total: int = 0
        self._init_complete: int = 0
        self._init_current_station: str = ""

        # Load saved data
        self._load_data()

        # Initialize virtual start times for all stations
        self._init_virtual_timelines()

        # Prefetch video durations in background
        self._prefetch_durations()

    def _load_data(self) -> None:
        """Load packs and settings from disk."""
        # Load packs
        packs_data = config.load_packs()
        self._packs = [Pack.from_dict(p) for p in packs_data.get("packs", [])]
        self._active_pack_id = packs_data.get("active_pack_id")

        # Validate active pack exists
        if self._active_pack_id and not self._get_pack_by_id(self._active_pack_id):
            self._active_pack_id = self._packs[0].id if self._packs else None

        # Load settings
        self._settings = config.load_settings()

        # Apply max volume setting
        self._max_volume = self._settings.get("max_volume", 100)

        # Apply default volume (capped at max_volume)
        default_volume = self._settings.get("default_volume", 30)
        default_volume = min(default_volume, self._max_volume)
        self._audio_player.set_volume(default_volume)

        # Apply static volume setting
        static_volume = self._settings.get("static_volume", 75)
        self._audio_player.set_static_volume_percent(static_volume)

        # Apply loudness normalization setting
        loudness_norm = self._settings.get("loudness_normalization", False)
        self._audio_player.set_loudness_normalization(loudness_norm)

        logger.info(f"Loaded {len(self._packs)} packs, active: {self._active_pack_id}")

    def _init_virtual_timelines(self) -> None:
        """
        Initialize virtual start times for all stations.

        Each station gets a random "start time" in the past, so when you
        tune in, it feels like the station has been playing continuously.
        """
        now = time.time()

        for pack in self._packs:
            for station in pack.stations:
                if station.url not in self._virtual_start_times:
                    # Random start time: between 0 and 24 hours ago
                    random_offset = random.uniform(0, 24 * 60 * 60)
                    self._virtual_start_times[station.url] = now - random_offset

        logger.info(f"Initialized virtual timelines for {len(self._virtual_start_times)} stations")

    def _prefetch_durations(self) -> None:
        """Prefetch video durations and stream URLs for active pack in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Only prefetch the active pack
        active_pack = self._get_pack_by_id(self._active_pack_id) if self._active_pack_id else None
        if not active_pack or not active_pack.stations:
            self._initializing = False
            return

        stations_info = [(s.url, s.name) for s in active_pack.stations]
        self._init_total = len(stations_info)
        self._init_complete = 0

        def fetch_one(url: str, name: str) -> str:
            """Fetch duration and stream URL for one station."""
            # This caches both duration AND stream URL if not already cached
            self._audio_player.get_video_duration(url)
            # If duration was cached but stream URL wasn't, fetch it now
            self._audio_player.get_stream_url(url)
            return name

        def fetch_all():
            logger.info(f"Prefetching {len(stations_info)} stations in parallel...")
            self._init_current_station = "all stations"
            self._notify_state_change()

            # Parallel fetch - mostly network I/O so parallelism helps
            with ThreadPoolExecutor(max_workers=len(stations_info)) as executor:
                futures = {executor.submit(fetch_one, url, name): name for url, name in stations_info}
                for future in as_completed(futures):
                    name = future.result()
                    self._init_complete += 1
                    logger.info(f"Prefetched: {name} ({self._init_complete}/{self._init_total})")
                    self._notify_state_change()

            self._initializing = False
            self._init_current_station = ""
            self._notify_state_change()
            logger.info("Prefetch complete - all stations ready")

            # Auto-start playback on boot
            self._auto_start_playback()

        thread = threading.Thread(target=fetch_all, daemon=True)
        thread.start()

    def _auto_start_playback(self) -> None:
        """Auto-start playback on boot if enabled and stations available."""
        # Check if auto-start is enabled
        if not self._settings.get("auto_start", True):
            logger.info("Auto-start disabled in settings")
            return

        active_pack = self._get_pack_by_id(self._active_pack_id) if self._active_pack_id else None
        if not active_pack or not active_pack.stations:
            logger.info("No stations available - skipping auto-start")
            return

        # Only auto-start if radio is currently off
        if self._current_station_index == 0:
            logger.info("Auto-starting playback on boot")
            self.switch_to_station(1)

    def _get_virtual_position(self, url: str) -> float:
        """
        Calculate the current playback position for a station's virtual timeline.

        Args:
            url: Station URL

        Returns:
            Position in seconds where playback should start.
            Returns 0 for live streams or if duration is unknown.
        """
        # Get video duration (may take a moment on first call)
        duration = self._audio_player.get_video_duration(url)

        if duration is None or duration <= 0:
            # Live stream or unknown duration - start from beginning/live
            return 0

        # Get or create virtual start time
        if url not in self._virtual_start_times:
            self._virtual_start_times[url] = time.time() - random.uniform(0, duration)

        # Calculate elapsed time since virtual start
        elapsed = time.time() - self._virtual_start_times[url]

        # Use modulo to loop the video (simulates continuous broadcast)
        position = elapsed % duration

        logger.debug(f"Virtual position for {url}: {position:.1f}s (duration: {duration:.1f}s)")
        return position

    def _save_packs(self) -> None:
        """Save packs to disk."""
        data = {
            "packs": [p.to_dict() for p in self._packs],
            "active_pack_id": self._active_pack_id,
        }
        config.save_packs(data)

    def _save_settings(self) -> None:
        """Save settings to disk."""
        config.save_settings(self._settings)

    def _get_pack_by_id(self, pack_id: str) -> Optional[Pack]:
        """Get a pack by its ID."""
        for pack in self._packs:
            if pack.id == pack_id:
                return pack
        return None

    def _notify_state_change(self) -> None:
        """Notify all registered callbacks of a state change."""
        for callback in self._state_change_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"State change callback error: {e}")

    def _on_audio_status_change(self) -> None:
        """Called when audio playback status changes."""
        self._notify_state_change()

    def _on_playback_ended(self) -> None:
        """Called when audio playback ends naturally (EOF). Restarts non-live streams."""
        try:
            logger.info("_on_playback_ended callback triggered")

            # Gather info while holding lock, but release before blocking calls
            station_url = None
            station_name = None

            with self._lock:
                logger.debug(f"Current station index: {self._current_station_index}")
                if self._current_station_index <= 0:
                    logger.info("Not playing a station, skipping restart")
                    return  # Not playing a station

                # Get current station
                active_pack = self._get_pack_by_id(self._active_pack_id) if self._active_pack_id else None
                if not active_pack:
                    logger.warning("No active pack, skipping restart")
                    return

                station_idx = self._current_station_index - 1  # Convert to 0-based
                if station_idx < 0 or station_idx >= len(active_pack.stations):
                    logger.warning(f"Invalid station index {station_idx}, skipping restart")
                    return

                station = active_pack.stations[station_idx]
                station_url = station.url
                station_name = station.name

                # Check if this is a non-live stream (has a duration)
                duration = self._audio_player.get_video_duration(station_url)
                logger.debug(f"Station duration: {duration}")
                if duration is None:
                    # Live stream shouldn't end, but if it does, don't auto-restart
                    logger.warning(f"Live stream ended unexpectedly: {station_name}")
                    return

            # Restart from the beginning for non-live content
            # Done outside the lock to avoid blocking user interactions during network calls
            logger.info(f"Restarting non-live station from beginning: {station_name}")
            self._audio_player.play_url(station_url, start_position=0)
            logger.info(f"Restart initiated for {station_name}")
        except Exception as e:
            logger.error(f"Error in _on_playback_ended: {e}", exc_info=True)

    def register_state_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback to be called on state changes."""
        self._state_change_callbacks.append(callback)

    def unregister_state_callback(self, callback: Callable[[], None]) -> None:
        """Unregister a state change callback."""
        if callback in self._state_change_callbacks:
            self._state_change_callbacks.remove(callback)

    # === State Accessors ===

    def get_current_state(self) -> dict:
        """
        Get the complete current state.

        Returns:
            Dict with pack, station, volume, and status info.
        """
        with self._lock:
            active_pack = self._get_pack_by_id(self._active_pack_id) if self._active_pack_id else None
            current_station = None

            if active_pack and self._current_station_index > 0:
                station_idx = self._current_station_index - 1  # Convert to 0-based
                if station_idx < len(active_pack.stations):
                    current_station = active_pack.stations[station_idx]

            return {
                "pack": {
                    "id": active_pack.id,
                    "name": active_pack.name,
                    "station_count": len(active_pack.stations),
                } if active_pack else None,
                "station": {
                    "id": current_station.id,
                    "name": current_station.name,
                    "index": self._current_station_index,
                } if current_station else None,
                "station_index": self._current_station_index,
                "volume": self._audio_player.get_volume(),
                "status": self._audio_player.get_stream_status(),
                "is_on": self._current_station_index > 0,
                "initializing": self._initializing,
                "init_progress": {
                    "total": self._init_total,
                    "complete": self._init_complete,
                    "current_station": self._init_current_station,
                } if self._initializing else None,
            }

    # === Station Switching ===

    def switch_to_station(self, index: int) -> None:
        """
        Switch to a specific station by index.

        Args:
            index: Station index (0 = OFF, 1+ = station number)
        """
        with self._lock:
            active_pack = self._get_pack_by_id(self._active_pack_id) if self._active_pack_id else None
            max_index = len(active_pack.stations) if active_pack else 0

            # Clamp index
            if index < 0:
                index = 0
            elif index > max_index:
                index = max_index

            # No change needed
            if index == self._current_station_index:
                return

            old_index = self._current_station_index
            self._current_station_index = index

            # Check if we're currently playing something
            is_playing = self._audio_player.is_playing() or self._audio_player.get_stream_status() == "loading"

            # Handle playback
            if index == 0:
                # OFF - immediate stop, no fade
                self._audio_player.stop_tuning_sound()
                self._audio_player.stop()
            elif active_pack and index <= len(active_pack.stations):
                # Play the selected station
                station = active_pack.stations[index - 1]

                # Increment switch counter to cancel any pending transitions
                self._switch_counter += 1
                my_switch = self._switch_counter

                # Save reference to old mpv process and socket FIRST
                old_process = self._audio_player._mpv_process
                old_socket = self._audio_player._ipc_socket_path

                # Start static FIRST - this ensures audio mixing is established
                self._audio_player.fade_in_tuning(duration=1.0)

                # Now start the fade (static is already playing and mixing)
                if is_playing and old_process:
                    # Drop old station volume to 70% to make room for static
                    current_vol = self._audio_player.get_volume()
                    self._audio_player._send_mpv_command(["set_property", "volume", current_vol * 0.7])
                    # Start the gradual fade in background
                    self._audio_player.fade_out_stream(duration=2.0, socket_path=old_socket)

                # Calculate virtual position
                start_position = self._get_virtual_position(station.url)

                # Start loading new station (uses new socket, old fade continues)
                self._audio_player.play_url(station.url, start_position=start_position, stop_current=False)

                # Clean up old process in background (non-blocking)
                if is_playing and old_process:
                    def cleanup_old(proc, sock, switch_id):
                        # Wait for fade, but check if another switch happened
                        for _ in range(30):  # 30 x 0.1s = 3s
                            if self._switch_counter != switch_id:
                                break
                            time.sleep(0.1)
                        # Kill old process
                        try:
                            proc.kill()
                            proc.wait(timeout=1.0)
                        except:
                            pass
                        # Clean up old socket
                        try:
                            if os.path.exists(sock):
                                os.unlink(sock)
                        except:
                            pass

                    thread = threading.Thread(
                        target=cleanup_old,
                        args=(old_process, old_socket, my_switch),
                        daemon=True
                    )
                    thread.start()
            else:
                # No stations or invalid - stop
                self._audio_player.play_tuning_sound(loop=False)
                self._audio_player.stop()

        self._notify_state_change()

    def toggle_power(self) -> None:
        """Toggle the radio on/off."""
        with self._lock:
            if self._current_station_index == 0:
                # Turn on - go to station 1
                self.switch_to_station(1)
            else:
                # Turn off
                self.switch_to_station(0)

    def next_station(self) -> None:
        """Switch to the next station. Wraps to first station if at last."""
        with self._lock:
            # Do nothing if radio is off
            if self._current_station_index == 0:
                return

            active_pack = self._get_pack_by_id(self._active_pack_id) if self._active_pack_id else None
            max_index = len(active_pack.stations) if active_pack else 0

            if self._current_station_index >= max_index:
                # Wrap to first station
                new_index = 1
            else:
                new_index = self._current_station_index + 1

        self.switch_to_station(new_index)

    def previous_station(self) -> None:
        """Switch to the previous station. Wraps to last station if at first."""
        with self._lock:
            # Do nothing if radio is off
            if self._current_station_index == 0:
                return

            active_pack = self._get_pack_by_id(self._active_pack_id) if self._active_pack_id else None
            max_index = len(active_pack.stations) if active_pack else 0

            if self._current_station_index <= 1:
                # Wrap to last station
                new_index = max_index
            else:
                new_index = self._current_station_index - 1

        self.switch_to_station(new_index)

    # === Volume Control ===

    def set_volume(self, level: int) -> None:
        """
        Set the volume level (0 to max_volume).

        Volume-based power control:
        - Setting volume to 0 turns the radio off
        - Setting volume above 0 while off turns the radio on
        """
        # Clamp to valid range (0 to max_volume)
        level = max(0, min(self._max_volume, level))

        current_volume = self._audio_player.get_volume()
        is_on = self._current_station_index > 0

        # Volume-based power control
        if level == 0 and is_on:
            # Turning off via volume - save current station for later
            self._last_station_before_off = self._current_station_index
            self._audio_player.set_volume(0)
            self.switch_to_station(0)
            return
        elif level > 0 and not is_on:
            # Turning on via volume - restore last station
            self._audio_player.set_volume(level)
            target_station = self._last_station_before_off
            # Validate station still exists
            active_pack = self._get_pack_by_id(self._active_pack_id) if self._active_pack_id else None
            max_station = len(active_pack.stations) if active_pack else 0
            if target_station < 1 or target_station > max_station:
                target_station = 1 if max_station > 0 else 0
            if target_station > 0:
                self.switch_to_station(target_station)
            self._notify_state_change()
            return

        # Normal volume change
        self._audio_player.set_volume(level)
        self._notify_state_change()

    def get_volume(self) -> int:
        """Get the current volume level."""
        return self._audio_player.get_volume()

    # === Pack Management ===

    def get_packs(self) -> list[dict]:
        """Get all packs as dicts."""
        with self._lock:
            return [
                {
                    **p.to_dict(),
                    "is_active": p.id == self._active_pack_id,
                }
                for p in self._packs
            ]

    def get_pack(self, pack_id: str) -> Optional[dict]:
        """Get a single pack by ID."""
        with self._lock:
            pack = self._get_pack_by_id(pack_id)
            if pack:
                return {
                    **pack.to_dict(),
                    "is_active": pack.id == self._active_pack_id,
                }
            return None

    def create_pack(self, name: str) -> dict:
        """
        Create a new pack.

        Args:
            name: Name for the new pack

        Returns:
            The created pack as a dict
        """
        with self._lock:
            pack = Pack(
                id=str(uuid.uuid4()),
                name=name,
                stations=[],
            )
            self._packs.append(pack)

            # If this is the first pack, make it active
            if len(self._packs) == 1:
                self._active_pack_id = pack.id

            self._save_packs()
            logger.info(f"Created pack: {pack.name} ({pack.id})")

            return pack.to_dict()

    def update_pack(self, pack_id: str, data: dict) -> Optional[dict]:
        """
        Update a pack's properties.

        Args:
            pack_id: ID of the pack to update
            data: Dict with fields to update (name, stations)

        Returns:
            Updated pack as dict, or None if not found
        """
        with self._lock:
            pack = self._get_pack_by_id(pack_id)
            if not pack:
                return None

            if "name" in data:
                pack.name = data["name"]

            if "stations" in data:
                pack.stations = [Station.from_dict(s) for s in data["stations"]]

            self._save_packs()
            logger.info(f"Updated pack: {pack.name}")

            return pack.to_dict()

    def delete_pack(self, pack_id: str) -> bool:
        """
        Delete a pack.

        Args:
            pack_id: ID of the pack to delete

        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            pack = self._get_pack_by_id(pack_id)
            if not pack:
                return False

            self._packs.remove(pack)

            # If we deleted the active pack, switch to another or none
            if self._active_pack_id == pack_id:
                if self._packs:
                    self.set_active_pack(self._packs[0].id)
                else:
                    self._active_pack_id = None
                    self._current_station_index = 0
                    self._audio_player.stop()

            self._save_packs()
            logger.info(f"Deleted pack: {pack.name}")

            return True

    def next_pack(self) -> bool:
        """
        Cycle to the next pack. Wraps from last to first.

        Returns:
            True if successful, False if no packs available
        """
        with self._lock:
            if not self._packs:
                return False

            # Find current pack index
            current_idx = 0
            for i, pack in enumerate(self._packs):
                if pack.id == self._active_pack_id:
                    current_idx = i
                    break

            # Cycle to next pack (wrap around)
            next_idx = (current_idx + 1) % len(self._packs)
            next_pack = self._packs[next_idx]

        return self.set_active_pack(next_pack.id)

    def set_active_pack(self, pack_id: str) -> bool:
        """
        Set the active pack.

        Args:
            pack_id: ID of the pack to activate

        Returns:
            True if successful, False if pack not found
        """
        with self._lock:
            pack = self._get_pack_by_id(pack_id)
            if not pack:
                return False

            if self._active_pack_id == pack_id:
                return True  # Already active

            # Remember if radio was on before switching
            was_on = self._current_station_index > 0

            self._active_pack_id = pack_id
            self._save_packs()
            logger.info(f"Activated pack: {pack.name}")

        # Lazy-load durations for the new pack in background
        self._prefetch_pack_durations(pack)

        # If radio was on, play first station of new pack
        # If radio was off, stay off
        if was_on and pack.stations:
            # Reset index so switch_to_station doesn't skip (it checks if index changed)
            self._current_station_index = 0
            self.switch_to_station(1)
        else:
            self._audio_player.stop()
            self._current_station_index = 0
            self._notify_state_change()

        return True

    def _prefetch_pack_durations(self, pack: Pack) -> None:
        """Prefetch durations for a specific pack in background (no UI blocking)."""
        if not pack.stations:
            return

        # Check which stations don't have cached durations
        uncached = [s for s in pack.stations
                    if s.url not in self._audio_player._duration_cache]

        if not uncached:
            logger.info(f"Pack '{pack.name}' durations already cached")
            return

        def fetch_all():
            logger.info(f"Background prefetch for pack '{pack.name}' ({len(uncached)} stations)...")
            # Sequential fetch to avoid CPU contention on Pi
            for station in uncached:
                self._audio_player.get_video_duration(station.url)
            logger.info(f"Background prefetch for pack '{pack.name}' complete")

        thread = threading.Thread(target=fetch_all, daemon=True)
        thread.start()

    # === Station Management (within a pack) ===

    def add_station(self, pack_id: str, name: str, url: str) -> Optional[dict]:
        """
        Add a station to a pack.

        Args:
            pack_id: ID of the pack
            name: Station name
            url: Station URL

        Returns:
            The created station as dict, or None if pack not found
        """
        with self._lock:
            pack = self._get_pack_by_id(pack_id)
            if not pack:
                return None

            station = Station(
                id=str(uuid.uuid4()),
                name=name,
                url=url,
            )
            pack.stations.append(station)

            self._save_packs()
            logger.info(f"Added station '{name}' to pack '{pack.name}'")

            return station.to_dict()

    def update_station(self, pack_id: str, station_id: str, data: dict) -> Optional[dict]:
        """
        Update a station's properties.

        Args:
            pack_id: ID of the pack containing the station
            station_id: ID of the station to update
            data: Dict with fields to update (name, url)

        Returns:
            Updated station as dict, or None if not found
        """
        with self._lock:
            pack = self._get_pack_by_id(pack_id)
            if not pack:
                return None

            for station in pack.stations:
                if station.id == station_id:
                    if "name" in data:
                        station.name = data["name"]
                    if "url" in data:
                        station.url = data["url"]

                    self._save_packs()
                    logger.info(f"Updated station: {station.name}")
                    return station.to_dict()

            return None

    def delete_station(self, pack_id: str, station_id: str) -> bool:
        """
        Delete a station from a pack.

        Args:
            pack_id: ID of the pack
            station_id: ID of the station to delete

        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            pack = self._get_pack_by_id(pack_id)
            if not pack:
                return False

            for i, station in enumerate(pack.stations):
                if station.id == station_id:
                    pack.stations.pop(i)

                    # Adjust current station index if needed
                    if pack.id == self._active_pack_id:
                        if self._current_station_index > len(pack.stations):
                            self._current_station_index = len(pack.stations)
                            if self._current_station_index == 0:
                                self._audio_player.stop()

                    self._save_packs()
                    logger.info(f"Deleted station: {station.name}")
                    return True

            return False

    def reorder_stations(self, pack_id: str, station_ids: list[str]) -> bool:
        """
        Reorder stations in a pack.

        Args:
            pack_id: ID of the pack
            station_ids: List of station IDs in the new order

        Returns:
            True if successful, False if pack not found
        """
        with self._lock:
            pack = self._get_pack_by_id(pack_id)
            if not pack:
                return False

            # Build new station list in specified order
            station_map = {s.id: s for s in pack.stations}
            new_stations = []

            for sid in station_ids:
                if sid in station_map:
                    new_stations.append(station_map[sid])

            # Add any stations not in the list at the end
            for station in pack.stations:
                if station not in new_stations:
                    new_stations.append(station)

            pack.stations = new_stations
            self._save_packs()
            logger.info(f"Reordered stations in pack '{pack.name}'")

            return True

    # === Settings ===

    def get_settings(self) -> dict:
        """Get current settings."""
        with self._lock:
            return self._settings.copy()

    def update_settings(self, data: dict) -> dict:
        """
        Update settings.

        Args:
            data: Dict with settings to update

        Returns:
            Updated settings
        """
        with self._lock:
            if "default_volume" in data:
                self._settings["default_volume"] = data["default_volume"]

            if "max_volume" in data:
                new_max = max(1, min(100, data["max_volume"]))  # Clamp 1-100
                self._settings["max_volume"] = new_max
                self._max_volume = new_max
                # If current volume exceeds new max, lower it
                current_vol = self._audio_player.get_volume()
                if current_vol > new_max:
                    self._audio_player.set_volume(new_max)

            if "static_volume" in data:
                self._settings["static_volume"] = data["static_volume"]
                self._audio_player.set_static_volume_percent(data["static_volume"])

            if "loudness_normalization" in data:
                self._settings["loudness_normalization"] = data["loudness_normalization"]
                self._audio_player.set_loudness_normalization(data["loudness_normalization"])

            if "auto_start" in data:
                self._settings["auto_start"] = data["auto_start"]

            self._save_settings()
            logger.info(f"Updated settings: {data}")

            return self._settings.copy()

    # === Cleanup ===

    def cleanup(self) -> None:
        """Clean up resources."""
        self._audio_player.cleanup()
        logger.info("RadioCore cleaned up")
