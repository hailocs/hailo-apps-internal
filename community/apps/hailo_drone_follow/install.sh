#!/bin/bash
set -e

# Install script for drone-follow
# Installs: drone-follow Python package (editable) with hailo-apps pulled from
# GitHub, plus the web UI.
#
# Prerequisites (one-time system setup, NOT done by this script):
#   - HailoRT and TAPPAS .deb + .whl packages installed (Hailo Developer Zone)
#   - /usr/local/hailo/resources/ populated with HEF models and C++ postprocess
#     modules (install via hailo-apps system installer or TAPPAS deb)
#
# Usage: ./install.sh [OPTIONS]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Defaults
SKIP_UI=false
SKIP_PYTHON=false

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --skip-ui              Skip UI npm install and build"
    echo "  --skip-python          Skip Python venv + dependency installation"
    echo "  --help, -h             Show this help message"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-ui)          SKIP_UI=true; shift ;;
        --skip-python)      SKIP_PYTHON=true; shift ;;
        --help|-h)          usage; exit 0 ;;
        *)                  echo -e "${RED}Unknown argument: $1${NC}"; usage; exit 1 ;;
    esac
done

echo "========================================="
echo "  drone-follow installer"
echo "========================================="
echo ""

# ─── Step 1: Build repo-owned venv and install Python deps ───────────
REPO_VENV_DIR="$SCRIPT_DIR/venv"

# ─── Download ReID HEF models ──────────────────────────────────────
REID_MODELS_DIR="/usr/local/hailo/resources/models/hailo8"
REID_HEFS=(
    "repvgg_a0_person_reid_512.hef"
    "osnet_x1_0.hef"
)
REID_BASE_URL="https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.18.0/hailo8"

MISSING_HEFS=()
for hef in "${REID_HEFS[@]}"; do
    if [ ! -f "$REID_MODELS_DIR/$hef" ]; then
        MISSING_HEFS+=("$hef")
    fi
done

