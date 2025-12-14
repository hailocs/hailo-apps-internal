"""
Elevator control interface and simulator implementation.

This module provides an abstract interface for elevator control and a
Flask-based web simulator for visualization.
"""

import logging
import threading
from abc import ABC, abstractmethod
from typing import Any

# Import config from parent package
try:
    from hailo_apps.python.gen_ai_apps.agent_tools_example import config
except ImportError:
    # Fallback for direct execution
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from hailo_apps.python.gen_ai_apps.agent_tools_example import config

logger = logging.getLogger(__name__)

# Floor data (single source of truth) - defined here to avoid circular imports
FLOORS: dict[int, dict[str, Any]] = {
    0: {
        "name": "Staff & Utilities (Basement)",
        "description": "The infrastructural and unseen level containing the boiler room, Oompa Loompa staff quarters, and other utilities necessary for maintenance and operation.",
        "keywords": ["maintenance", "boiler room", "staff quarters", "utilities", "basement", "underground", "oompa loompas", "oompa loompa", "lowest floor"]
    },
    1: {
        "name": "The Chocolate Room",
        "description": "The vast, edible garden floor. Features the Chocolate River and Waterfall. The starting point of the tour, famous for the elimination of Augustus Gloop, who fell into the river and was sucked up the pipe toward the Fudge Room.",
        "keywords": ["chocolate river", "waterfall", "edible grass", "augustus gloop", "fudge room", "garden", "simple sweets", "first floor", "ground floor", "chocolate room"]
    },
    2: {
        "name": "The Inventing Room",
        "description": "A laboratory filled with machines and bubbling pots where experimental sweets are created. This floor features the Everlasting Gobstopper and the disastrous Three-Course Dinner Chewing Gum. Violet Beauregarde was eliminated here by swelling up into a blueberry.",
        "keywords": ["inventing", "everlasting gobstopper", "gobstopper", "three-course gum", "violet beauregarde", "violet", "blueberry", "blue berry", "swelling", "chewing gum", "new candy", "experimental", "innovation", "inventing room", "laboratory", "lab", "second floor"]
    },
    3: {
        "name": "The Fizzy Lifting Drinks Room",
        "description": "The room housing the Fizzy Lifting Drinks, famous for the scene where Charlie and Grandpa Joe risk being chopped up by the ceiling fan after defying gravity and floating up. Ideal for requests about non-standard beverages or floating.",
        "keywords": ["floating", "lifting drinks", "fizzy lifting drinks", "burping", "ceiling fan", "gravity", "soda", "beverages", "charlie", "grandpa joe", "float", "fly"]
    },
    4: {
        "name": "The Nut Room",
        "description": "Dedicated to quality control where hundreds of trained Squirrels shell walnuts to find 'good' and 'bad' nuts. Veruca Salt was eliminated here, judged a 'bad nut' by the squirrels and sent down the Rubbish Chute.",
        "keywords": ["squirrels", "squirrel", "veruca salt", "bad egg", "rubbish chute", "nuts", "quality control", "i want it now", "nut room", "walnuts"]
    },
    5: {
        "name": "The Television-Chocolate Room",
        "description": "A sterile, white room containing the powerful Wonkavision camera/teleporter. It develops a way to send chocolate bars through television waves. Mike Teavee was eliminated here after shrinking himself down to a tiny size.",
        "keywords": ["tv", "television", "wonkavision", "teleporter", "shrinking", "mike teavee", "media", "broadcasting", "transmission", "top floor", "highest floor", "television room", "tv room"]
    }
}


