"""
Hardware interface for RGB LED and servo control.

Supports real hardware (Adafruit NeoPixel, gpiozero Servo) and simulator (Flask browser visualization).
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Any

from hailo_apps.python.api_apps.agent_tools_example import config

logger = logging.getLogger(__name__)


class RGBLEDInterface(ABC):
    """Abstract base class for RGB LED control."""

    @abstractmethod
    def set_color(self, r: int, g: int, b: int) -> None:
        """Set LED color using RGB values (0-255)."""
        pass

    @abstractmethod
    def set_intensity(self, percentage: float) -> None:
        """Set LED intensity/brightness (0-100%)."""
        pass

    @abstractmethod
    def on(self) -> None:
        """Turn LED on."""
        pass

    @abstractmethod
    def off(self) -> None:
        """Turn LED off."""
        pass

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Get current LED state."""
        pass


class NeoPixelLED(RGBLEDInterface):
    """Real hardware implementation using Adafruit NeoPixel (rpi-ws281x)."""

    def __init__(self, pin: int = 18, num_pixels: int = 1) -> None:
        """
        Initialize NeoPixel LED using rpi-ws281x.

        Args:
            pin: GPIO pin number for data line (default: 18)
            num_pixels: Number of LEDs in strip (default: 1)
        """
        try:
            from rpi_ws281x import PixelStrip
        except ImportError:
            logger.warning("rpi-ws281x library not available. Install with: pip install rpi-ws281x")
            raise

        self.pin = pin
        self.num_pixels = num_pixels
        # Default state: on with white color
        self._power = True
        self._color_rgb = (255, 255, 255)
        self._color_name = "white"
        self._intensity = 100.0

        try:
            # Create PixelStrip instance
            # LED strip configuration: pin, count, brightness, DMA channel, invert, channel
            self.strip = PixelStrip(
                num=num_pixels,
                pin=pin,
                freq_hz=800000,
                dma=10,
                invert=False,
                brightness=255,
                channel=0,
            )
            self.strip.begin()
            logger.info("NeoPixel initialized on pin %d with %d LEDs", pin, num_pixels)
            # Set default state: on with white color
            self._update_pixels()
        except Exception as e:
            logger.error("Failed to initialize NeoPixel: %s", e)
            raise

    def set_color(self, r: int, g: int, b: int, color_name: str | None = None) -> None:
        """
        Set LED color using RGB values (0-255).

        Args:
            r: Red component (0-255)
            g: Green component (0-255)
            b: Blue component (0-255)
            color_name: Optional color name (e.g., "red", "blue")
        """
        self._color_rgb = (r, g, b)
        if color_name is not None:
            self._color_name = color_name
        else:
            # Try to find color name from RGB
            self._color_name = self._find_color_name_from_rgb(r, g, b)
        if self._power:
            self._update_pixels()

    def _find_color_name_from_rgb(self, r: int, g: int, b: int) -> str:
        """Find color name from RGB values."""
        # Common color mappings (avoid circular import)
        common_colors = {
            (255, 0, 0): "red",
            (0, 255, 0): "green",
            (0, 0, 255): "blue",
            (255, 255, 0): "yellow",
            (255, 0, 255): "magenta",
            (0, 255, 255): "cyan",
            (255, 255, 255): "white",
            (0, 0, 0): "black",
            (255, 165, 0): "orange",
            (255, 192, 203): "pink",
            (128, 0, 128): "purple",
            (0, 128, 0): "lime",
            (0, 128, 128): "teal",
            (0, 0, 128): "navy",
        }
        rgb_tuple = (r, g, b)
        return common_colors.get(rgb_tuple, "custom")

    def set_intensity(self, percentage: float) -> None:
        """Set LED intensity/brightness (0-100%)."""
        self._intensity = max(0.0, min(100.0, percentage))
        if self._power:
            self._update_pixels()

    def on(self) -> None:
        """Turn LED on."""
        self._power = True
        self._update_pixels()

    def off(self) -> None:
        """Turn LED off."""
        self._power = False
        # Turn off all pixels
        for i in range(self.num_pixels):
            self.strip.setPixelColor(i, 0)
        self.strip.show()

    def _update_pixels(self) -> None:
        """Update pixel colors based on current state."""
        if not self._power:
            # Turn off all pixels
            for i in range(self.num_pixels):
                self.strip.setPixelColor(i, 0)
        else:
            # Apply intensity to color
            brightness = self._intensity / 100.0
            r = int(self._color_rgb[0] * brightness)
            g = int(self._color_rgb[1] * brightness)
            b = int(self._color_rgb[2] * brightness)
            # Convert RGB to GRB format (NeoPixel uses GRB)
            color = (g << 16) | (r << 8) | b
            # Set all pixels to the same color
            for i in range(self.num_pixels):
                self.strip.setPixelColor(i, color)
        self.strip.show()

    def get_state(self) -> dict[str, Any]:
        """Get current LED state."""
        return {
            "power": self._power,
            "color": self._color_name,
            "color_rgb": self._color_rgb,
            "intensity": self._intensity,
        }


