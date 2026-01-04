"""
Flask application entry point for Fallout Radio.

Provides REST API and WebSocket endpoints for the web UI.
"""

import logging
import os
from flask import Flask, jsonify, request, render_template
from flask_socketio import SocketIO, emit

from .radio_core import RadioCore
from .gpio_handler import create_gpio_handler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "fallout-radio-secret-key")

# Create SocketIO instance
socketio = SocketIO(app, cors_allowed_origins="*")

# Global instances (initialized in create_app or on first request)
radio_core: RadioCore = None
gpio_handler = None


def get_radio_core() -> RadioCore:
    """Get or create the RadioCore instance."""
    global radio_core
    if radio_core is None:
        radio_core = RadioCore()
        # Register callback for state changes
        radio_core.register_state_callback(broadcast_state_update)
    return radio_core


def get_gpio_handler():
    """Get or create the GPIO handler instance."""
    global gpio_handler
    if gpio_handler is None:
        gpio_handler = create_gpio_handler(get_radio_core())
        gpio_handler.start()
    return gpio_handler


def broadcast_state_update():
    """Broadcast state update to all connected WebSocket clients."""
    state = get_radio_core().get_current_state()
    socketio.emit("state_update", state)


# =============================================================================
# Template Routes
# =============================================================================

@app.route("/")
def index():
    """Main page - Now Playing."""
    return render_template("now_playing.html")


@app.route("/packs")
def packs_page():
    """Station packs management page."""
    return render_template("packs.html")


@app.route("/packs/<pack_id>")
def pack_editor_page(pack_id):
    """Pack editor page."""
    return render_template("pack_editor.html", pack_id=pack_id)


@app.route("/settings")
def settings_page():
    """Settings page."""
    return render_template("settings.html")


# =============================================================================
# API: State
# =============================================================================

@app.route("/api/state")
def api_get_state():
    """Get current radio state."""
    state = get_radio_core().get_current_state()
    return jsonify(state)


# =============================================================================
# API: Packs
# =============================================================================

@app.route("/api/packs", methods=["GET"])
def api_list_packs():
    """List all station packs."""
    packs = get_radio_core().get_packs()
    return jsonify({"packs": packs})


@app.route("/api/packs", methods=["POST"])
def api_create_pack():
    """Create a new station pack."""
    data = request.get_json()
    if not data or "name" not in data:
        return jsonify({"error": "Name is required"}), 400

    pack = get_radio_core().create_pack(data["name"])
    return jsonify(pack), 201


@app.route("/api/packs/<pack_id>", methods=["GET"])
def api_get_pack(pack_id):
    """Get a single pack by ID."""
    pack = get_radio_core().get_pack(pack_id)
    if not pack:
        return jsonify({"error": "Pack not found"}), 404
    return jsonify(pack)


@app.route("/api/packs/<pack_id>", methods=["PUT"])
def api_update_pack(pack_id):
    """Update a pack's properties."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    pack = get_radio_core().update_pack(pack_id, data)
    if not pack:
        return jsonify({"error": "Pack not found"}), 404
    return jsonify(pack)


@app.route("/api/packs/<pack_id>", methods=["DELETE"])
def api_delete_pack(pack_id):
    """Delete a pack."""
    success = get_radio_core().delete_pack(pack_id)
    if not success:
        return jsonify({"error": "Pack not found"}), 404
    return jsonify({"success": True})


@app.route("/api/packs/<pack_id>/activate", methods=["POST"])
def api_activate_pack(pack_id):
    """Set a pack as the active pack."""
    success = get_radio_core().set_active_pack(pack_id)
    if not success:
        return jsonify({"error": "Pack not found"}), 404
    return jsonify({"success": True})


# =============================================================================
# API: Stations (within a pack)
# =============================================================================

@app.route("/api/packs/<pack_id>/stations", methods=["POST"])
def api_add_station(pack_id):
    """Add a station to a pack."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    if "name" not in data or "url" not in data:
        return jsonify({"error": "Name and URL are required"}), 400

    station = get_radio_core().add_station(pack_id, data["name"], data["url"])
    if not station:
        return jsonify({"error": "Pack not found"}), 404
    return jsonify(station), 201


