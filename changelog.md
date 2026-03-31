# Changelog

## 26.03.0

### Added
- New standalone **YOLO26** apps in `hailo_apps/python/standalone_apps/yolo26/`:
	- Object Detection
	- Pose Estimation (including AI Gym example)
	- ONNX Runtime Hailo Pipeline (`hailo_apps/cpp/onnxrt_hailo_pipeline/`) — integrates ONNX Runtime as a postprocess stage for unsupported ONNX operations
- New **Voice2Action (V2A) Demo** GenAI app in `hailo_apps/python/gen_ai_apps/v2a_demo/`:
	- Voice-driven agentic pipeline with STT, LLM tool selection, and TTS
	- Built-in tools: weather, travel, LED control, system check, data storage
- **Agentic AI Development** framework (Beta):
	- AI coding agents that build, validate, and run Hailo applications for you
	- Supports VLM, LLM, pipeline, standalone, voice, and agent app types
	- Works with GitHub Copilot, Claude Code, and Cursor
	- Documentation in `doc/user_guide/agentic_development.md`
- **Agent tools example** GenAI app in `hailo_apps/python/gen_ai_apps/agent_tools_example/`
- Returned standalone **Speech Recognition** app in `hailo_apps/python/standalone_apps/speech_recognition/`
- **Easter Eggs** pipeline game app in `hailo_apps/python/pipeline_apps/easter_eggs/`
- **Instance segmentation models with built-in NMS** — new models added to resources config for higher FPS
- **Tiling support** — simplified tiling app with 4-class HEF

### Platform Support
- Added **Windows support** across GenAI, standalone Python, and C++ applications.

### Changed
- Resource handling and defaults:
	- updates in `hailo_apps/config/resources_config.yaml`
	- downloader behavior updates in `hailo_apps/installation/download_resources.py`
- Core/pipeline infrastructure improvements:
	- updates across `core/common/*` and `core/gstreamer/*`
	- improved input handling and helper pipeline behavior
	- unified mirror/flip handling via `GStreamerApp.get_source_pipeline()`
	- framerate caps guard — fix for `frame_rate` being None
- GenAI applications updates:
	- changes in `voice_assistant` and `vlm_chat`
	- terminal/audio diagnostics improvements in shared GenAI utilities
- C++ apps refactored for Windows support and improved resource handling
- Standalone Python applications refreshed:
	- object detection, instance segmentation, lane detection, pose estimation,
		oriented object detection, paddle OCR, and super-resolution updates
- Testing framework updates — improved test runner, agent testing framework, and mirror combination tests
- Documentation refresh:
	- `README.md`, `doc/RELEASE_NOTES.md`, developer/user guides, and multiple app READMEs