class SimulatedLED(RGBLEDInterface):
    """Simulator implementation using Flask web server with browser visualization."""

    def __init__(self, port: int = 5000) -> None:
        """
        Initialize simulated LED with Flask web server.

        Args:
            port: Port for Flask web server (default: 5000)
        """
        try:
            from flask import Flask, jsonify, render_template_string  # noqa: F401
        except ImportError as e:
            logger.error("Flask not available. Install with: pip install flask")
            raise ImportError("Flask is required for simulator mode") from e

        self.port = port
        # Default state: on with white color
        self._power = True
        self._color_rgb = (255, 255, 255)
        self._color_name = "white"
        self._intensity = 100.0

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

        # HTML template for LED visualization
        self._html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>LED Simulator</title>
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
        .led-container {
            text-align: center;
        }
        .led {
            width: 200px;
            height: 200px;
            border-radius: 50%;
            border: 3px solid #333;
            margin: 20px;
            box-shadow: 0 0 30px rgba(255,255,255,0.3);
            transition: all 0.3s ease;
        }
        .led.off {
            background: #000;
            box-shadow: none;
        }
        .status {
            margin-top: 20px;
            font-size: 18px;
        }
        .info {
            margin-top: 10px;
            font-size: 14px;
            color: #aaa;
        }
    </style>
</head>
<body>
    <div class="led-container">
        <div class="led" id="led"></div>
        <div class="status" id="status">LED Off</div>
        <div class="info" id="info">Color: RGB(0, 0, 0) | Intensity: 0%</div>
    </div>
    <script>
        function updateLED() {
            fetch('/state')
                .then(response => response.json())
                .then(data => {
                    const led = document.getElementById('led');
                    const status = document.getElementById('status');
                    const info = document.getElementById('info');

                    if (data.power) {
                        const r = Math.round(data.color_rgb[0] * data.intensity / 100);
                        const g = Math.round(data.color_rgb[1] * data.intensity / 100);
                        const b = Math.round(data.color_rgb[2] * data.intensity / 100);
                        led.style.background = `rgb(${r}, ${g}, ${b})`;
                        led.style.boxShadow = `0 0 30px rgba(${r}, ${g}, ${b}, 0.5)`;
                        led.classList.remove('off');
                        status.textContent = 'LED On';
                        info.textContent = `Color: RGB(${data.color_rgb[0]}, ${data.color_rgb[1]}, ${data.color_rgb[2]}) | Intensity: ${data.intensity.toFixed(0)}%`;
                    } else {
                        led.style.background = '#000';
                        led.style.boxShadow = 'none';
                        led.classList.add('off');
                        status.textContent = 'LED Off';
                        info.textContent = 'Color: RGB(0, 0, 0) | Intensity: 0%';
                    }
                })
                .catch(error => console.error('Error:', error));
        }

        // Update every 100ms
        setInterval(updateLED, 100);
        updateLED(); // Initial update
    </script>
