from hailo_platform import VDevice
from hailo_platform.genai import LLM, Speech2Text, Speech2TextTask
from hailo_apps.python.core.common.core import get_resource_path
import subprocess
import numpy as np
import wave
from piper import PiperVoice
from piper.voice import SynthesisConfig
import threading
import queue
import time
import tempfile
from io import StringIO
from contextlib import redirect_stderr
from hailo_apps.python.core.common.defines import (
    RESOURCES_MODELS_DIR_NAME,
    LLM_MODEL_NAME_H10,
    WHISPER_MODEL_NAME_H10,
    TTS_ONNX_PATH,
    TTS_VOLUME,
    TTS_LENGTH_SCALE,
    TTS_NOISE_SCALE,
    TTS_W_SCALE,
    TEMP_WAV_DIR,
    LLM_PROMPT_PREFIX,
    SHARED_VDEVICE_GROUP_ID
)

class AIPipeline:
    """
    Manages the AI pipeline from speech-to-text, to a large language model,
    and finally to text-to-speech.

    This class handles the complexities of streaming responses, managing audio
    playback, and ensuring that new user interactions can gracefully interrupt
    and replace ongoing ones.
    """

    def __init__(self, no_tts=False):
        """
        Initializes all components of the AI pipeline.

        Args:
            no_tts (bool): If True, disables text-to-speech output for lower resource usage.
        """
        self._setup_hailo_ai()
        self.no_tts = no_tts
        if not no_tts:
            self._setup_tts()
            self._setup_threading()
            # Start the background worker for speech synthesis and playback
            self.speech_thread = threading.Thread(
                target=self._speech_worker, daemon=True)
            self.speech_thread.start()

    def interrupt(self):
        """
        Interrupts any ongoing speech.

        This method stops the current audio playback, increments the generation ID
        to invalidate stale speech chunks, and clears the audio queue. It is
        called at the beginning of a new processing request.
        """
        if not self.no_tts:
            self._interrupted.set()
            with self._gen_id_lock:
                self.generation_id += 1

            with self._speech_lock:
                if self.current_speech_process:
                    try:
                        # Terminate the 'aplay' process to stop audio instantly
                        self.current_speech_process.kill()
                    except OSError:
                        # The process might have already finished, which is fine.
                        pass
                    self.current_speech_process = None

            # Drain the queue of any stale audio chunks from the previous generation
            while not self.speech_queue.empty():
                try:
                    self.speech_queue.get_nowait()
                except queue.Empty:
                    continue

    def _setup_hailo_ai(self):
        """Initializes Hailo AI platform components (VDevice, S2T, LLM)."""
        params = VDevice.create_params()
        params.group_id = SHARED_VDEVICE_GROUP_ID
        self._vdevice = VDevice(params)
        self.speech2text = Speech2Text(self._vdevice, str(get_resource_path(pipeline_name=None, resource_type=RESOURCES_MODELS_DIR_NAME, model=WHISPER_MODEL_NAME_H10)))
        self.llm = LLM(self._vdevice, str(get_resource_path(pipeline_name=None, resource_type=RESOURCES_MODELS_DIR_NAME, model=LLM_MODEL_NAME_H10)))
        self._recovery_seq = self.llm.get_generation_recovery_sequence()

    def _setup_tts(self):
        """Initializes the Text-to-Speech engine (Piper)."""
        # Suppress Piper warning messages
        with redirect_stderr(StringIO()):
            self.piper_voice = PiperVoice.load(TTS_ONNX_PATH)  # In case different voice selected, please modify here
            self.syn_config = SynthesisConfig(
                volume=TTS_VOLUME,
                length_scale=TTS_LENGTH_SCALE,
                noise_scale=TTS_NOISE_SCALE,
                noise_w_scale=TTS_W_SCALE,
                normalize_audio=True
            )

    def _setup_threading(self):
        """Sets up threading components for asynchronous speech playback."""
        self.speech_queue = queue.Queue()
        self.current_speech_process = None
        self._speech_lock = threading.Lock()
        self.generation_id = 0
        self._gen_id_lock = threading.Lock()
        self._interrupted = threading.Event()

    def _speech_worker(self):
        """
        A background thread that processes the speech queue.

        This worker pulls text chunks, synthesizes them into audio, and plays
        them back. It continuously checks the generation ID and interruption
        flag to ensure it doesn't play stale audio from a previous, interrupted
        interaction.
        """
        while True:
            try:
                gen_id, text = self.speech_queue.get(timeout=0.1)

                # If an interruption is signaled, discard this chunk and move on.
                if self._interrupted.is_set():
                    self.speech_queue.task_done()
                    continue

                # If this chunk is from a previous (stale) generation, discard it.
                with self._gen_id_lock:
                    if gen_id != self.generation_id:
                        self.speech_queue.task_done()
                        continue

                self._synthesize_and_play(text)

            except queue.Empty:
                # The queue is empty, just wait a moment before checking again.
                time.sleep(0.1)

    def _synthesize_and_play(self, text: str):
        """
        Synthesizes a chunk of text to audio and plays it.

        Args:
            text (str): The text to be spoken.
        """
        playback_process = None
        try:
            # Create a temporary WAV file for the audio output.
            # This ensures that files are cleaned up properly.
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True, dir=TEMP_WAV_DIR) as temp_wav_file:
                temp_wav_path = temp_wav_file.name
                with wave.open(temp_wav_path, "wb") as wav_file:
                    # Suppress Piper warning messages during synthesis
                    with redirect_stderr(StringIO()):
                        self.piper_voice.synthesize_wav(
                            text, wav_file, self.syn_config)

                with self._speech_lock:
                    # Start audio playback in a separate process.
                    self.current_speech_process = subprocess.Popen(
                        ['aplay', temp_wav_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    playback_process = self.current_speech_process

                # Wait for the current audio chunk to finish playing.
                playback_process.wait()

        finally:
            # Ensure the process handle is cleaned up.
            with self._speech_lock:
                if (self.current_speech_process and playback_process and
                        self.current_speech_process.pid == playback_process.pid):
                    self.current_speech_process = None
            self.speech_queue.task_done()

    def process(self, audio: 'np.ndarray') -> str:
        """
        Processes recorded audio to generate and speak a response.

        This is the main entry point for the pipeline, which takes raw audio
        and orchestrates the S2T, LLM, and TTS steps.

        Args:
            audio (np.ndarray): The raw audio data from the microphone.

        Returns:
            str: The generated text response from the language model.
        """
        # 1. Prepare for the new generation by clearing the interruption flag.
        if not self.no_tts:
            self._interrupted.clear()
            with self._gen_id_lock:
                current_gen_id = self.generation_id
        else:
            current_gen_id = None

        # 2. Transcribe the user's speech using the S2T model.
        segments = self.speech2text.generate_all_segments(
            audio_data=audio,
            task=Speech2TextTask.TRANSCRIBE,
            language="en",
            timeout_ms=15000)
        print("Captured text:\n")
        print(segments)
        print("\nLLM response:\n")

        # 3. Get a response from the language model.
        user_text = ''.join([seg.text for seg in segments])
        prompt = LLM_PROMPT_PREFIX + user_text

        output = ''
        sentence_buffer = ''
        first_chunk_sent = False

        with self.llm.generate(prompt=[{'role': 'user', 'content': prompt}]) as gen:
            for token in gen:
                if token == self._recovery_seq:
                    continue

                print(token, end='', flush=True)
                output += token

                if not self.no_tts:
                    sentence_buffer += token
                    # 4. Chunk the response and send it to the speech queue.
                    # This allows for a more responsive, streaming-like experience.
                    sentence_buffer = self._chunk_and_queue_speech(
                        sentence_buffer, current_gen_id, not first_chunk_sent
                    )

                    if not first_chunk_sent and not self.speech_queue.empty():
                        first_chunk_sent = True

        # 5. Send any remaining text from the buffer to the speech queue.
        if not self.no_tts and sentence_buffer.strip():
            self.speech_queue.put((current_gen_id, sentence_buffer.strip()))

        print()
        return output

    def _chunk_and_queue_speech(self, buffer: str, gen_id: int, is_first_chunk: bool) -> str:
        """
        Chunks a buffer of text into sentences and adds them to the speech queue.

        Args:
            buffer (str): The text buffer to be chunked.
            gen_id (int): The current generation ID to tag the chunks with.
            is_first_chunk (bool): If true, also uses commas as delimiters for faster response.

        Returns:
            str: The remaining text in the buffer after chunking.
        """
        # Use a comma as a delimiter only for the first chunk for faster response.
        delimiters = ['.', '?', '!']
        if is_first_chunk:
            delimiters.append(',')

        while True:
            # Find the first occurrence of any delimiter.
            positions = {buffer.find(
                d): d for d in delimiters if buffer.find(d) != -1}
            if not positions:
                break  # No delimiters found, wait for more tokens.

            first_pos = min(positions.keys())
            chunk = buffer[:first_pos + 1]

            if chunk.strip():
                self.speech_queue.put(
                    (gen_id, chunk.strip()))

            buffer = buffer[first_pos + 1:]

        return buffer
