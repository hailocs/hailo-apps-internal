# Changelog

## 26.03.0

### Added
- New standalone **Speech Recognition** app in `hailo_apps/python/standalone_apps/speech_recognition/`:

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

