"""Data storage tool - store and retrieve information with JSON persistence."""

import json
import logging
import os
import tempfile
import threading
from typing import Optional

logger = logging.getLogger("v2a_demo")

# Maximum number of key-value entries across all subjects.
# Adjust this value according to your use-case and available storage.
MAX_ENTRIES = 100
DEFAULT_USER = "User"

TOOL_PROMPT = (
    "Extract parameters from the user's memory storage/retrieval request as a JSON object.\n"
    "You MUST output ALL 4 fields in every response.\n"
    "\n"
    "Parameters:\n"
    '- "operation" (required): "store" for remember/save/store/record, "retrieve" for what is/recall/tell me/do you remember/read back.\n'
    '- "subject" (required): The person\'s name. ALWAYS capitalize only the first letter (e.g. "Gal", not "gal" or "GAL"). If the user says "my"/"me"/"I" without a name, use "User".\n'
    '- "key" (required): The field name. Normalize: phone number/telephone/mobile -> "phone", email address/e-mail -> "email", home address/address -> "address", birthday/birth date/date of birth -> "birthday", ID number/identification/employee id -> "id_number".\n'
    '- "value": The actual data for store operations. MUST be null for retrieve operations.\n'
    "\n"
    "IMPORTANT: For retrieve operations, value MUST always be null.\n"
    "\n"
    "Examples:\n"
    '"Remember John\'s phone number is 123-456-7890" -> {"operation": "store", "subject": "John", "key": "phone", "value": "123-456-7890"}\n'
    '"What is Sarah\'s email?" -> {"operation": "retrieve", "subject": "Sarah", "key": "email", "value": null}\n'
    '"Do you remember Rina\'s employee id?" -> {"operation": "retrieve", "subject": "Rina", "key": "id_number", "value": null}\n'
    '"Read back Yael\'s id number." -> {"operation": "retrieve", "subject": "Yael", "key": "id_number", "value": null}\n'
    '"Save that David\'s birthday is 1990-05-15" -> {"operation": "store", "subject": "David", "key": "birthday", "value": "1990-05-15"}\n'
    '"Save my ID number 123" -> {"operation": "store", "subject": "User", "key": "id_number", "value": "123"}\n'
    '"What is my phone number?" -> {"operation": "retrieve", "subject": "User", "key": "phone", "value": null}\n'
    "\n"
    "Output ONLY the JSON object, nothing else."
)

TOOL_DESCRIPTIONS = [
    "Store personal information about people",
    "Remember details like phone numbers and emails",
    "Save addresses, birthdays, and ID numbers",
    "Record personal information for later recall",
    "Retrieve previously stored personal details",
    "Answer questions about saved personal information",
    "Handle remember and recall requests for people",
    "Write and read personal data by name and field",
    "Manage simple personal memory storage and lookup",
]


# Data stored in a JSON file as a two-level dict:
#
#   { "alice": { "email": "alice@example.com", "phone": "555-1234" },
#     "bob":   { "employee_id": "42" } }
#
# All public methods are thread-safe (guarded by a lock).
# Writes are atomic (write-to-temp-file, then rename) so a crash
# mid-write can never corrupt the file.
class DataStorage:
    """Thread-safe persistent key-value store backed by a JSON file."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        self._data: dict = self._load()
        self._entry_count: int = sum(len(keys) for keys in self._data.values())

    def _load(self) -> dict:
        """Read the JSON file from disk. Returns empty dict on missing or corrupt file."""
        if not os.path.exists(self._path):
            logger.info(f"Storage file not found at {self._path}, starting with empty storage")
            return {}
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.error("Storage file does not contain a JSON object, resetting")
                return {}
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load storage file: {e}")
            return {}

    def _save(self) -> bool:
        """Atomically write data to disk. Returns True on success.

        Writes to a temporary file first, then atomically replaces the
        target file via ``os.replace``.  This guarantees that the
        persistent file is never left in a half-written state — even if
        the process crashes or the Pi loses power mid-write.
        """
        dir_path = os.path.dirname(self._path)
        try:
            os.makedirs(dir_path, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(self._data, f, indent=2)
                os.replace(tmp_path, self._path)
                return True
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as e:
            logger.error(f"Failed to save storage file: {e}")
            return False

    def retrieve(self, subject: str, key: str) -> Optional[str]:
        """Return the value for *subject*/*key*, or ``None`` if missing."""
        with self._lock:
            return self._data.get(subject, {}).get(key)

    def retrieve_all(self, subject: str) -> dict:
        """Return a shallow copy of all key-value pairs for *subject*."""
        with self._lock:
            return dict(self._data.get(subject, {}))

    def store(self, subject: str, key: str, value: str) -> bool:
        """Store *value* under *subject*/*key*. Returns True on success, False if full."""
        with self._lock:
            is_new = key not in self._data.get(subject, {})
            if is_new and (self._entry_count >= MAX_ENTRIES):
                logger.warning(f"Storage full ({MAX_ENTRIES} entries), rejecting store")
                return False
            self._data.setdefault(subject, {})[key] = value
            if is_new:
                self._entry_count += 1
            return self._save()



# Path to the persistent JSON file and global store instance. Created once at import time.
_STORAGE_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "resources", "data_storage.json"))
g_data_storage = DataStorage(_STORAGE_FILE)


def data_storage(operation: str, subject: str, key: str = "", value: Optional[str] = None) -> str:
    """
    Store or retrieve information in persistent data storage.

    Args:
        operation: One of 'store' or 'retrieve'.
        subject:   The subject or context (e.g. a person's name).
        key:       The specific attribute (e.g. 'email').
        value:     The value to store (only for store).

    Returns:
        Human-readable string describing the result, suitable for TTS.
    """
    operation = operation.lower().strip()
    subject = subject.strip().capitalize()
    key = key.strip() if key else ""

    if operation == "store":
        if not key:
            return "I need a key to store that information."
        if value is None:
            return "I need a value to store."
        if not g_data_storage.store(subject, key, value):
            return "My storage is full."
        return "Got it, stored."

    if operation == "retrieve":
        if not key:
            return "I need to know what piece of information you want."
        result = g_data_storage.retrieve(subject, key)
        if result is None:
            return f"I don't have a {key} stored for {subject}."
        return f"The {key} for {subject} is {result}."

    return "I didn't understand that operation. You can say store or retrieve."
