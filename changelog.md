## 26.03.1

### Fixed
- Improved Raspberry Pi compatibility by supporting both legacy and new HailoRT package names
- Fixed H10 default Model Zoo version auto-resolution and added compatibility support for HailoRT 5.3.0
- Refactored USB/Raspberry Pi camera detection with earlier validation when required camera components are unavailable
- Strengthened installation prerequisite checks and version compatibility validation across supported architectures
- Removed deprecated resource scripts `get_inputs.sh` and `get_hef.sh`