"""Interactive live-prompt panel for the YOLO World app.

Showcases the model's defining capability — open-vocabulary, swap-classes-at-
runtime — with a clear full-screen terminal panel (stdlib `curses`):

  +-------------------------------------------------------------+
  |  YOLO World — Live Open-Vocabulary Detection                |
  |                                                             |
  |  Detecting now:                                             |
  |    ● person   (2)        <- green/bold = seen this moment   |
  |    ○ laptop   (0)        <- dim        = not seen           |
  |                                                             |
  |  How to change what we look for:                            |
  |    type words   ->  REPLACE all   (e.g.  cat, dog, laptop)  |
  |    +word        ->  ADD a class   (e.g.  +bottle)           |
  |    -word        ->  REMOVE a class(e.g.  -dog)              |
  |                                                             |
  |  last: replaced all -> cat, dog                             |
  |  > cat, do_                                                 |
  +-------------------------------------------------------------+

Re-encoding runs on the pure-NumPy CLIP encoder (~ms), so edits apply on the
next frame. The panel owns the terminal, so app logs are redirected to a file
while it runs. If stdout isn't a TTY (e.g. piped), it falls back to a clear
line-based mode. Enabled with --interactive.
"""
import logging
import sys
import threading

from hailo_apps.python.core.common.hailo_logger import get_logger

logger = get_logger(__name__)

LOG_REDIRECT_PATH = "/tmp/yolo_world_live.log"


def parse_command(text, current_labels):
    """Map a typed command to a new label list + a human-readable message.

    Returns (new_labels | None, message). new_labels is None when the command
    is a no-op/invalid (message explains why).
    """
    text = text.strip()
    if not text:
        return None, "type at least one class"
    if text.startswith("+"):
        word = text[1:].strip()
        if not word:
            return None, "nothing to add"
        if word in current_labels:
            return None, f'"{word}" already active'
        return current_labels + [word], f'added "{word}"'
    if text.startswith("-"):
        word = text[1:].strip()
        new = [c for c in current_labels if c != word]
        if len(new) == len(current_labels):
            return None, f'"{word}" was not active'
        if not new:
            return None, "can't remove the last class"
        return new, f'removed "{word}"'
    new = [p.strip() for p in text.split(",") if p.strip()]
    if not new:
        return None, "type at least one class"
    return new, f'replaced all → {", ".join(new)}'


