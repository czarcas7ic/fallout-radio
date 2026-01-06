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
    "max_volume": 100,  # Maximum volume limit (0-100), for speaker protection
    "static_volume": 60,  # Percentage of main volume (0-100)
    "wrap_stations": True,
    "loudness_normalization": False,  # Keep volume consistent across stations
    "auto_start": True,  # Automatically start playing on boot
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
