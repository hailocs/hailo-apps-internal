<!-- PR template for hailo-rpi5-examples community contributions -->
<!-- Copy this file to .github/PULL_REQUEST_TEMPLATE.md in hailo-rpi5-examples -->

## Description

<!-- Brief description of your app or contribution -->

## App Details

- **App name:** <!-- e.g., my_detection_app -->
- **Type:** <!-- pipeline | standalone | gen_ai -->
- **Hardware tested:** <!-- Hailo-8, Hailo-8L, Hailo-10H, or "not tested" -->
- **Primary model:** <!-- e.g., yolov8n -->

---

## Checklist

### Required Files

- [ ] `app.yaml` manifest present and complete
- [ ] `run.sh` wrapper present and executable
- [ ] `README.md` with Overview, Setup, and Usage sections
- [ ] `__init__.py` present
- [ ] `requirements.txt` present

### Coding Conventions

- [ ] Entry point (`if __name__ == "__main__"` or `def main()`)
- [ ] Uses absolute imports (`from hailo_apps.python.core...`)
- [ ] Uses `get_logger(__name__)` (not bare `print`)
- [ ] Uses `resolve_hef_path()` (no hardcoded `.hef` paths)
- [ ] No hardcoded system paths (`/home/...`, `/tmp/...`, `/dev/videoN`)
- [ ] Signal handler for graceful shutdown

### Testing

- [ ] App runs successfully after copying to `community/apps/<type>_apps/<app_name>/` in a hailo-apps clone
- [ ] CLI `--help` works
- [ ] Tested on hardware (specify which above) **or** verified code-only

### Knowledge Findings (if included)

- [ ] Files placed in `community_projects/<app_name>/contributions/`
- [ ] YAML frontmatter with required fields (`title`, `category`, `contributor`, `date`, `tags`)
- [ ] Includes Summary, Context, Finding, Solution, Results, Applicability sections

---

## Additional Notes

<!-- Any extra context, screenshots, or performance metrics -->
