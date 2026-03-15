"""LPR display panel — separate OpenCV window showing recognized plates."""

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Display panel constants
# ---------------------------------------------------------------------------
PANEL_WIDTH = 420
ROW_HEIGHT = 60
CROP_DISPLAY_W = 140
CROP_DISPLAY_H = 48
BG_COLOR = (30, 30, 30)
TEXT_COLOR = (220, 220, 220)
HEADER_HEIGHT = 36


def lpr_display_thread(user_data):
    """Runs in a separate thread. Shows a scrollable panel of recognized plates.
    Note: cv2.namedWindow must be called from the main thread before starting this thread."""
    scroll_offset = 0  # 0 = top (newest)

    def on_mouse(event, x, y, flags, param):
        nonlocal scroll_offset
        if event == cv2.EVENT_MOUSEWHEEL:
            if flags > 0:
                scroll_offset = max(0, scroll_offset - 1)
            else:
                scroll_offset += 1

    cv2.setMouseCallback("LPR Panel", on_mouse)

    while user_data.running:
        with user_data.plate_log_lock:
            log_snapshot = list(user_data.plate_log)

        total = len(log_snapshot)
        # Clamp scroll offset
        win_h = 700
        visible_rows = max(1, (win_h - HEADER_HEIGHT) // ROW_HEIGHT)
        max_scroll = max(0, total - visible_rows)
        scroll_offset = min(scroll_offset, max_scroll)

        # Build panel image
        panel = np.full((win_h, PANEL_WIDTH, 3), BG_COLOR, dtype=np.uint8)

        # Header
        cv2.putText(
            panel, f"Recognized Plates: {total}",
            (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, TEXT_COLOR, 2,
        )
        cv2.line(panel, (0, HEADER_HEIGHT - 2), (PANEL_WIDTH, HEADER_HEIGHT - 2), (80, 80, 80), 1)

        # Draw visible rows
        for i in range(visible_rows):
            idx = scroll_offset + i
            if idx >= total:
                break
            crop_bgr, text, conf, track_id = log_snapshot[idx]
            y_top = HEADER_HEIGHT + i * ROW_HEIGHT
            y_bottom = y_top + ROW_HEIGHT

            # Resize crop to fixed display size
            try:
                crop_resized = cv2.resize(crop_bgr, (CROP_DISPLAY_W, CROP_DISPLAY_H))
                panel[y_top + 6 : y_top + 6 + CROP_DISPLAY_H, 4 : 4 + CROP_DISPLAY_W] = crop_resized
            except Exception:
                pass

            # Plate text (bold)
            text_x = CROP_DISPLAY_W + 12
            cv2.putText(
                panel, text,
                (text_x, y_top + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.7, TEXT_COLOR, 2,
            )

            # Row separator
            cv2.line(panel, (0, y_bottom - 1), (PANEL_WIDTH, y_bottom - 1), (60, 60, 60), 1)

        # Scroll indicator
        if total > visible_rows:
            bar_h = max(20, int(win_h * visible_rows / total))
            bar_y = int((win_h - bar_h) * scroll_offset / max_scroll) if max_scroll > 0 else 0
            cv2.rectangle(panel, (PANEL_WIDTH - 8, bar_y), (PANEL_WIDTH - 2, bar_y + bar_h), (100, 100, 100), -1)

        cv2.imshow("LPR Panel", panel)
        key = cv2.waitKey(100) & 0xFF
        if key == 27:  # ESC to close panel
            break
        elif key == ord("k") or key == 82:  # k or Up arrow
            scroll_offset = max(0, scroll_offset - 1)
        elif key == ord("j") or key == 84:  # j or Down arrow
            scroll_offset += 1

    try:
        cv2.destroyWindow("LPR Panel")
    except Exception:
        pass
