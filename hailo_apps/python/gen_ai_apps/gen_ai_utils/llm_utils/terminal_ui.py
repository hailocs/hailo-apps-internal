"""
Terminal UI module for Hailo applications.

Handles terminal interactions, input reading, and banner display.
"""
import platform
import logging
import sys
# Platform-specific terminal modules
if platform.system() == "Windows":
    import msvcrt
else:
    import termios
    import tty

# Setup logger
logger = logging.getLogger(__name__)


class TerminalUI:
    """
    Handles terminal user interface interactions.
    """

    @staticmethod
    def show_banner(title: str = "Terminal Voice Assistant", controls: dict = None):
        """
        Displays the full application banner with instructions.

        Args:
            title (str): The title to display in the banner.
            controls (dict): Dictionary of control keys and their descriptions.
                           If None, uses default voice assistant controls.
        """
        if controls is None:
            controls = {
                "SPACE": "start/stop recording",
                "Q": "quit",
                "C": "clear context",
            }

        print("\n" + "=" * 50)
        print(f"      {title}")
        print("=" * 50)
        print("Controls:")
        for key, description in controls.items():
            print(f"  - Press {key} to {description}.")
        print("=" * 50 + "\n")

    @staticmethod
    def get_char() -> str:
        """
        Read a single character from stdin.

        - Windows: uses msvcrt.getwch().
        - POSIX: uses tty.setcbreak() on a real terminal so signals (Ctrl+C) are preserved.
        - Falls back to a simple read when stdin is not a TTY (e.g. redirected).
        - Returns '\\x03' on KeyboardInterrupt to keep current handling logic.

        Returns:
            str: The character read from stdin.
        """
        # Non-interactive fallback (e.g. run with input redirected)
        if not sys.stdin.isatty():
            ch = sys.stdin.read(1)
            return ch or ""

        # Windows path
        if platform.system() == "Windows":
            try:
                ch = msvcrt.getwch()
                return ch
            except KeyboardInterrupt:
                logger.debug("KeyboardInterrupt received in terminal input")
                return "\x03"
            except Exception as e:
                logger.warning("Terminal input error: %s", e)
                raise
        
        # POSIX path
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            # cbreak is less invasive than raw: Ctrl+C still raises KeyboardInterrupt
            tty.setcbreak(fd)
            try:
                ch = sys.stdin.read(1)
            except KeyboardInterrupt:
                # Return control character for Ctrl+C
                logger.debug("KeyboardInterrupt received in terminal input")
                return "\x03"
        except Exception as e:
            logger.warning("Terminal input error: %s", e)
            raise
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        return ch
