# hailotilecropper_dynamic

A GStreamer plugin that crops video tiles defined dynamically (per-buffer, by upstream
pipeline elements) and/or statically (via element properties). Drop-in compatible
with the standard `hailotileaggregator`.

## Use case

Set tile locations from application logic — e.g., add a tile that covers a tracked
object, change tile count per frame, or feed a single full-frame tile when no
detections are present.

## Building & installing

```bash
source setup_env.sh
hailo-compile-postprocess
```

## Status

Implementation in progress. See
`docs/superpowers/plans/2026-04-30-hailotilecropper-dynamic.md`.