class ElevatorInterface(ABC):
    """Abstract base class for elevator control."""

    @abstractmethod
    def move_to_floor(self, floor: int) -> None:
        """Move elevator to specified floor (0-5)."""
        pass

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Get current elevator state."""
        pass

    @abstractmethod
    def get_floor_info(self, floor: int) -> dict[str, Any] | None:
        """Get information about a specific floor."""
        pass


class SimulatedElevator(ElevatorInterface):
    """Simulator implementation using Flask web server with browser visualization."""

    def __init__(self, port: int = 5002, floors_data: dict[int, dict[str, Any]] | None = None) -> None:
        """
        Initialize simulated elevator with Flask web server.

        Args:
            port: Port for Flask web server (default: 5002)
            floors_data: Dictionary of floor data (if None, will use module-level FLOORS)
        """
        try:
            from flask import Flask, jsonify, render_template_string  # noqa: F401
        except ImportError as e:
            logger.error("Flask not available. Install with: pip install flask")
            raise ImportError("Flask is required for simulator mode") from e

        # Use provided floors_data or default to module-level FLOORS
        self.FLOORS = floors_data if floors_data is not None else FLOORS

        self.port = port
        self._current_floor = 1  # Start at Floor 1 (Chocolate Room)

        try:
            # Suppress Werkzeug logging BEFORE creating Flask app
            werkzeug_logger = logging.getLogger("werkzeug")
            werkzeug_logger.setLevel(logging.CRITICAL)
            werkzeug_logger.disabled = True

            self._app = Flask(__name__)
            self._server_thread: threading.Thread | None = None

            # Disable Flask's app logger to avoid request messages in terminal
            self._app.logger.setLevel(logging.ERROR)
            self._app.logger.disabled = True
        except Exception as e:
            logger.error("Failed to create Flask app: %s", e)
            raise

        # HTML template for elevator visualization
        self._html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Wonkavator Elevator Simulator</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
            margin: 0;
            background: #1a1a1a;
            color: #fff;
        }
        .container {
            text-align: center;
            max-width: 1200px;
            padding: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .title {
            font-size: 32px;
            font-weight: bold;
            margin-bottom: 10px;
            color: #ffd700;
            width: 100%;
        }
        .subtitle {
            font-size: 18px;
            margin-bottom: 30px;
            color: #aaa;
            width: 100%;
        }
        .building-container {
            display: flex;
            justify-content: center;
            align-items: flex-start;
            margin: 0;
            position: relative;
        }
        .building {
            display: flex;
            flex-direction: column-reverse;
            border: 3px solid #444;
            border-radius: 5px;
            overflow: hidden;
            background: #222;
            position: relative;
            margin-left: 80px;
        }
        .floor {
            display: flex;
            align-items: center;
            padding: 15px 20px;
            border-top: 2px solid #333;
            min-height: 60px;
            transition: all 0.3s ease;
            background: #2a2a2a;
        }
        .floor:first-child {
            border-top: none;
        }
        .floor.current {
            background: linear-gradient(90deg, #4a2c2a, #6a3c3a);
            border-left: 5px solid #ffd700;
            box-shadow: 0 0 20px rgba(255, 215, 0, 0.3);
        }
        .floor-number {
            font-size: 24px;
            font-weight: bold;
            width: 50px;
            text-align: center;
            color: #ffd700;
        }
        .floor.current .floor-number {
            color: #fff;
        }
        .floor-name {
            font-size: 16px;
            text-align: left;
            color: #ccc;
            flex: 1;
            padding-left: 20px;
        }
        .floor.current .floor-name {
            color: #fff;
            font-weight: bold;
        }
        .content-wrapper {
            display: flex;
            flex-direction: row;
            align-items: flex-start;
            gap: 40px;
            width: 100%;
            justify-content: center;
        }
        .info-panel {
            margin-top: 0;
            padding: 20px;
            background: #2a2a2a;
            border: 2px solid #444;
            border-radius: 10px;
            text-align: left;
            width: 400px;
            flex-shrink: 0;
        }
        .info-title {
            font-size: 24px;
            color: #ffd700;
            margin-bottom: 10px;
        }
        .info-description {
            font-size: 16px;
            color: #ccc;
            line-height: 1.6;
        }
        .elevator-indicator {
            position: absolute;
            left: 0;
            width: 60px;
            height: 60px;
            background: #ffd700;
            border-radius: 5px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            font-weight: bold;
            color: #1a1a1a;
            box-shadow: 0 0 20px rgba(255, 215, 0, 0.5);
            transition: all 0.5s ease;
            top: 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="title">🍫 Wonkavator Elevator 🍫</div>
        <div class="subtitle">The Great Glass Elevator Control System</div>

        <div class="content-wrapper">
            <div class="building-container">
                <div class="building" id="building">
                    <!-- Floors will be populated here -->
                </div>
                <div class="elevator-indicator" id="elevator">🛗</div>
            </div>

            <div class="info-panel">
                <div class="info-title" id="floor-title">The Chocolate Room</div>
                <div class="info-description" id="floor-description">Loading...</div>
            </div>
        </div>
    </div>
    <script>
        function updateElevator() {
            fetch('/state', {
                cache: 'no-store',
                headers: {
                    'Cache-Control': 'no-cache',
                    'Pragma': 'no-cache'
                }
            })
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    const building = document.getElementById('building');
                    const floorTitle = document.getElementById('floor-title');
                    const floorDescription = document.getElementById('floor-description');
                    const elevator = document.getElementById('elevator');

                    // Clear and rebuild floors
                    building.innerHTML = '';

                    // Create floors 0-5 in DOM order (0 first, 5 last)
                    // With column-reverse CSS, first DOM child appears at bottom, last at top
                    // So floor 0 will be at bottom, floor 5 at top
                    for (let i = 0; i <= 5; i++) {
                        const floorDiv = document.createElement('div');
                        floorDiv.className = 'floor';
                        if (i === data.current_floor) {
                            floorDiv.className += ' current';
                        }

                        const floorNumber = document.createElement('div');
                        floorNumber.className = 'floor-number';
                        floorNumber.textContent = i;

                        const floorName = document.createElement('div');
                        floorName.className = 'floor-name';
                        floorName.textContent = data.floors[i].name;

                        floorDiv.appendChild(floorNumber);
                        floorDiv.appendChild(floorName);
                        building.appendChild(floorDiv);
                    }

                    // Update info panel
                    floorTitle.textContent = data.current_floor_info.name;
                    floorDescription.textContent = data.current_floor_info.description;

                    // Update elevator position (visual indicator)
                    // Calculate position based on floor (0 at bottom, 5 at top)
                    // DOM order is [0,1,2,3,4,5], but column-reverse displays them visually reversed
                    // So floor i is at DOM index i, but positioned visually in reverse
                    // Need to wait for DOM to update to get accurate floor heights
                    setTimeout(() => {
                        const floors = building.querySelectorAll('.floor');
                        if (floors.length > 0 && data.current_floor >= 0 && data.current_floor <= 5) {
                            // DOM order matches floor number: floor i is at index i
                            const targetFloor = floors[data.current_floor];
                            const buildingRect = building.getBoundingClientRect();
                            const floorRect = targetFloor.getBoundingClientRect();
                            const relativeTop = floorRect.top - buildingRect.top;
                            // Center elevator vertically on the floor
                            const elevatorOffset = (floorRect.height - 60) / 2;
                            elevator.style.transform = `translateY(${relativeTop + elevatorOffset}px)`;
                        }
                    }, 10);
                })
                .catch(error => {
                    console.error('Error updating elevator:', error);
                });
        }

        // Update every 100ms
        const updateInterval = setInterval(updateElevator, 100);
        updateElevator(); // Initial update

        // Ensure interval is set up
        if (!updateInterval) {
            console.error('Failed to set up update interval');
        }
    </script>
</body>
</html>
"""

        @self._app.route("/")
        def index() -> str:
            """Serve the elevator visualization page."""
            return render_template_string(self._html_template)

        @self._app.route("/state")
        def state() -> Any:
            """Return current elevator state as JSON."""
            return jsonify(self.get_state())

        # Start Flask server in background thread
        self._start_server()

    def _start_server(self) -> None:
        """Start Flask server in background thread."""
        def run_server() -> None:
            try:
                # Run Flask server (logging already suppressed in __init__)
                self._app.run(host="127.0.0.1", port=self.port, debug=False, use_reloader=False, threaded=True)
            except OSError as e:
                if "Address already in use" in str(e):
                    logger.warning("Port %d already in use. Simulator may not start properly.", self.port)
                else:
                    logger.error("Flask server error: %s", e)
            except Exception as e:
                logger.error("Unexpected error in Flask server thread: %s", e)

        self._server_thread = threading.Thread(target=run_server, daemon=True)
        self._server_thread.start()
        # Give server a moment to start
        import time
        time.sleep(0.1)

    def move_to_floor(self, floor: int) -> None:
        """Move elevator to specified floor (0-5)."""
        if floor in self.FLOORS:
            self._current_floor = floor

    def get_state(self) -> dict[str, Any]:
        """Get current elevator state."""
        return {
            "current_floor": self._current_floor,
            "current_floor_info": self.FLOORS[self._current_floor],
            "floors": self.FLOORS,
        }

    def get_floor_info(self, floor: int) -> dict[str, Any] | None:
        """Get information about a specific floor."""
        return self.FLOORS.get(floor)

    def cleanup(self) -> None:
        """Clean up resources (shutdown Flask server)."""
        # Flask server runs in daemon thread, so it will terminate automatically
        if self._server_thread is not None and self._server_thread.is_alive():
            logger.debug("Flask elevator simulator server will terminate with main process")


# Global singleton instance for elevator controller
_elevator_controller_instance: ElevatorInterface | None = None


def create_elevator_controller() -> ElevatorInterface:
    """
    Factory function to create elevator controller (simulator only for now).
    Uses singleton pattern to ensure only one instance exists.

    Returns:
        ElevatorInterface instance (SimulatedElevator)

    Raises:
        ImportError: If required libraries are not available
        RuntimeError: If initialization fails
    """
    global _elevator_controller_instance

    # Return existing instance if available
    if _elevator_controller_instance is not None:
        return _elevator_controller_instance

    # For elevator, we only have simulator mode (no real hardware)
    _elevator_controller_instance = SimulatedElevator(port=config.ELEVATOR_SIMULATOR_PORT)

    return _elevator_controller_instance

