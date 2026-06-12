"""
Tkinter-based enrollment UI for the Room Security Monitor.

Shows face thumbnails of unknown/recognized persons and provides
simple buttons to enroll or add samples — designed to be kid-friendly.
"""

import os
import shutil
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk


# Thumbnail size for face crops in the UI
THUMB_SIZE = (90, 90)
# How often to refresh the face list (ms)
POLL_INTERVAL_MS = 500


class EnrollmentUI:
    """Tkinter enrollment control panel.

    Runs in a daemon thread alongside the GStreamer pipeline.
    Reads face data directly from user_data (same process, thread-safe via locks).
    """

    def __init__(self, user_data):
        self.user_data = user_data
        self.root = None
        # Keep references to PhotoImages so they aren't garbage collected
        self._photo_refs = []

    def start(self):
        """Launch the UI in a daemon thread."""
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self):
        self.root = tk.Tk()
        self.root.title("Face Enrollment")
        self.root.geometry("420x650")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._poll_faces()
        self.root.mainloop()

    def _on_close(self):
        self.user_data.running = False
        self.root.destroy()

    # ── Build the UI ─────────────────────────────────────────────

    def _build_ui(self):
        style = ttk.Style()
        style.configure("Big.TButton", font=("Helvetica", 13, "bold"), padding=8)
        style.configure("Header.TLabel", font=("Helvetica", 14, "bold"))
        style.configure("Status.TLabel", font=("Helvetica", 11))

        # ── Unknown faces section ────────────────────────────────
        unknown_frame = ttk.LabelFrame(self.root, text="  Unknown Faces  ", padding=10)
        unknown_frame.pack(fill=tk.X, padx=10, pady=(10, 5))

        self.unknown_gallery = ttk.Frame(unknown_frame)
        self.unknown_gallery.pack(fill=tk.X)

        self.no_unknown_label = ttk.Label(
            unknown_frame, text="No unknown faces detected yet.",
            style="Status.TLabel", foreground="gray",
        )
        self.no_unknown_label.pack(pady=5)

        # ── Enroll controls ──────────────────────────────────────
        enroll_frame = ttk.LabelFrame(self.root, text="  Enroll New Person  ", padding=10)
        enroll_frame.pack(fill=tk.X, padx=10, pady=5)

        name_row = ttk.Frame(enroll_frame)
        name_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(name_row, text="Name:", font=("Helvetica", 12)).pack(side=tk.LEFT, padx=(0, 8))
        self.name_var = tk.StringVar()
        self.name_entry = ttk.Entry(name_row, textvariable=self.name_var, font=("Helvetica", 14))
        self.name_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.name_entry.bind("<Return>", lambda e: self._enroll_clicked())

        self.enroll_btn = ttk.Button(
            enroll_frame, text="Add Person",
            style="Big.TButton", command=self._enroll_clicked,
        )
        self.enroll_btn.pack(fill=tk.X)

        # ── Known people section ─────────────────────────────────
        known_frame = ttk.LabelFrame(self.root, text="  Known People  ", padding=10)
        known_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Scrollable list
        canvas = tk.Canvas(known_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(known_frame, orient=tk.VERTICAL, command=canvas.yview)
        self.known_list = ttk.Frame(canvas)
        self.known_list.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.known_list, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.no_known_label = ttk.Label(
            self.known_list, text="Database is empty.\nEnroll someone to get started!",
            style="Status.TLabel", foreground="gray",
        )
        self.no_known_label.pack(pady=10)

        # ── Clear DB button ───────────────────────────────────────
        style.configure("Danger.TButton", font=("Helvetica", 11), padding=6)
        clear_btn = ttk.Button(
            self.root, text="Clear All Data",
            style="Danger.TButton", command=self._clear_db_clicked,
        )
        clear_btn.pack(fill=tk.X, padx=10, pady=(5, 0))

        # ── Status bar ───────────────────────────────────────────
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self.root, textvariable=self.status_var,
            style="Status.TLabel", relief=tk.SUNKEN, anchor=tk.W,
        )
        status_bar.pack(fill=tk.X, padx=10, pady=(5, 10))

    # ── Polling ──────────────────────────────────────────────────

    def _poll_faces(self):
        """Periodically refresh the face galleries from user_data."""
        if not self.user_data.running:
            self.root.quit()
            return

        self._refresh_unknowns()
        self._refresh_known()
        self.root.after(POLL_INTERVAL_MS, self._poll_faces)

    def _refresh_unknowns(self):
        """Update the unknown faces gallery."""
        unknowns = self.user_data.get_enrollable_unknowns()

        # Clear old widgets
        for widget in self.unknown_gallery.winfo_children():
            widget.destroy()

        if not unknowns:
            self.no_unknown_label.pack(pady=5)
            return
        self.no_unknown_label.pack_forget()

        for tid, data in sorted(unknowns.items(), key=lambda x: -x[1]["timestamp"]):
            card = self._make_face_card(
                self.unknown_gallery, data["crop"], f"ID: {tid}",
                btn_text="Select",
                btn_command=lambda t=tid: self._select_unknown(t),
            )
            card.pack(side=tk.LEFT, padx=4, pady=4)

    def _refresh_known(self):
        """Update the known people list from the database."""
        if not self.user_data.db_handler:
            return

        try:
            records = self.user_data.db_handler.get_all_records()
        except Exception:
            return

        # Clear old
        for widget in self.known_list.winfo_children():
            widget.destroy()

        if not records:
            self.no_known_label = ttk.Label(
                self.known_list, text="Database is empty.\nEnroll someone to get started!",
                style="Status.TLabel", foreground="gray",
            )
            self.no_known_label.pack(pady=10)
            return

        for rec in records:
            name = rec["label"]
            samples = rec.get("samples_json", [])
            num = len(samples) if isinstance(samples, list) else 0

            row = ttk.Frame(self.known_list)
            row.pack(fill=tk.X, pady=2)

            ttk.Label(
                row, text=f"{name}  ({num} sample{'s' if num != 1 else ''})",
                font=("Helvetica", 12),
            ).pack(side=tk.LEFT, padx=(0, 10))

            ttk.Button(
                row, text="+ Add Photo",
                command=lambda n=name: self._add_sample_clicked(n),
            ).pack(side=tk.RIGHT)

    # ── Face card widget ─────────────────────────────────────────

    def _make_face_card(self, parent, crop, label_text, btn_text=None, btn_command=None):
        """Create a small card with a face thumbnail and optional button."""
        card = ttk.Frame(parent, relief=tk.RIDGE, borderwidth=2)

        # Convert numpy crop to PhotoImage
        try:
            img = Image.fromarray(crop)
            img = img.resize(THUMB_SIZE, Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._photo_refs.append(photo)  # prevent GC
            tk.Label(card, image=photo).pack(padx=2, pady=2)
        except Exception:
            tk.Label(card, text="[no image]", width=12, height=4).pack(padx=2, pady=2)

        ttk.Label(card, text=label_text, font=("Helvetica", 10)).pack()

        if btn_text and btn_command:
            ttk.Button(card, text=btn_text, command=btn_command).pack(pady=(2, 4))

        return card

    # ── Actions ──────────────────────────────────────────────────

    def _select_unknown(self, track_id):
        """Select an unknown face and focus the name entry."""
        self.name_entry.focus_set()
        self._selected_track_id = track_id
        self.status_var.set(f"Selected face ID {track_id}. Type a name and click 'Add Person'.")

    def _enroll_clicked(self):
        """Enroll the selected (or most recent) unknown face."""
        name = self.name_var.get().strip()
        if not name:
            self.status_var.set("Please enter a name first.")
            self.name_entry.focus_set()
            return

        track_id = getattr(self, "_selected_track_id", None)
        success = self.user_data.enroll_face(name, track_id=track_id)

        if success:
            # Force re-classification so the overlay updates immediately
            if self.user_data.pipeline_ref:
                self.user_data.pipeline_ref.force_reclassify(track_id)
            self.status_var.set(f"Enrolled '{name}' successfully!")
            self.name_var.set("")
            self._selected_track_id = None
            # Allow the seen_track_ids to re-log this person with new name
            if track_id is not None:
                self.user_data.seen_track_ids.discard(track_id)
        else:
            self.status_var.set("Enrollment failed. Is a face visible?")

    def _add_sample_clicked(self, name):
        """Add another sample for an existing person."""
        success = self.user_data.add_sample_for_person(name)
        if success:
            self.status_var.set(f"Added photo for '{name}'.")
        else:
            self.status_var.set(f"No face visible to capture for '{name}'.")

    def _clear_db_clicked(self):
        """Clear the database and all training data after confirmation."""
        ok = messagebox.askyesno(
            "Clear All Data",
            "This will delete ALL enrolled faces, training images, and samples.\n\n"
            "Are you sure?",
            parent=self.root,
        )
        if not ok:
            return

        ud = self.user_data
        if not ud.db_handler:
            self.status_var.set("Database not initialized.")
            return

        # Clear the vector database
        ud.db_handler.clear_table()

        # Clear training images
        train_dir = ud.train_images_dir
        if train_dir and os.path.isdir(train_dir):
            for entry in os.listdir(train_dir):
                entry_path = os.path.join(train_dir, entry)
                if os.path.isdir(entry_path):
                    shutil.rmtree(entry_path)
                elif os.path.isfile(entry_path):
                    os.remove(entry_path)

        # Clear enrollable face cache
        with ud.enrollable_lock:
            ud.enrollable_faces.clear()
        ud.seen_track_ids.clear()

        # Reset pipeline tracking state so faces get re-processed
        if ud.pipeline_ref:
            ud.pipeline_ref.track_id_frame_count.clear()
            ud.pipeline_ref.processed_names.clear()

        self.status_var.set("All data cleared.")
