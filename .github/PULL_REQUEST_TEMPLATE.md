> **Community contributors:** This PR template is for internal and agent-built contributions to this repository.
> If you're contributing a community app or knowledge finding, please open your PR to
> [hailo-rpi5-examples](https://github.com/hailo-ai/hailo-rpi5-examples) instead.
> See [CONTRIBUTING.md](./CONTRIBUTING.md) for the full guide.

## Description

<!-- Brief description of your changes -->

## Contribution Type

- [ ] **New app** (`community/apps/`) — agent-built, to be pushed to hailo-rpi5-examples
- [ ] **Knowledge finding** (`community/contributions/`)
- [ ] **Bug fix**
- [ ] **Documentation improvement**
- [ ] **Other**: _describe_

---

## For New Apps

### Checklist

- [ ] `app.yaml` manifest present and complete
- [ ] `run.sh` wrapper present and executable
- [ ] `README.md` with description, usage, and example output
- [ ] `__init__.py` present
- [ ] Entry point (`if __name__ == "__main__"` or `def main()`)
- [ ] Uses absolute imports (`from hailo_apps.python.core...`)
- [ ] Uses `get_logger(__name__)` (not bare `print`)
- [ ] Uses `resolve_hef_path()` (no hardcoded `.hef` paths)
- [ ] No hardcoded system paths (`/home/...`, `/tmp/...`, `/dev/videoN`)
- [ ] Signal handler for graceful shutdown

### Validation

- [ ] `python .github/scripts/validate_app.py <app_dir>` — all static checks pass
- [ ] `python .github/scripts/validate_app.py <app_dir> --smoke-test` — smoke tests pass (or gracefully skip on missing hardware)

### Hardware Tested

- [ ] Hailo-8
- [ ] Hailo-8L
- [ ] Hailo-10H
- [ ] Not tested on hardware (simulation / code-only)

---

## For Knowledge Findings

### Checklist

- [ ] YAML frontmatter with required fields (`title`, `category`, `contributor`, `date`, `tags`)
- [ ] Placed in correct category directory under `community/contributions/`
- [ ] File named `YYYY-MM-DD_<app>_<slug>.md`
- [ ] Includes Summary, Context, Finding, Solution, Results sections

### Reproducibility

- [ ] Verified — tested and confirmed
- [ ] Observed — seen in practice but not formally verified
- [ ] Theoretical — based on documentation or reasoning

---

## Additional Notes

<!-- Any extra context, screenshots, or performance metrics -->
