# Changelog

## 26.03.0

### Added
- New standalone **Speech Recognition** app in `hailo_apps/python/standalone_apps/speech_recognition/`
- New standalone **YOLO26** apps in `hailo_apps/python/standalone_apps/yolo26/`:
	- Object Detection
	- Pose Estimation (including AI Gym example)
	- ONNX Runtime Hailo Pipeline (`hailo_apps/cpp/onnxrt_hailo_pipeline/`) — integrates ONNX Runtime as a postprocess stage for unsupported ONNX operations
- New **Voice2Action (V2A) Demo** GenAI app in `hailo_apps/python/gen_ai_apps/v2a_demo/`:
	- Voice-driven agentic pipeline with STT, LLM tool selection, and TTS
	- Built-in tools: weather, travel, LED control, system check, data storage
- **Agentic AI Development** framework (Beta):
	- AI coding agents for building Hailo applications via natural language
	- Support for GitHub Copilot, Claude Code, and Cursor IDEs
	- Specialized agents: app builder, pipeline builder, standalone builder, VLM builder, voice builder, LLM builder, and agent builder
	- Documentation in `doc/user_guide/agentic_development.md`

### Platform Support
- Added **Windows support** across GenAI and standalone Python applications.

### Changed
- Resource handling and defaults:
	- updates in `hailo_apps/config/resources_config.yaml`
	- downloader behavior updates in `hailo_apps/installation/download_resources.py`
- Core/pipeline infrastructure improvements:
	- updates across `core/common/*` and `core/gstreamer/*`
	- improved input handling and helper pipeline behavior
- GenAI applications updates:
	- changes in `voice_assistant` and `vlm_chat`
	- terminal/audio diagnostics improvements in shared GenAI utilities
- Standalone Python applications refreshed:
	- object detection, instance segmentation, lane detection, pose estimation,
		oriented object detection, paddle OCR, and super-resolution updates
- Documentation refresh:
	- `README.md`, `doc/RELEASE_NOTES.md`, developer/user guides, and multiple app READMEs