if [ ${#MISSING_HEFS[@]} -gt 0 ]; then
    echo -e "${GREEN}Downloading ReID HEF models...${NC}"
    sudo mkdir -p "$REID_MODELS_DIR"
    for hef in "${MISSING_HEFS[@]}"; do
        echo -e "  Downloading ${CYAN}$hef${NC}..."
        if sudo wget -q --show-progress -O "$REID_MODELS_DIR/$hef" "$REID_BASE_URL/$hef"; then
            echo -e "  ${GREEN}Saved to $REID_MODELS_DIR/$hef${NC}"
        else
            echo -e "${YELLOW}  Failed to download $hef. Download manually from:${NC}"
            echo -e "  https://github.com/hailo-ai/hailo_model_zoo/blob/master/docs/public_models/HAILO8/HAILO8_person_re_id.rst"
            echo -e "  Place in: $REID_MODELS_DIR/"
        fi
    done
else
    echo -e "${GREEN}ReID HEF models already present in $REID_MODELS_DIR${NC}"
fi

# hailo-all / TAPPAS deb ships /usr/local/hailo/resources/ as root:root, and
# the sudo wget above (when it runs) writes root-owned HEFs into it. But
# hailo-apps downloads additional HEFs and writes its .env into that tree at
# runtime as the invoking user, so leaving it root-owned causes EACCES on
# first run of hailo-tiling et al. Hand the tree to the target user.
# SUDO_USER is set when this script is invoked under sudo (e.g. by
# scripts/install_air.sh); fall back to the current user otherwise.
TARGET_USER="${SUDO_USER:-$USER}"
if [ -d /usr/local/hailo/resources ]; then
    sudo chown -R "$TARGET_USER":"$TARGET_USER" /usr/local/hailo/resources
fi

if ! $SKIP_PYTHON; then
    echo -e "${GREEN}[1/2] Setting up repo Python venv at ${CYAN}$REPO_VENV_DIR${NC}..."

    if [ ! -d "$REPO_VENV_DIR" ]; then
        python3 -m venv --system-site-packages "$REPO_VENV_DIR"
        echo -e "  Created venv (--system-site-packages so apt-installed Hailo bindings are visible)."
    else
        echo -e "  Reusing existing venv."
    fi

    # shellcheck disable=SC1091
    source "$REPO_VENV_DIR/bin/activate"

    pip install --upgrade pip setuptools wheel

    echo -e "  Installing drone-follow + hailo-apps from GitHub..."
    pip install -e ".[hailo]"

    echo -e "${GREEN}  drone-follow + hailo-apps installed into $REPO_VENV_DIR.${NC}"

    # `pip install hailo-apps` does NOT compile the C++ postprocess libraries
    # or write /usr/local/hailo/resources/.env — that's done by the upstream
    # `hailo-post-install` CLI. Without it, the pipeline crashes at runtime
    # with "cannot open shared object file: libyolo_hailortpp_postprocess.so".
    # Skip the (slow) re-run if the postprocess libs are already in place.
    if [ ! -f /usr/local/hailo/resources/so/libyolo_hailortpp_postprocess.so ]; then
        echo -e "${GREEN}  Running hailo-post-install (compiles postprocess libs, writes .env, downloads default models)...${NC}"
        hailo-post-install
    else
        echo -e "${GREEN}  hailo-apps post-install artifacts already present, skipping.${NC}"
    fi
else
    echo -e "${YELLOW}[1/2] Skipping Python dependencies (--skip-python)${NC}"
fi

# ─── Step 2: Install and build UI ────────────────────────────────────
if ! $SKIP_UI; then
    echo -e "${GREEN}[2/2] Installing and building UI...${NC}"

    UI_DIR="$SCRIPT_DIR/drone_follow/ui"
    if [ ! -f "$UI_DIR/package.json" ]; then
        echo -e "${YELLOW}  No package.json found, skipping UI.${NC}"
    else
        if ! command -v npm &> /dev/null; then
            echo -e "${RED}  Error: npm is not installed. Install Node.js first:${NC}"
            echo -e "    sudo apt install nodejs npm"
            exit 1
        fi

        echo -e "  Running npm install..."
        (cd "$UI_DIR" && npm install)

        echo -e "  Building UI..."
        (cd "$UI_DIR" && npm run build)

        echo -e "${GREEN}  UI built successfully.${NC}"
    fi
else
    echo -e "${YELLOW}[2/2] Skipping UI installation (--skip-ui)${NC}"
fi

# ─── Regenerate setup_env.sh ─────────────────────────────────────────
cat > "$SCRIPT_DIR/setup_env.sh" << 'SETUP_EOF'
#!/bin/bash
# Auto-generated by install.sh. Activates the repo-owned venv, sets PYTHONPATH,
# runs the RPi kernel-compatibility check, and loads /usr/local/hailo/resources/.env.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

# RPi kernel-version check (mirrors hailo-apps/setup_env.sh)
if uname -a | grep -q "Linux raspberrypi"; then
    INVALID_KERNELS=("6.12.21" "6.12.22" "6.12.23" "6.12.24" "6.12.25")
    CURRENT_VERSION=$(uname -r | cut -d '+' -f 1)
    for k in "${INVALID_KERNELS[@]}"; do
        if [ "$k" = "$CURRENT_VERSION" ]; then
            echo "Error: Kernel $CURRENT_VERSION is incompatible." >&2
            echo "See https://community.hailo.ai/t/raspberry-pi-kernel-compatibility-issue-temporary-fix/15322" >&2
            return 1
        fi
    done
fi

export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

if [ -d "$VENV_DIR" ]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    echo "Activated venv at $VENV_DIR"
else
    echo "Error: venv not found at $VENV_DIR. Run ./install.sh first." >&2
    return 1
fi

ENV_FILE="/usr/local/hailo/resources/.env"
if [ -f "$ENV_FILE" ]; then
    while IFS='=' read -r key value; do
        [[ -z "$key" || "$key" =~ ^# ]] && continue
        export "$key=$value"
        upper_key=$(echo "$key" | tr '[:lower:]' '[:upper:]')
        export "$upper_key=$value"
    done < "$ENV_FILE"
fi
SETUP_EOF
chmod +x "$SCRIPT_DIR/setup_env.sh"

echo ""
echo -e "${GREEN}Installation complete!${NC}"
echo ""
echo "Next steps:"
echo "  source setup_env.sh"
echo "  drone-follow --input rpi --ui"
