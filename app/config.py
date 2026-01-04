"""
Configuration management for Fallout Radio.

Handles paths, loading/saving JSON data, and default configurations.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Determine base paths
APP_DIR = Path(__file__).parent
PROJECT_ROOT = APP_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
SOUNDS_DIR = APP_DIR / "static" / "sounds"

# Data file paths
PACKS_FILE = DATA_DIR / "packs.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
DURATION_CACHE_FILE = DATA_DIR / "duration_cache.json"

# Default configurations
DEFAULT_SETTINGS = {
    "default_volume": 40,
    "static_volume": 60,  # Percentage of main volume (0-100)
    "wrap_stations": True,
    "audio_preset": "small_speaker",  # Audio EQ preset name
}

# Audio presets - each is a list of ffmpeg audio filters
# These can be changed live without restarting the stream
AUDIO_PRESETS = {
    "flat": {
        "name": "Flat (No Processing)",
        "description": "Pure audio, no EQ or filters",
        "filters": [],
    },
    "bass_cut": {
        "name": "Bass Cut Only",
        "description": "Removes sub-bass rumble, no other changes",
        "filters": ["highpass=f=100:poles=2"],
    },
    "small_speaker": {
        "name": "Small Speaker",
        "description": "Optimized for small speakers - cuts rumble, boosts mids",
        "filters": [
            "highpass=f=80:poles=2",
            "equalizer=f=120:width_type=o:w=1.5:g=2",
            "equalizer=f=300:width_type=o:w=1.5:g=2",
            "equalizer=f=3000:width_type=o:w=2:g=1",
        ],
    },
    "warm": {
        "name": "Warm",
        "description": "Subtle warmth, good for vocals and jazz",
        "filters": [
            "highpass=f=60:poles=2",
            "equalizer=f=200:width_type=o:w=2:g=2",
            "equalizer=f=400:width_type=o:w=2:g=1",
        ],
    },
    "bright": {
        "name": "Bright",
        "description": "Enhanced treble clarity",
        "filters": [
            "highpass=f=80:poles=2",
            "equalizer=f=4000:width_type=o:w=2:g=2",
            "equalizer=f=8000:width_type=o:w=2:g=1.5",
        ],
    },
    "vocal": {
        "name": "Vocal Focus",
        "description": "Emphasizes vocal frequencies",
        "filters": [
            "highpass=f=100:poles=2",
            "equalizer=f=250:width_type=o:w=2:g=-1",
            "equalizer=f=2000:width_type=o:w=1.5:g=2",
            "equalizer=f=4000:width_type=o:w=2:g=1",
        ],
    },
    "bass_boost": {
        "name": "Bass Boost",
        "description": "For speakers that can handle bass (may distort on small speakers)",
        "filters": [
            "equalizer=f=60:width_type=o:w=2:g=4",
            "equalizer=f=120:width_type=o:w=2:g=2",
        ],
    },
    "lofi": {
        "name": "Lo-Fi",
        "description": "Vintage lo-fi sound - rolled off highs and lows",
        "filters": [
            "highpass=f=120:poles=2",
            "lowpass=f=8000:poles=2",
            "equalizer=f=400:width_type=o:w=2:g=2",
        ],
    },
    "radio": {
        "name": "Vintage Radio",
        "description": "Old AM radio style - heavy mid focus",
        "filters": [
            "highpass=f=200:poles=2",
            "lowpass=f=5000:poles=2",
            "equalizer=f=1000:width_type=o:w=1:g=3",
        ],
    },
    "loudness": {
        "name": "Loudness (Volume Normalized)",
        "description": "EBU R128 loudness normalization - may cause compression artifacts",
        "filters": ["loudnorm=I=-16:TP=-1.5:LRA=11"],
    },
    "treble_tame": {
        "name": "Treble Tame",
        "description": "Reduces harsh highs - gentle rolloff above 8kHz",
        "filters": [
            "highpass=f=80:poles=2",
            "lowpass=f=12000:poles=2",
            "equalizer=f=6000:width_type=o:w=2:g=-2",
        ],
    },
    "smooth": {
        "name": "Smooth",
        "description": "Soft, rounded sound - cuts harshness at 4-8kHz",
        "filters": [
            "highpass=f=80:poles=2",
            "equalizer=f=4000:width_type=o:w=1.5:g=-3",
            "equalizer=f=7000:width_type=o:w=2:g=-2",
            "lowpass=f=14000:poles=1",
        ],
    },
    "deharsh": {
        "name": "De-Harsh",
        "description": "Aggressive cut at harsh frequencies (5-7kHz)",
        "filters": [
            "highpass=f=80:poles=2",
            "equalizer=f=5500:width_type=o:w=1:g=-4",
        ],
    },
    "mellow": {
        "name": "Mellow",
        "description": "Very soft highs - like listening through a blanket",
        "filters": [
            "highpass=f=80:poles=2",
            "lowpass=f=8000:poles=2",
        ],
    },
    "test_bad": {
        "name": "TEST - Sounds Terrible",
        "description": "Intentionally bad - tinny phone speaker simulation",
        "filters": [
            "highpass=f=500:poles=2",
            "lowpass=f=3000:poles=2",
            "equalizer=f=1000:width_type=o:w=0.5:g=8",
        ],
    },
}

DEFAULT_PACKS_DATA = {
    "packs": [],
    "active_pack_id": None,
}


def ensure_data_dir() -> None:
    """Ensure the data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_json(file_path: Path, default: dict) -> dict:
    """
    Load JSON data from a file, returning default if file doesn't exist.

    Args:
        file_path: Path to the JSON file
        default: Default data to return if file doesn't exist

    Returns:
        Loaded data or default
    """
    if not file_path.exists():
        logger.info(f"File not found, using defaults: {file_path}")
        return default.copy()

    try:
        with open(file_path, "r") as f:
            data = json.load(f)
            logger.debug(f"Loaded data from {file_path}")
            return data
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {file_path}: {e}")
        return default.copy()
    except Exception as e:
        logger.error(f"Failed to load {file_path}: {e}")
        return default.copy()


def save_json(file_path: Path, data: dict) -> bool:
    """
    Save data to a JSON file.

    Args:
        file_path: Path to the JSON file
        data: Data to save

    Returns:
        True if successful, False otherwise
    """
    ensure_data_dir()

    try:
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Saved data to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save {file_path}: {e}")
        return False


def load_packs() -> dict:
    """Load station packs data."""
    return load_json(PACKS_FILE, DEFAULT_PACKS_DATA)


def save_packs(data: dict) -> bool:
    """Save station packs data."""
    return save_json(PACKS_FILE, data)


def load_settings() -> dict:
    """Load application settings."""
    return load_json(SETTINGS_FILE, DEFAULT_SETTINGS)


def save_settings(data: dict) -> bool:
    """Save application settings."""
    return save_json(SETTINGS_FILE, data)


def load_duration_cache() -> dict:
    """Load cached video durations."""
    return load_json(DURATION_CACHE_FILE, {})


def save_duration_cache(data: dict) -> bool:
    """Save video duration cache."""
    return save_json(DURATION_CACHE_FILE, data)
