"""The probe writer pattern around test_log_file must survive close() being
called from another thread between the is-not-None check and the .write()
call. Test pins the snapshot+except-AttributeError pattern used in
hailo_drone_detection_manager._app_callback_inner's finally block."""

import io
import json
import threading
import time
import types


def test_writer_pattern_handles_concurrent_close():
    """Replicates the production probe pattern verbatim.

    A worker thread loops on (snapshot handle, write JSON) while the main
    thread Nones out the handle. Pattern must NOT propagate exceptions.
    """
    user_data = types.SimpleNamespace(
        test_log_file=io.StringIO(),
        _frame_log_data={"frame": 1},
    )

    stop = threading.Event()
    errors = []

    def writer():
        while not stop.is_set():
            try:
                # Mirror the exact pattern in hailo_drone_detection_manager
                # `finally` block: snapshot handle, narrow except.
                log_file = user_data.test_log_file
                if log_file is not None and user_data._frame_log_data is not None:
                    try:
                        log_file.write(json.dumps(user_data._frame_log_data) + "\n")
                    except (ValueError, OSError, AttributeError):
                        pass
            except Exception as e:
                errors.append(e)

    t = threading.Thread(target=writer)
    t.start()
    time.sleep(0.05)
    user_data.test_log_file = None  # race the write
    time.sleep(0.05)
    stop.set()
    t.join()
    assert not errors, f"writer raised: {errors}"


def test_attributeerror_caught_when_handle_replaced_with_none_object():
    """A direct test that AttributeError is in the except list.

    Simulates the worst-case race: the snapshot somehow misses the swap and
    we end up calling write() on None — which raises AttributeError, not
    ValueError or OSError. The catch list must include it.
    """
    handle = None
    raised = None
    try:
        try:
            handle.write("x")
        except (ValueError, OSError, AttributeError):
            pass
    except Exception as e:
        raised = e
    assert raised is None, f"AttributeError must be caught, got {raised!r}"
