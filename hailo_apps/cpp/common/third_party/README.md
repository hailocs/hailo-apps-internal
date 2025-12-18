# C++ third-party headers

This folder is intended for **vendored (header-only) C++ dependencies** that are used by the C++ examples.

## xtl / xtensor
Some examples (e.g. `cpp/pose_estimation`) require **xtl** and **xtensor**.

Expected layout:

- `hailo_apps/cpp/common/third_party/xtl/include/xtl/...`
- `hailo_apps/cpp/common/third_party/xtensor/include/xtensor/...`

### Option A: add as git submodules (recommended)
From the repository root:

```bash
git submodule add https://github.com/xtensor-stack/xtl.git hailo_apps/cpp/common/third_party/xtl
git submodule add https://github.com/xtensor-stack/xtensor.git hailo_apps/cpp/common/third_party/xtensor
```

Then checkout known-good tags for your toolchain, for example:

- xtl: `0.7.x`
- xtensor: `0.25.x` (this repo uses includes like `<xtensor/views/xview.hpp>`)

### Option B: copy a release snapshot
Download a release archive for `xtl` and `xtensor` and extract them into the folders above.

## Notes
- This repo does **not** commit upstream sources by default to avoid repository bloat.
- The CMake files are wired to prefer these vendored headers and will fail fast if they are missing.
