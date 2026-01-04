"""
Audio player module for Fallout Radio.

Handles YouTube streaming via mpv/yt-dlp and local sound effects via mpv.
"""

import json
import logging
import os
import platform
import random
import socket
import subprocess
import tempfile
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

import yt_dlp

from . import config

logger = logging.getLogger(__name__)

# Shared yt-dlp instance for fast metadata extraction (avoids subprocess overhead)
_yt_dlp_opts = {
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'extract_flat': False,  # Need full info for duration
    'no_color': True,
}
_yt_dlp_instance: Optional[yt_dlp.YoutubeDL] = None
_yt_dlp_lock = threading.Lock()


def _get_yt_dlp() -> yt_dlp.YoutubeDL:
    """Get or create a shared yt-dlp instance (thread-safe)."""
    global _yt_dlp_instance
    with _yt_dlp_lock:
        if _yt_dlp_instance is None:
            _yt_dlp_instance = yt_dlp.YoutubeDL(_yt_dlp_opts)
        return _yt_dlp_instance


class StreamStatus(Enum):
    STOPPED = "stopped"
    LOADING = "loading"
    PLAYING = "playing"
    ERROR = "error"


class AudioPlayer:
    """
    Manages audio playback for Fallout Radio.

    - YouTube streams via mpv subprocess with yt-dlp
    - Local sound effects via mpv
    - Volume control via mpv IPC
    """

    def __init__(self, sounds_dir: Optional[Path] = None):
        """
        Initialize the audio player.

        Args:
            sounds_dir: Path to directory containing sound effect files.
                       Defaults to app/static/sounds/
        """
        self._mpv_process: Optional[subprocess.Popen] = None
        self._ipc_socket_path = os.path.join(tempfile.gettempdir(), "fallout-radio-mpv.sock")
        self._socket_counter = 0  # For unique socket paths when running parallel streams
        self._volume: int = 30
        self._status: StreamStatus = StreamStatus.STOPPED
        self._current_url: Optional[str] = None
        self._status_lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitor = threading.Event()

        # Callback for status changes (used to notify WebSocket clients)
        self._status_callback: Optional[callable] = None

        # Set up sounds directory
        if sounds_dir is None:
            sounds_dir = Path(__file__).parent / "static" / "sounds"
        self._sounds_dir = sounds_dir

        # Tuning sound via mpv (persistent process, volume-controlled)
        self._tuning_process: Optional[subprocess.Popen] = None
        self._tuning_socket_path = os.path.join(tempfile.gettempdir(), "fallout-radio-tuning.sock")
        self._tuning_sound_path: Optional[Path] = self._find_tuning_sound()
        self._tuning_active: bool = False  # Whether static should be audible
        self._static_volume_percent: int = 60  # Percentage of main volume for static
        self._audio_preset: str = "flat"  # Current audio preset name

        # Cache for video durations (url -> duration in seconds)
        # Load from disk for instant startup after first run
        self._duration_cache: dict[str, Optional[float]] = self._load_duration_cache()

        # Cache for direct stream URLs (youtube_url -> direct_stream_url)
        # These expire, so we don't persist them to disk
        self._stream_url_cache: dict[str, tuple[str, float]] = {}  # url -> (stream_url, timestamp)

        # Tuning sound volume (0.0 to 1.0) for fading
        self._tuning_volume: float = 0.0  # Start muted
        self._fade_thread: Optional[threading.Thread] = None
        self._stop_fade = threading.Event()

        # Kill any orphaned mpv processes from previous runs
        self._kill_orphaned_mpv()

        # Start persistent tuning sound process (muted)
        self._start_persistent_tuning()

    def _start_persistent_tuning(self) -> None:
        """Start a persistent tuning sound process (muted, looping)."""
        if not self._tuning_sound_path:
            logger.debug("No tuning sound available")
            return

        # Clean up old socket
        try:
            if os.path.exists(self._tuning_socket_path):
                os.unlink(self._tuning_socket_path)
        except OSError:
            pass

        # Start mpv muted, looping forever
        cmd = [
            "mpv",
            f"--input-ipc-server={self._tuning_socket_path}",
            "--no-video",
            "--no-terminal",
            "--volume=0",  # Start muted
            "--loop=inf",
            str(self._tuning_sound_path),
        ]

        try:
            self._tuning_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Started persistent tuning sound (muted)")
        except Exception as e:
            logger.warning(f"Failed to start persistent tuning: {e}")

    def _kill_orphaned_mpv(self) -> None:
        """Kill any orphaned mpv processes that might be using our sockets."""
        import glob as glob_module
        try:
            # Find all fallout-radio-mpv sockets
            socket_pattern = os.path.join(tempfile.gettempdir(), "fallout-radio-mpv*.sock")
            orphan_sockets = glob_module.glob(socket_pattern)

            for sock_path in orphan_sockets:
                logger.info(f"Found orphaned mpv socket: {sock_path}, cleaning up...")
                # Try to connect and quit gracefully first
                try:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.settimeout(1.0)
                    sock.connect(sock_path)
                    sock.sendall(b'{"command": ["quit"]}\n')
                    sock.close()
                    time.sleep(0.3)
                except:
                    pass
                # Remove socket file
                try:
                    if os.path.exists(sock_path):
                        os.unlink(sock_path)
                except:
                    pass
        except Exception as e:
            logger.debug(f"Orphan cleanup error: {e}")

    def _load_duration_cache(self) -> dict[str, Optional[float]]:
        """Load duration cache from disk."""
        try:
            data = config.load_duration_cache()
            cache = {}
            for url, duration in data.items():
                cache[url] = float(duration) if duration is not None else None
            if cache:
                logger.debug(f"Loaded {len(cache)} cached durations from disk")
            return cache
        except Exception as e:
            logger.warning(f"Failed to load duration cache: {e}")
            return {}

    def _save_duration_cache(self) -> None:
        """Save duration cache to disk."""
        try:
            config.save_duration_cache(self._duration_cache)
        except Exception as e:
            logger.warning(f"Failed to save duration cache: {e}")

    def set_status_callback(self, callback: callable) -> None:
        """Set a callback to be called when playback status changes."""
        self._status_callback = callback

    def _notify_status_change(self) -> None:
        """Notify the callback of a status change."""
        if self._status_callback:
            try:
                self._status_callback()
            except Exception as e:
                logger.warning(f"Status callback error: {e}")

    def _find_tuning_sound(self) -> Optional[Path]:
        """Find the tuning sound effect file."""
        for ext in [".wav", ".mp3", ".ogg"]:
            tuning_path = self._sounds_dir / f"tuning{ext}"
            if tuning_path.exists():
                logger.info(f"Found tuning sound: {tuning_path}")
                return tuning_path
        logger.info("No tuning sound found in sounds directory")
        return None

    def _cleanup_socket(self) -> None:
        """Remove the IPC socket file if it exists."""
        try:
            if os.path.exists(self._ipc_socket_path):
                os.unlink(self._ipc_socket_path)
        except OSError as e:
            logger.warning(f"Failed to cleanup socket: {e}")

    def _send_mpv_command(self, command: list) -> Optional[dict]:
        """
        Send a command to mpv via IPC socket.

        Args:
            command: Command as a list, e.g., ["get_property", "volume"]

        Returns:
            Response dict from mpv, or None on failure.
        """
        if not os.path.exists(self._ipc_socket_path):
            return None

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(self._ipc_socket_path)

            msg = json.dumps({"command": command}) + "\n"
            sock.sendall(msg.encode())

            response = sock.recv(4096).decode()
            sock.close()

            return json.loads(response)
        except (socket.error, json.JSONDecodeError, OSError) as e:
            logger.debug(f"IPC command failed: {e}")
            return None

    def _start_status_monitor(self) -> None:
        """Start background thread to monitor mpv status."""
        self._stop_monitor.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _stop_status_monitor(self) -> None:
        """Stop the status monitor thread."""
        self._stop_monitor.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
            self._monitor_thread = None

    def _monitor_loop(self) -> None:
        """Monitor mpv process and update status."""
        # Wait for socket to be created
        for _ in range(50):  # 5 seconds max
            if self._stop_monitor.is_set():
                return
            if os.path.exists(self._ipc_socket_path):
                break
            time.sleep(0.1)

        while not self._stop_monitor.is_set():
            if self._mpv_process is None:
                break

            # Check if process is still running
            if self._mpv_process.poll() is not None:
                with self._status_lock:
                    if self._status != StreamStatus.STOPPED:
                        self._status = StreamStatus.ERROR
                        logger.warning("mpv process exited unexpectedly")
                self._notify_status_change()
                break

            # Query playback status
            paused = self._send_mpv_command(["get_property", "pause"])
            buffering = self._send_mpv_command(["get_property", "paused-for-cache"])
            idle = self._send_mpv_command(["get_property", "core-idle"])
            time_pos = self._send_mpv_command(["get_property", "time-pos"])

            old_status = self._status

            is_paused = paused and paused.get("data") is True
            is_buffering = buffering and buffering.get("data") is True
            is_idle = idle and idle.get("data") is True
            has_position = time_pos and time_pos.get("data") is not None and time_pos.get("data") > 0

            with self._status_lock:
                if is_paused or is_buffering or is_idle or not has_position:
                    self._status = StreamStatus.LOADING
                else:
                    self._status = StreamStatus.PLAYING

            if self._status != old_status:
                if self._status == StreamStatus.PLAYING:
                    self._send_mpv_command(["set_property", "volume", self._volume])
                    self.fade_out_tuning(duration=0.8)
                self._notify_status_change()

            time.sleep(0.5)

    def _extract_stream_url_from_info(self, url: str, info: dict) -> Optional[str]:
        """Extract and cache stream URL from yt-dlp info dict."""
        formats = info.get('formats', [])

        # Get audio-only formats
        audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']

        # For live streams, also try audio-only formats first
        if info.get('is_live') and not audio_formats:
            # Fall back to main URL for live if no audio-only available
            stream_url = info.get('url')
            if stream_url:
                self._stream_url_cache[url] = (stream_url, time.time())
                return stream_url
            return None

        if audio_formats:
            # Prefer Opus codec (highest quality on YouTube), then sort by bitrate
            # Opus > vorbis > aac/mp4a
            def audio_quality_score(f):
                codec = (f.get('acodec') or '').lower()
                bitrate = f.get('abr') or f.get('tbr') or 0

                # Codec preference (higher is better)
                if 'opus' in codec:
                    codec_score = 3
                elif 'vorbis' in codec:
                    codec_score = 2
                else:  # aac, mp4a, etc.
                    codec_score = 1

                # Combined score: codec preference * 1000 + bitrate
                return codec_score * 1000 + bitrate

            audio_formats.sort(key=audio_quality_score, reverse=True)
            best = audio_formats[0]
            stream_url = best.get('url')

            if stream_url:
                codec = best.get('acodec', 'unknown')
                bitrate = best.get('abr') or best.get('tbr') or 0
                logger.debug(f"Selected audio format: {codec} @ {bitrate}kbps")
                self._stream_url_cache[url] = (stream_url, time.time())
                return stream_url

        # Fallback: try the main URL field
        stream_url = info.get('url')
        if stream_url:
            self._stream_url_cache[url] = (stream_url, time.time())
            return stream_url

        return None

    def get_video_duration(self, url: str) -> Optional[float]:
        """
        Get the duration of a YouTube video in seconds.

        Uses yt-dlp library directly. Results are cached.
        Also caches stream URL from the same call.
        Returns None for live streams or on error.
        """
        if url in self._duration_cache:
            return self._duration_cache[url]

        try:
            ydl = _get_yt_dlp()
            info = ydl.extract_info(url, download=False)

            if info is None:
                self._duration_cache[url] = None
                self._save_duration_cache()
                return None

            is_live = info.get('is_live', False)
            if is_live:
                self._duration_cache[url] = None
                self._save_duration_cache()
                self._extract_stream_url_from_info(url, info)
                return None

            # Cache stream URL from this same extract_info call
            self._extract_stream_url_from_info(url, info)

            duration = info.get('duration')
            if duration is not None:
                duration = float(duration)
                self._duration_cache[url] = duration
                self._save_duration_cache()
                return duration

        except Exception as e:
            logger.warning(f"Error fetching duration: {e}")

        self._duration_cache[url] = None
        self._save_duration_cache()
        return None

    def get_stream_url(self, url: str) -> Optional[str]:
        """
        Get the direct stream URL for a YouTube video.

        Uses yt-dlp library to resolve the YouTube URL to a direct audio stream URL.
        Results are cached briefly (YouTube URLs expire after ~6 hours).
        """
        cache_max_age = 30 * 60  # 30 minutes
        if url in self._stream_url_cache:
            stream_url, cached_time = self._stream_url_cache[url]
            if time.time() - cached_time < cache_max_age:
                return stream_url

        try:
            ydl = _get_yt_dlp()
            info = ydl.extract_info(url, download=False)

            if info is None:
                return None

            return self._extract_stream_url_from_info(url, info)

        except Exception as e:
            logger.warning(f"Error resolving stream URL: {e}")
            return None

    def play_url(self, url: str, start_position: float = 0, stop_current: bool = True) -> bool:
        """
        Start streaming a YouTube URL.

        Args:
            url: YouTube video/stream URL
            start_position: Start playback at this position in seconds (default 0)
            stop_current: If True, stop current playback first. If False, let caller handle it.

        Returns:
            True if playback started successfully, False otherwise.
        """
        # Always stop the old monitor thread to prevent stale timing logs
        self._stop_status_monitor()

        # Stop any existing playback (unless caller will handle it)
        if stop_current:
            self.stop()
            self._cleanup_socket()
        else:
            # Use a new unique socket for parallel stream
            self._socket_counter += 1
            self._ipc_socket_path = os.path.join(
                tempfile.gettempdir(),
                f"fallout-radio-mpv-{self._socket_counter}.sock"
            )
            self._cleanup_socket()

        with self._status_lock:
            self._status = StreamStatus.LOADING
            self._current_url = url

        # Notify UI immediately so it shows loading state
        self._notify_status_change()

        # Resolve YouTube URL to direct stream URL
        play_url = url
        if "youtube.com" in url or "youtu.be" in url:
            resolved = self.get_stream_url(url)
            if resolved:
                play_url = resolved

        # Build mpv command - minimal settings, let mpv auto-detect everything
        cmd = [
            "mpv",
            f"--input-ipc-server={self._ipc_socket_path}",
            "--no-video",
            "--no-terminal",
            f"--volume={self._volume}",
        ]

        # Add start position if specified
        if start_position > 0:
            cmd.append(f"--start={int(start_position)}")

        cmd.append(play_url)

        try:
            self._mpv_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            if start_position > 0:
                logger.info(f"Started mpv for URL: {url} at position {start_position:.0f}s")
            else:
                logger.info(f"Started mpv for URL: {url}")

            # Start monitoring thread
            self._start_status_monitor()

            return True
        except FileNotFoundError:
            logger.error("mpv not found. Please install mpv.")
            with self._status_lock:
                self._status = StreamStatus.ERROR
            return False
        except Exception as e:
            logger.error(f"Failed to start mpv: {e}")
            with self._status_lock:
                self._status = StreamStatus.ERROR
            return False

    def play_tuning_sound(self, loop: bool = False) -> None:
        """
        Play the tuning sound effect at reduced volume using mpv.

        Args:
            loop: If True, loop the sound until stop_tuning_sound() is called.
        """
        if not self._tuning_sound_path:
            logger.debug("No tuning sound available, skipping")
            return

        # Stop any existing tuning sound
        self.stop_tuning_sound()

        # Clean up old socket
        try:
            if os.path.exists(self._tuning_socket_path):
                os.unlink(self._tuning_socket_path)
        except OSError:
            pass

        # Use same volume as main stream
        tuning_vol = self._volume

        # Build mpv command for tuning sound
        cmd = [
            "mpv",
            f"--input-ipc-server={self._tuning_socket_path}",
            "--no-video",
            "--no-terminal",
            f"--volume={tuning_vol}",
        ]

        if loop:
            cmd.append("--loop=inf")

        cmd.append(str(self._tuning_sound_path))

        try:
            self._tuning_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.debug(f"Playing tuning sound (loop={loop})")
        except Exception as e:
            logger.warning(f"Failed to play tuning sound: {e}")

    def stop_tuning_sound(self) -> None:
        """Immediately mute the tuning sound (keeps process running)."""
        self._stop_fade.set()  # Stop any active fade

        # Just mute it, don't kill the process
        if self._tuning_process and self._tuning_process.poll() is None:
            self._send_tuning_command(["set_property", "volume", 0])

        self._tuning_volume = 0.0
        self._tuning_active = False
        logger.debug("Muted tuning sound")

    def fade_out_stream(self, duration: float = 0.5, callback: Optional[callable] = None, socket_path: Optional[str] = None) -> None:
        """
        Fade out the current stream volume.

        Args:
            duration: Fade duration in seconds
            callback: Optional callback when fade completes
            socket_path: Optional IPC socket path (uses current if not specified)
        """
        if not self._mpv_process or self._mpv_process.poll() is not None:
            if callback:
                callback()
            return

        # Use specified socket or current one
        fade_socket = socket_path or self._ipc_socket_path

        def send_to_socket(command: list) -> Optional[dict]:
            """Send command to specific socket."""
            if not os.path.exists(fade_socket):
                return None
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(1.0)
                sock.connect(fade_socket)
                msg = json.dumps({"command": command}) + "\n"
                sock.sendall(msg.encode())
                response = sock.recv(4096).decode()
                sock.close()
                return json.loads(response)
            except:
                return None

        def fade():
            steps = 20
            step_duration = duration / steps
            current_vol = self._volume

            for i in range(steps):
                if self._stop_fade.is_set():
                    break
                vol = current_vol * (1 - (i + 1) / steps)
                send_to_socket(["set_property", "volume", max(0, vol)])
                time.sleep(step_duration)

            if callback:
                callback()

        self._stop_fade.clear()
        thread = threading.Thread(target=fade, daemon=True)
        thread.start()

    def fade_in_stream(self, duration: float = 0.8) -> None:
        """
        Fade in the stream volume to current target level.

        Args:
            duration: Fade duration in seconds
        """
        if not self._mpv_process or self._mpv_process.poll() is not None:
            return

        def fade():
            steps = 20
            step_duration = duration / steps
            target_vol = self._volume

            # Start at 0
            self._send_mpv_command(["set_property", "volume", 0])

            for i in range(steps):
                if self._stop_fade.is_set():
                    break
                vol = target_vol * ((i + 1) / steps)
                self._send_mpv_command(["set_property", "volume", vol])
                time.sleep(step_duration)

            # Ensure final volume is set
            self._send_mpv_command(["set_property", "volume", target_vol])

        self._stop_fade.clear()
        thread = threading.Thread(target=fade, daemon=True)
        thread.start()

    def _send_tuning_command(self, command: list) -> Optional[dict]:
        """Send a command to the tuning mpv process via IPC socket."""
        if not os.path.exists(self._tuning_socket_path):
            return None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(self._tuning_socket_path)
            sock.send((json.dumps({"command": command}) + "\n").encode())
            response = sock.recv(4096).decode()
            sock.close()
            return json.loads(response)
        except Exception:
            return None

    def fade_in_tuning(self, duration: float = 0.3) -> None:
        """
        Unmute the persistent tuning sound immediately.

        Args:
            duration: Ignored (kept for API compatibility)
        """
        if not self._tuning_sound_path:
            return

        if self._tuning_active:
            return

        # Restart persistent process if it died
        if not self._tuning_process or self._tuning_process.poll() is not None:
            self._start_persistent_tuning()
            time.sleep(0.3)

        tuning_vol = int(self._volume * self._static_volume_percent / 100)
        self._send_tuning_command(["set_property", "volume", tuning_vol])
        self._tuning_volume = tuning_vol / 100.0
        self._tuning_active = True

    def fade_out_tuning(self, duration: float = 0.5) -> None:
        """
        Fade out the tuning sound (keeps process running muted).

        Args:
            duration: Fade duration in seconds
        """
        if not self._tuning_process or self._tuning_process.poll() is not None:
            return

        def fade():
            steps = 15
            step_duration = duration / steps
            start_vol = int(self._tuning_volume * 100)

            for i in range(steps):
                if self._stop_fade.is_set():
                    break
                vol = int(start_vol * (1 - (i + 1) / steps))
                self._send_tuning_command(["set_property", "volume", max(0, vol)])
                self._tuning_volume = vol / 100.0
                time.sleep(step_duration)

            # Set to 0 and mark inactive (keep process running)
            self._send_tuning_command(["set_property", "volume", 0])
            self._tuning_volume = 0.0
            self._tuning_active = False
            logger.debug("Tuning sound faded to mute")

        self._stop_fade.clear()
        thread = threading.Thread(target=fade, daemon=True)
        thread.start()

    def stop(self) -> None:
        """Stop current stream playback."""
        self._stop_status_monitor()

        if self._mpv_process:
            try:
                # Try graceful shutdown via IPC
                self._send_mpv_command(["quit"])
                self._mpv_process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                # Force kill if needed
                self._mpv_process.kill()
                self._mpv_process.wait()
            except Exception as e:
                logger.warning(f"Error stopping mpv: {e}")
                try:
                    self._mpv_process.kill()
                except:
                    pass
            finally:
                self._mpv_process = None

        self._cleanup_socket()

        with self._status_lock:
            self._status = StreamStatus.STOPPED
            self._current_url = None

        logger.info("Playback stopped")

    def set_volume(self, level: int) -> None:
        """
        Set the volume level.

        Args:
            level: Volume level from 0 to 100.
        """
        self._volume = max(0, min(100, level))

        # Update mpv volume if playing
        if self._mpv_process and self._mpv_process.poll() is None:
            self._send_mpv_command(["set_property", "volume", self._volume])

        # Update tuning sound volume only if active (not muted)
        if self._tuning_active and self._tuning_process and self._tuning_process.poll() is None:
            tuning_vol = int(self._volume * self._static_volume_percent / 100)
            self._send_tuning_command(["set_property", "volume", tuning_vol])

        logger.debug(f"Volume set to {self._volume}")

    def get_volume(self) -> int:
        """Get the current volume level (0-100)."""
        return self._volume

    def set_static_volume_percent(self, percent: int) -> None:
        """Set the static volume as a percentage of main volume (0-100)."""
        self._static_volume_percent = max(0, min(100, percent))
        logger.debug(f"Static volume percent set to {self._static_volume_percent}")

    def _get_preset_filters(self) -> list[str]:
        """Get the audio filters for the current preset."""
        preset = config.AUDIO_PRESETS.get(self._audio_preset, {})
        return preset.get("filters", [])

    def set_audio_preset(self, preset_name: str, apply_live: bool = True) -> bool:
        """
        Set the audio preset.

        Args:
            preset_name: Name of the preset (must exist in AUDIO_PRESETS)
            apply_live: If True, apply the change immediately to current stream

        Returns:
            True if preset was set successfully
        """
        if preset_name not in config.AUDIO_PRESETS:
            logger.warning(f"Unknown audio preset: {preset_name}")
            return False

        self._audio_preset = preset_name
        logger.info(f"Audio preset set to: {preset_name}")

        if apply_live:
            self._apply_filters_live()

        return True

    def _apply_filters_live(self) -> bool:
        """Apply current preset filters to the running stream via IPC."""
        if not self._mpv_process or self._mpv_process.poll() is not None:
            logger.debug("No active stream to apply filters to")
            return False

        filters = self._get_preset_filters()

        if filters:
            filter_chain = f"lavfi=[{','.join(filters)}]"
        else:
            filter_chain = ""

        # Use "af set" to replace all audio filters
        result = self._send_mpv_command(["af", "set", filter_chain])

        if result and result.get("error") == "success":
            preset_info = config.AUDIO_PRESETS.get(self._audio_preset, {})
            logger.info(f"Applied audio preset live: {preset_info.get('name', self._audio_preset)}")
            return True
        else:
            logger.warning(f"Failed to apply filters live: {result}")
            return False

    def get_audio_preset(self) -> str:
        """Get the current audio preset name."""
        return self._audio_preset

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        with self._status_lock:
            return self._status == StreamStatus.PLAYING

    def get_stream_status(self) -> str:
        """
        Get the current stream status.

        Returns:
            One of: "stopped", "loading", "playing", "error"
        """
        with self._status_lock:
            return self._status.value

    def get_current_url(self) -> Optional[str]:
        """Get the currently playing URL, or None if stopped."""
        with self._status_lock:
            return self._current_url

    def cleanup(self) -> None:
        """Clean up resources. Call when shutting down."""
        self.stop()
        # Actually kill the persistent tuning process on shutdown
        if self._tuning_process and self._tuning_process.poll() is None:
            try:
                self._tuning_process.terminate()
                self._tuning_process.wait(timeout=0.5)
            except:
                try:
                    self._tuning_process.kill()
                except:
                    pass
            self._tuning_process = None
        logger.info("AudioPlayer cleaned up")


# Convenience function for testing
def main():
    """Test the audio player with a sample stream."""
    logging.basicConfig(level=logging.DEBUG)

    player = AudioPlayer()

    print("Testing tuning sound...")
    player.play_tuning_sound()
    time.sleep(1)

    # Test with a known working YouTube stream (lofi girl)
    test_url = "https://www.youtube.com/watch?v=jfKfPfyJRdk"
    print(f"Testing stream: {test_url}")

    if player.play_url(test_url):
        print("Stream started, waiting for playback...")
        for i in range(30):
            time.sleep(1)
            status = player.get_stream_status()
            volume = player.get_volume()
            print(f"  Status: {status}, Volume: {volume}")

            if i == 10:
                print("  Setting volume to 30...")
                player.set_volume(30)
            elif i == 20:
                print("  Playing tuning sound...")
                player.play_tuning_sound()
    else:
        print("Failed to start stream")

    print("Stopping...")
    player.cleanup()
    print("Done")


if __name__ == "__main__":
    main()
