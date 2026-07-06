# Skill: Hailo Platform Artifacts Downloader

> Download official Hailo platform packages — HailoRT, TAPPAS, the PCIe driver, and
> the Model Zoo — for a specific device, version, and CPU architecture, using the
> public manifest-based downloader. Use this to install or switch the HailoRT/TAPPAS
> stack a build runs against (e.g. validating the repo across the supported version
> matrix).

## When to Use This Skill

- You need to **install or upgrade** the HailoRT / TAPPAS / PCIe-driver `.deb` packages
  (and the matching `pyhailort` / `pytappas` wheels) the repo builds against.
- You need to **switch between HailoRT:TAPPAS version combinations** to validate the
  app suite across the supported matrix (see `hailo_apps/config/config.yaml` →
  `valid_combinations`).
- You need a **specific Model Zoo version** for a device/version.

This is distinct from `hl-model-management` (which resolves and downloads per-app HEFs
at runtime). This skill fetches the **platform stack itself**.

## The Downloader

The artifacts are served from a public Cloudflare endpoint with md5-verified downloads
driven by per-version manifests.

```bash
curl -fsSL https://dev-public.hailo.ai/scripts/common/artifacts_downloader.sh -o /tmp/artifacts_downloader.sh
bash /tmp/artifacts_downloader.sh [-d <device>] [-p <project>] [-v <version>] [-a <arch>] [-o <dir>]
```

| Flag | Meaning | Values / default |
|------|---------|------------------|
| `-d` | Device family | `H10`, `H8` (default `H10`). **No `H15` artifacts are published** — H15 comes from the BSP/Yocto stack. |
| `-p` | Project | `hailort`, `tappas`, `model_zoo` (default: all) |
| `-v` | Version | e.g. `5.3.0`, `4.23.0`, or `latest` (default `latest`) |
| `-a` | CPU arch | `x86_64` (laptop/desktop), `aarch64` (Raspberry Pi / ARM) (default `x86_64`) |
| `-o` | Output dir | download destination |

Manifests live at
`https://dev-public.hailo.ai/artifacts/{device}/{project}/{version}/manifest.json`.

### Examples

```bash
# HailoRT 5.3.0 for an x86_64 host with an H10
bash /tmp/artifacts_downloader.sh -d H10 -p hailort -v 5.3.0 -a x86_64 -o /tmp/art

# Full stack (hailort + tappas + model_zoo) for an aarch64 Pi with an H8, HailoRT 4.23.0
bash /tmp/artifacts_downloader.sh -d H8 -v 4.23.0 -a aarch64 -o /tmp/art
```

## Version-switch workflow (validating the support matrix)

The repo declares its supported `HailoRT:TAPPAS` combinations in
`hailo_apps/config/config.yaml` under `valid_combinations` (per arch: `hailo8`,
`hailo8l`, `hailo10h`). To validate a combination end-to-end:

1. **Download** the target combo's packages with this skill (`hailort` + `tappas` for
   the right `-d`/`-a`).
2. **Uninstall** the current stack: `sudo bash scripts/uninstall_hailo_packages.sh`.
3. **Install** the new `.deb`s: `sudo dpkg -i <dir>/*.deb`.
4. **Re-install the app env** pointing at the matching wheels:
   `sudo ./install.sh --force-cleanup -ph <dir>/*pyhailort*.whl -pt <dir>/*pytappas*.whl`.
5. **Build + test**: `cd hailo_apps/postprocess && bash compile_postprocess.sh`, then
   `source setup_env.sh && python -m pytest tests/ -q`.
6. **Verify the install** is recognized: `bash scripts/check_installed_packages.sh`.

> Switching versions is **destructive** to the current install. Snapshot the working
> versions first (`dpkg -l | grep -iE 'hailort|tappas'`) and keep the known-good
> artifacts so the host can be restored afterward.

## Notes

- A specific older version may not be present on the public manifest (the download
  404s). Treat that as a "needs internal/dev-zone source" condition rather than a hard
  failure when sweeping the matrix.
- `-a aarch64` is required for Raspberry Pi targets; `-a x86_64` for laptops/desktops.
- Always run inside the project venv for the Python steps (`source setup_env.sh`).