</body>
</html>
"""

        @self._app.route("/")
        def index() -> str:
            """Serve the LED visualization page."""
            return render_template_string(self._html_template)

        @self._app.route("/state")
        def state() -> Any:
            """Return current LED state as JSON."""
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

    def set_color(self, r: int, g: int, b: int, color_name: str | None = None) -> None:
        """
        Set LED color using RGB values (0-255).

        Args:
            r: Red component (0-255)
            g: Green component (0-255)
            b: Blue component (0-255)
            color_name: Optional color name (e.g., "red", "blue")
        """
        self._color_rgb = (r, g, b)
        if color_name is not None:
            self._color_name = color_name
        else:
            # Try to find color name from RGB
            self._color_name = self._find_color_name_from_rgb(r, g, b)

    def _find_color_name_from_rgb(self, r: int, g: int, b: int) -> str:
        """Find color name from RGB values."""
        # Common color mappings (avoid circular import)
        common_colors = {
            (255, 0, 0): "red",
            (0, 255, 0): "green",
            (0, 0, 255): "blue",
            (255, 255, 0): "yellow",
            (255, 0, 255): "magenta",
            (0, 255, 255): "cyan",
            (255, 255, 255): "white",
            (0, 0, 0): "black",
            (255, 165, 0): "orange",
            (255, 192, 203): "pink",
            (128, 0, 128): "purple",
            (0, 128, 0): "lime",
            (0, 128, 128): "teal",
            (0, 0, 128): "navy",
        }
        rgb_tuple = (r, g, b)
        return common_colors.get(rgb_tuple, "custom")

    def set_intensity(self, percentage: float) -> None:
        """Set LED intensity/brightness (0-100%)."""
        self._intensity = max(0.0, min(100.0, percentage))

    def on(self) -> None:
        """Turn LED on."""
        self._power = True

    def off(self) -> None:
        """Turn LED off."""
        self._power = False

    def get_state(self) -> dict[str, Any]:
        """Get current LED state."""
        return {
            "power": self._power,
            "color": self._color_name,
            "color_rgb": list(self._color_rgb),
            "intensity": self._intensity,
        }


class ServoInterface(ABC):
    """Abstract base class for servo control."""

    @abstractmethod
    def set_angle(self, angle: float) -> None:
        """Set servo to absolute angle."""
        pass

    @abstractmethod
    def move_relative(self, delta: float) -> None:
        """Move servo by relative angle."""
        pass

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """Get current servo state."""
        pass


class GpiozeroServo(ServoInterface):
    """Real hardware implementation using gpiozero Servo."""

    def __init__(self, pin: int = 17, min_angle: float = -90.0, max_angle: float = 90.0) -> None:
        """
        Initialize servo using gpiozero.

        Args:
            pin: GPIO pin number for servo control signal (default: 17)
            min_angle: Minimum angle in degrees (default: -90)
            max_angle: Maximum angle in degrees (default: 90)
        """
        try:
            from gpiozero import Servo
        except ImportError:
            logger.warning("gpiozero library not available. Install with: pip install gpiozero")
            raise

        self.pin = pin
        self.min_angle = min_angle
        self.max_angle = max_angle
        self._current_angle = 0.0  # Default to center position

        try:
            # gpiozero.Servo expects values -1.0 to 1.0
            # We map -90 to 90 degrees to -1.0 to 1.0
            self.servo = Servo(pin)
            logger.info("Servo initialized on pin %d with angle range %.1f to %.1f degrees", pin, min_angle, max_angle)
            # Set default position to center (0 degrees)
            self._update_servo(0.0)
        except Exception as e:
            logger.error("Failed to initialize servo: %s", e)
            raise

    def _angle_to_gpiozero_value(self, angle: float) -> float:
        """
        Convert angle in degrees to gpiozero value (-1.0 to 1.0).

        Args:
            angle: Angle in degrees

        Returns:
            gpiozero value (-1.0 to 1.0)
        """
        # Clamp angle to valid range
        clamped_angle = max(self.min_angle, min(self.max_angle, angle))
        # Map angle range to -1.0 to 1.0
        # Linear mapping: (angle - min) / (max - min) maps to -1.0 to 1.0
        # So: value = 2 * (angle - min) / (max - min) - 1.0
        if self.max_angle == self.min_angle:
            return 0.0
        normalized = (clamped_angle - self.min_angle) / (self.max_angle - self.min_angle)
        return 2.0 * normalized - 1.0

    def _update_servo(self, angle: float) -> None:
        """
        Update servo position to given angle.

        Args:
            angle: Target angle in degrees
        """
        gpiozero_value = self._angle_to_gpiozero_value(angle)
        self.servo.value = gpiozero_value
        self._current_angle = max(self.min_angle, min(self.max_angle, angle))

    def set_angle(self, angle: float) -> None:
        """Set servo to absolute angle."""
        self._update_servo(angle)

    def move_relative(self, delta: float) -> None:
        """Move servo by relative angle."""
        new_angle = self._current_angle + delta
        self._update_servo(new_angle)

    def get_state(self) -> dict[str, Any]:
        """Get current servo state."""
        return {
            "angle": self._current_angle,
            "min_angle": self.min_angle,
            "max_angle": self.max_angle,
        }


class SimulatedServo(ServoInterface):
    """Simulator implementation using Flask web server with browser visualization."""

    def __init__(self, port: int = 5001, min_angle: float = -90.0, max_angle: float = 90.0) -> None:
        """
        Initialize simulated servo with Flask web server.

        Args:
            port: Port for Flask web server (default: 5001)
            min_angle: Minimum angle in degrees (default: -90)
            max_angle: Maximum angle in degrees (default: 90)
        """
        try:
            from flask import Flask, jsonify, render_template_string  # noqa: F401
        except ImportError as e:
            logger.error("Flask not available. Install with: pip install flask")
            raise ImportError("Flask is required for simulator mode") from e

        self.port = port
        self.min_angle = min_angle
        self.max_angle = max_angle
        self._current_angle = 0.0  # Default to center position

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

        # HTML template for servo visualization
        self._html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Servo Simulator</title>
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
        .servo-container {
            text-align: center;
            position: relative;
        }
        .scale-container {
            width: 400px;
            height: 200px;
            position: relative;
            margin: 0 auto 20px;
            overflow: visible;
        }
        .scale-arc {
            width: 400px;
            height: 200px;
            position: relative;
        }
        .scale-mark {
            position: absolute;
            width: 2px;
            height: 15px;
            background: #888;
            top: 0;
            left: 50%;
            transform-origin: 50% 200px;
        }
        .scale-mark.major {
            height: 20px;
            background: #aaa;
            width: 3px;
        }
        .scale-label {
            position: absolute;
            top: 35px;
            left: 50%;
            transform-origin: 50% 200px;
            font-size: 12px;
            color: #aaa;
            text-align: center;
            width: 30px;
            margin-left: -15px;
        }
        .servo-base {
            width: 100px;
            height: 100px;
            background: #444;
            border-radius: 10px;
            position: absolute;
            border: 2px solid #666;
            left: 50%;
            top: 200px;
            margin-left: -50px;
            margin-top: -50px;
        }
        .servo-arm-container {
            position: absolute;
            left: 50%;
            top: 50%;
            margin-top: -8px;
            transform-origin: 0 50%;
            width: 150px;
            height: 16px;
        }
        .servo-arm {
            width: 120px;
            height: 8px;
            background: #888;
            position: absolute;
            left: 0;
            top: 4px;
            border-radius: 0 4px 4px 0;
            filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));
        }
        .servo-arm::before {
            content: '';
            position: absolute;
            left: -10px;
            top: -2px;
            width: 10px;
            height: 10px;
            background: #666;
            border-radius: 50%;
        }
        .servo-pivot {
            width: 20px;
            height: 20px;
            background: #666;
            border-radius: 50%;
            position: absolute;
            left: 50%;
            top: 50%;
            transform: translate(-50%, -50%);
            border: 2px solid #888;
            z-index: 10;
        }
        .status {
            margin-top: 100px;
            font-size: 18px;
        }
        .info {
            margin-top: 10px;
            font-size: 14px;
            color: #aaa;
        }
    </style>
</head>
<body>
    <div class="servo-container">
        <div class="scale-container">
            <div class="scale-arc" id="scale-arc"></div>
            <div class="servo-base">
                <div class="servo-pivot"></div>
                <div class="servo-arm-container" id="servo-arm-container">
                    <div class="servo-arm" id="servo-arm"></div>
                </div>
            </div>
        </div>
        <div class="status" id="status">Servo Position: 0°</div>
        <div class="info" id="info">Angle Range: -90° to 90°</div>
    </div>
    <script>
        function createScale(minAngle, maxAngle) {
            const scaleArc = document.getElementById('scale-arc');
            scaleArc.innerHTML = '';

            // Create major marks every 30 degrees
            // Reverse the angle display so visual left shows negative, right shows positive
            for (let angle = minAngle; angle <= maxAngle; angle += 30) {
                const mark = document.createElement('div');
                mark.className = 'scale-mark major';
                // rotation needs to account for the -90° offset we apply to the arm
                const rotation = -angle;
                mark.style.transform = `rotate(${rotation}deg)`;
                scaleArc.appendChild(mark);

                // Add label with counter-rotated text
                const label = document.createElement('div');
                label.className = 'scale-label';
                const span = document.createElement('span');
                // Display the reversed angle: visual rotation matches servo angle
                span.textContent = (-angle) + '°';
                label.appendChild(span);
                label.style.transform = `rotate(${rotation}deg)`;
                scaleArc.appendChild(label);
            }

            // Create minor marks every 15 degrees
            for (let angle = minAngle; angle <= maxAngle; angle += 15) {
                if (angle % 30 !== 0) {
                    const mark = document.createElement('div');
                    mark.className = 'scale-mark';
                    const rotation = -angle;
                    mark.style.transform = `rotate(${rotation}deg)`;
                    scaleArc.appendChild(mark);
                }
            }
        }

        function updateServo() {
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
                    const armContainer = document.getElementById('servo-arm-container');
                    const status = document.getElementById('status');
                    const info = document.getElementById('info');

                    if (!armContainer || !status || !info) {
                        console.error('Required DOM elements not found');
                        return;
                    }

                    const angle = data.angle;
                    // Rotation mapping: -90° = LEFT, 0° = UP, +90° = RIGHT
                    // CSS rotates clockwise from 0° (pointing right)
                    // We need to subtract 90° to shift zero point from RIGHT to UP
                    // So: angle=-90 → rotation=-180 (LEFT), angle=0 → rotation=-90 (UP), angle=+90 → rotation=0 (RIGHT)
                    const rotation = angle - 90;
                    armContainer.style.transform = `rotate(${rotation}deg)`;
                    status.textContent = `Servo Position: ${angle.toFixed(1)}°`;
                    info.textContent = `Angle Range: ${data.min_angle}° to ${data.max_angle}°`;

                    // Initialize scale on first update
                    if (document.getElementById('scale-arc').children.length === 0) {
                        createScale(data.min_angle, data.max_angle);
                    }
                })
                .catch(error => {
                    console.error('Error updating servo:', error);
                });
        }

        // Update every 100ms
        const updateInterval = setInterval(updateServo, 100);
        updateServo(); // Initial update

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
            """Serve the servo visualization page."""
            return render_template_string(self._html_template)

        @self._app.route("/state")
        def state() -> Any:
            """Return current servo state as JSON."""
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

    def set_angle(self, angle: float) -> None:
        """Set servo to absolute angle."""
        self._current_angle = max(self.min_angle, min(self.max_angle, angle))

    def move_relative(self, delta: float) -> None:
        """Move servo by relative angle."""
        new_angle = self._current_angle + delta
        self._current_angle = max(self.min_angle, min(self.max_angle, new_angle))

    def get_state(self) -> dict[str, Any]:
        """Get current servo state."""
        return {
            "angle": self._current_angle,
            "min_angle": self.min_angle,
            "max_angle": self.max_angle,
        }


def create_led_controller() -> RGBLEDInterface:
    """
    Factory function to create appropriate LED controller based on configuration.

    Returns:
        RGBLEDInterface instance (NeoPixelLED or SimulatedLED)

    Raises:
        ImportError: If required libraries are not available
        ValueError: If configuration is invalid
    """
    hardware_mode = config.HARDWARE_MODE.lower()

    if hardware_mode == "real":
        # Try to create real hardware controller
        try:
            return NeoPixelLED(
                pin=config.NEOPIXEL_PIN,
                num_pixels=config.NEOPIXEL_COUNT,
            )
        except ImportError as e:
            logger.warning("Hardware mode requested but library not available: %s", e)
            logger.info("Falling back to simulator mode")
            return SimulatedLED(port=config.FLASK_PORT)
        except Exception as e:
            logger.warning("Hardware initialization failed: %s", e)
            logger.info("Falling back to simulator mode")
            return SimulatedLED(port=config.FLASK_PORT)
    else:
        # Default to simulator
        return SimulatedLED(port=config.FLASK_PORT)


# Global singleton instance for servo controller
_servo_controller_instance: ServoInterface | None = None


def create_servo_controller() -> ServoInterface:
    """
    Factory function to create appropriate servo controller based on configuration.
    Uses singleton pattern to ensure only one instance exists.

    Returns:
        ServoInterface instance (GpiozeroServo or SimulatedServo)

    Raises:
        ImportError: If required libraries are not available
        ValueError: If configuration is invalid
    """
    global _servo_controller_instance

    # Return existing instance if available
    if _servo_controller_instance is not None:
        return _servo_controller_instance

    hardware_mode = config.HARDWARE_MODE.lower()

    if hardware_mode == "real":
        # Try to create real hardware controller
        try:
            _servo_controller_instance = GpiozeroServo(
                pin=config.SERVO_PIN,
                min_angle=config.SERVO_MIN_ANGLE,
                max_angle=config.SERVO_MAX_ANGLE,
            )
        except ImportError as e:
            logger.warning("Hardware mode requested but library not available: %s", e)
            logger.info("Falling back to simulator mode")
            _servo_controller_instance = SimulatedServo(
                port=config.SERVO_SIMULATOR_PORT,
                min_angle=config.SERVO_MIN_ANGLE,
                max_angle=config.SERVO_MAX_ANGLE,
            )
        except Exception as e:
            logger.warning("Hardware initialization failed: %s", e)
            logger.info("Falling back to simulator mode")
            _servo_controller_instance = SimulatedServo(
                port=config.SERVO_SIMULATOR_PORT,
                min_angle=config.SERVO_MIN_ANGLE,
                max_angle=config.SERVO_MAX_ANGLE,
            )
    else:
        # Default to simulator
        _servo_controller_instance = SimulatedServo(
            port=config.SERVO_SIMULATOR_PORT,
            min_angle=config.SERVO_MIN_ANGLE,
            max_angle=config.SERVO_MAX_ANGLE,
        )

    return _servo_controller_instance