class LivePromptController:
    def __init__(self, embedding_manager, user_data, refresh_s: float = 0.4,
                 suggester=None, frame_buffer=None, engine=None, engine_lock=None):
        self._mgr = embedding_manager
        self._ud = user_data
        self._refresh = refresh_s
        self._stop = threading.Event()
        self._thread = None
        self._saved_handlers = None
        self._log_fh = None
        # "Did you mean" support (all optional).
        self._suggester = suggester
        self._frame_buffer = frame_buffer        # deque of recent 640x640 RGB frames
        self._engine = engine                    # live detector engine (reused for ?probe)
        self._engine_lock = engine_lock          # guards shared-engine access
        self._hint = ""                           # text-similarity hint line

    # ------------------------------------------------------------------ lifecycle

    def start(self):
        tty = sys.stdin.isatty() and sys.stdout.isatty()
        target = self._curses_main if tty else self._line_main
        if tty:
            self._redirect_logging()
        self._thread = threading.Thread(target=target, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._restore_logging()

    # ------------------------------------------------------------------ shared apply

    def _commit(self, text):
        # "?word" -> detection-aware probe (rank near-synonyms by what actually detects).
        if text.startswith("?"):
            return self._probe(text[1:].strip())
        new, msg = parse_command(text, self._mgr.get_labels())
        if new is None:
            return msg
        try:
            self._mgr.update_prompts(new)
        except Exception as e:  # noqa: BLE001 — never kill the control thread
            return f"error: {e}"
        self._update_hint(new)
        return msg

    def _update_hint(self, labels):
        """Cheap text-similarity 'did you mean' for the just-set labels."""
        if self._suggester is None:
            self._hint = ""
            return
        parts = []
        for lbl in labels:
            alts = self._suggester.nearest(lbl, k=2, min_sim=0.85)
            if alts:
                parts.append(f"{lbl} → {', '.join(a for a, _ in alts)}")
        self._hint = ("did you mean:  " + "   |   ".join(parts)) if parts else ""

    def _probe(self, word):
        """Detection-aware ranking of `word` + near-synonyms on buffered frames."""
        if self._suggester is None or self._frame_buffer is None or self._engine is None:
            return "probe unavailable (need --interactive)"
        frames = list(self._frame_buffer)[-12:]   # cap → ~1-2s engine freeze during probe
        if not frames:
            return "probe: no frames buffered yet — wait a moment and retry"
        restore = self._mgr.get_embeddings()
        try:
            ranked = self._suggester.rank_by_detection(
                word, frames, self._engine, self._engine_lock, restore, k=3, min_sim=0.80,
            )
        except Exception as e:  # noqa: BLE001 — surface, don't kill the thread
            logger.error("probe failed: %s", e)
            return f"probe error: {e}"
        if not ranked:
            return f'no known synonyms near "{word}" to probe'
        best = ranked[0]
        you = next((r for r in ranked if r["label"] == word), None)
        tail = "  ".join(f"{r['label']}={r['peak']:.2f}" for r in ranked)
        if you and best["label"] != word and best["peak"] > you["peak"] + 0.05:
            return f'try "{best["label"]}" (peak {best["peak"]:.2f} vs {word} {you["peak"]:.2f})  |  {tail}'
        return f'"{word}" detects fine here  |  {tail}'

    # ------------------------------------------------------------------ curses UI

    def _redirect_logging(self):
        root = logging.getLogger()
        self._saved_handlers = root.handlers[:]
        for h in root.handlers[:]:
            root.removeHandler(h)
        self._log_fh = logging.FileHandler(LOG_REDIRECT_PATH)
        self._log_fh.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        root.addHandler(self._log_fh)

    def _restore_logging(self):
        if self._saved_handlers is None:
            return
        root = logging.getLogger()
        if self._log_fh:
            root.removeHandler(self._log_fh)
            self._log_fh.close()
        for h in self._saved_handlers:
            root.addHandler(h)
        self._saved_handlers = None

    def _curses_main(self):
        import curses
        try:
            curses.wrapper(self._curses_loop)
        except Exception as e:  # noqa: BLE001
            logger.error("live UI error: %s", e)

    def _curses_loop(self, stdscr):
        import curses
        curses.curs_set(1)
        stdscr.timeout(int(self._refresh * 1000))
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)   # present
            curses.init_pair(2, curses.COLOR_CYAN, -1)    # headings
        buf = ""
        last_action = "type below to change what we detect"

        while not self._stop.is_set():
            self._draw(stdscr, curses, buf, last_action)
            ch = stdscr.getch()
            if ch == -1:
                continue
            if ch in (10, 13, curses.KEY_ENTER):
                if buf.strip():
                    last_action = self._commit(buf.strip())
                buf = ""
            elif ch in (127, 8, curses.KEY_BACKSPACE):
                buf = buf[:-1]
            elif 32 <= ch < 127:
                buf += chr(ch)

    def _draw(self, stdscr, curses, buf, last_action):
        green = curses.color_pair(1) if curses.has_colors() else 0
        cyan = curses.color_pair(2) if curses.has_colors() else 0
        try:
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            stdscr.addnstr(0, 0, " YOLO World — Live Open-Vocabulary Detection ".center(w - 1, "="),
                           w - 1, curses.A_BOLD)
            row = 2
            stdscr.addnstr(row, 2, "Detecting now:", w - 3, cyan | curses.A_BOLD)
            row += 1
            counts = self._ud.snapshot_class_counts()
            for lbl in self._mgr.get_labels():
                c = counts.get(lbl, 0)
                if c > 0:
                    stdscr.addnstr(row, 4, f"● {lbl}  ({c})", w - 5, green | curses.A_BOLD)
                else:
                    stdscr.addnstr(row, 4, f"○ {lbl}  ({c})", w - 5, curses.A_DIM)
                row += 1

            row += 1
            stdscr.addnstr(row, 2, "How to change what we look for:", w - 3, cyan | curses.A_BOLD)
            row += 1
            stdscr.addnstr(row, 4, 'type words   ->  REPLACE all   (e.g.  cat, dog, laptop)', w - 5, 0)
            row += 1
            stdscr.addnstr(row, 4, '+word        ->  ADD a class   (e.g.  +bottle)', w - 5, 0)
            row += 1
            stdscr.addnstr(row, 4, '-word        ->  REMOVE a class(e.g.  -dog)', w - 5, 0)
            row += 1
            stdscr.addnstr(row, 4, '?word        ->  suggest a better-detecting phrasing (e.g.  ?potted plant)', w - 5, 0)
            row += 2
            if self._hint:
                stdscr.addnstr(row, 2, f"💡 {self._hint}", w - 3, cyan)
                row += 1
            stdscr.addnstr(row, 2, f"last: {last_action}", w - 3, curses.A_DIM)
            row += 1
            stdscr.addnstr(h - 1, 0, f"(logs → {LOG_REDIRECT_PATH}   |   Ctrl-C to quit)", w - 1, curses.A_DIM)

            prompt = "> "
            stdscr.addnstr(row, 2, prompt + buf, w - 3, curses.A_BOLD)
            stdscr.move(row, 2 + len(prompt) + len(buf))
            stdscr.refresh()
        except curses.error:
            pass  # terminal too small this tick; redraw next tick

    # ------------------------------------------------------------------ line fallback

    def _line_main(self):
        self._print_state(banner=True)
        while not self._stop.is_set():
            line = sys.stdin.readline()
            if not line:
                return
            if line.strip():
                msg = self._commit(line.strip())
                sys.stdout.write(f"  -> {msg}\n")
            self._print_state()

    def _print_state(self, banner=False):
        if banner:
            sys.stdout.write(
                "\n[live] Change what we detect:  type words = REPLACE all  |  "
                "+word = ADD  |  -word = REMOVE  |  ?word = suggest better phrasing\n"
            )
        counts = self._ud.snapshot_class_counts()
        chips = "  ".join(
            f"{'●' if counts.get(l) else '○'} {l}({counts.get(l, 0)})"
            for l in self._mgr.get_labels()
        )
        if self._hint:
            sys.stdout.write(f"[live] 💡 {self._hint}\n")
        sys.stdout.write(f"[live] detecting: {chips}\n> ")
        sys.stdout.flush()