@app.route("/api/packs/<pack_id>/stations/<station_id>", methods=["PUT"])
def api_update_station(pack_id, station_id):
    """Update a station's properties."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    station = get_radio_core().update_station(pack_id, station_id, data)
    if not station:
        return jsonify({"error": "Station not found"}), 404
    return jsonify(station)


@app.route("/api/packs/<pack_id>/stations/<station_id>", methods=["DELETE"])
def api_delete_station(pack_id, station_id):
    """Delete a station from a pack."""
    success = get_radio_core().delete_station(pack_id, station_id)
    if not success:
        return jsonify({"error": "Station not found"}), 404
    return jsonify({"success": True})


@app.route("/api/packs/<pack_id>/stations/reorder", methods=["POST"])
def api_reorder_stations(pack_id):
    """Reorder stations in a pack."""
    data = request.get_json()
    if not data or "station_ids" not in data:
        return jsonify({"error": "station_ids array is required"}), 400

    success = get_radio_core().reorder_stations(pack_id, data["station_ids"])
    if not success:
        return jsonify({"error": "Pack not found"}), 404
    return jsonify({"success": True})


# =============================================================================
# API: Settings
# =============================================================================

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    """Get current settings."""
    settings = get_radio_core().get_settings()
    return jsonify(settings)


@app.route("/api/settings", methods=["PUT"])
def api_update_settings():
    """Update settings."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    settings = get_radio_core().update_settings(data)
    return jsonify(settings)


# =============================================================================
# API: Control
# =============================================================================

@app.route("/api/control/volume", methods=["POST"])
def api_set_volume():
    """Set the volume level."""
    data = request.get_json()
    if not data or "level" not in data:
        return jsonify({"error": "level is required"}), 400

    level = data["level"]
    if not isinstance(level, int) or level < 0 or level > 100:
        return jsonify({"error": "level must be an integer 0-100"}), 400

    get_radio_core().set_volume(level)
    return jsonify({"volume": get_radio_core().get_volume()})


@app.route("/api/control/station", methods=["POST"])
def api_switch_station():
    """Switch to a station."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    core = get_radio_core()

    if "index" in data:
        # Switch to specific station index
        core.switch_to_station(data["index"])
    elif "direction" in data:
        # Switch next/previous or toggle power
        direction = data["direction"]
        if direction == "next":
            core.next_station()
        elif direction == "prev":
            core.previous_station()
        elif direction == "power":
            core.toggle_power()
        else:
            return jsonify({"error": "direction must be 'next', 'prev', or 'power'"}), 400
    else:
        return jsonify({"error": "index or direction is required"}), 400

    return jsonify(core.get_current_state())


# =============================================================================
# WebSocket Events
# =============================================================================

@socketio.on("connect")
def handle_connect():
    """Handle client connection."""
    logger.info("WebSocket client connected")
    # Send current state to newly connected client
    state = get_radio_core().get_current_state()
    emit("state_update", state)


@socketio.on("disconnect")
def handle_disconnect():
    """Handle client disconnection."""
    logger.info("WebSocket client disconnected")


@socketio.on("get_state")
def handle_get_state():
    """Handle request for current state."""
    state = get_radio_core().get_current_state()
    emit("state_update", state)


@socketio.on("set_volume")
def handle_set_volume(data):
    """Handle volume change via WebSocket."""
    if "level" in data:
        get_radio_core().set_volume(data["level"])


@socketio.on("switch_station")
def handle_switch_station(data):
    """Handle station switch via WebSocket."""
    core = get_radio_core()
    if "index" in data:
        core.switch_to_station(data["index"])
    elif "direction" in data:
        if data["direction"] == "next":
            core.next_station()
        elif data["direction"] == "prev":
            core.previous_station()
        elif data["direction"] == "power":
            core.toggle_power()


@socketio.on("activate_pack")
def handle_activate_pack(data):
    """Handle pack activation via WebSocket."""
    if "pack_id" in data:
        get_radio_core().set_active_pack(data["pack_id"])


# =============================================================================
# Application Factory & Entry Point
# =============================================================================

def create_app():
    """Application factory for creating the Flask app."""
    # Initialize core components
    get_radio_core()
    get_gpio_handler()
    return app


def run_server(host="0.0.0.0", port=5000, debug=False):
    """Run the Flask-SocketIO server."""
    logger.info(f"Starting Fallout Radio server on {host}:{port}")

    # Initialize components
    get_radio_core()
    get_gpio_handler()

    # Run with SocketIO
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    run_server(port=5050, debug=False)
