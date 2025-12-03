# Hailo VLM Interactive Application

An interactive computer vision application using Hailo's Vision Language Model (VLM) for real-time image analysis and question answering.

## Features

- **Real-time video processing** with Hailo AI acceleration
- **Interactive Q&A mode** - press Enter to ask questions about the current frame
- **Dual window display** - continuous video feed and captured frame analysis
- **Custom prompt support** - ask any question about the captured image
- **Non-blocking interface** - video continues while processing questions

## Requirements

- Hailo AI processor and SDK
- Python >=3.10
- OpenCV
- NumPy
- Hailo Platform libraries

## Files

- `vlm_chat.py` - Main application with interactive video processing
- `backend.py` - Hailo VLM backend with multiprocessing support

## Usage

1. Run the application:
   ```bash
   python vlm_chat.py --input usb
   ```
   Or for Raspberry Pi camera:
   ```bash
   python vlm_chat.py --input rpi
   ```

   **Note:** This application requires a live camera input.

2. The application will show two windows:
   - **Video**: Continuous live camera feed
   - **Frame**: Current frame being processed

3. **Interactive mode**:
   - Press `Enter` to capture current frame and enter Q&A mode
   - Type your question about the captured image
   - Press `Enter` to get VLM response
   - Press `Enter` again to continue normal processing

## Configuration

You can modify the following constants in `vlm_chat.py` to customize the application behavior:

- `MAX_TOKENS` (Default: 200) - Maximum number of tokens to generate in the response.
- `TEMPERATURE` (Default: 0.1) - Sampling temperature for the model (lower means more deterministic).
- `SEED` (Default: 42) - Random seed for reproducibility.
- `SYSTEM_PROMPT` - The system prompt used to guide the VLM's behavior.
- `INFERENCE_TIMEOUT` (Default: 30) - Timeout in seconds for VLM inference.
- `SAVE_FRAMES` (Default: False) - Set to `True` to save captured frames to disk.

## How it works

The application uses a multiprocessing architecture to handle:
- Real-time video capture and display
- Hailo VLM inference in a separate process
- Non-blocking user input handling
- State management for interactive mode

The VLM can answer questions about objects, scenes, activities, and any visual content in the captured frames.
