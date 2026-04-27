#!/usr/bin/env bash
# Install drone-follow into an already-prepared hailo-apps-infra venv.
#
# Prerequisite: the hailo-apps-infra installer must have run successfully,
# creating its venv and /usr/local/hailo/resources/.env. This script
# does NOT call sudo and does NOT depend on its own location relative to
# the parent repo — it locates the parent via HAILO_APPS_PATH.
#
# Resolution order for HAILO_APPS_PATH:
#   1. $HAILO_APPS_PATH from the environment (e.g. set by `source <parent>/setup_env.sh`)
#   2. HAILO_APPS_PATH= line in /usr/local/hailo/resources/.env (case-insensitive)
#   3. error
#
# Flags:
#   --apps-infra <path>  override HAILO_APPS_PATH (highest priority)
#   --skip-ui            skip npm install + UI build
#   --skip-hefs          skip ReID HEF download
#   --skip-python        skip pip install -e .

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="/usr/local/hailo/resources/.env"
RESOURCES_HEF_DIR="/usr/local/hailo/resources/models/hailo8"

OVERRIDE_APPS_INFRA=""
SKIP_UI=false
SKIP_HEFS=false
SKIP_PYTHON=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --apps-infra)  OVERRIDE_APPS_INFRA="$2"; shift 2 ;;
    --skip-ui)     SKIP_UI=true; shift ;;
    --skip-hefs)   SKIP_HEFS=true; shift ;;
    --skip-python) SKIP_PYTHON=true; shift ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
done

# --- Resolve apps-infra root --------------------------------------------------
resolve_apps_infra_root() {
  if [[ -n "${OVERRIDE_APPS_INFRA}" ]]; then
    echo "${OVERRIDE_APPS_INFRA}"
    return
  fi
  if [[ -n "${HAILO_APPS_PATH:-}" ]]; then
    echo "${HAILO_APPS_PATH}"
    return
  fi
  if [[ -f "${ENV_FILE}" ]]; then
    local from_env
    from_env=$(grep -iE '^HAILO_APPS_PATH=' "${ENV_FILE}" | tail -1 | cut -d= -f2- | tr -d '"')
    if [[ -n "${from_env}" ]]; then
      echo "${from_env}"
      return
    fi
  fi
  echo "" # unresolved
}

APPS_INFRA_ROOT="$(resolve_apps_infra_root)"
if [[ -z "${APPS_INFRA_ROOT}" ]]; then
  cat <<EOF >&2
ERROR: Could not resolve hailo-apps-infra root. Provide one of:
  - export HAILO_APPS_PATH=/path/to/hailo-apps-infra (e.g. via parent setup_env.sh)
  - run the parent installer first so ${ENV_FILE} contains HAILO_APPS_PATH=
  - pass --apps-infra /path/to/hailo-apps-infra
EOF
  exit 1
fi

VENV="${APPS_INFRA_ROOT}/venv_hailo_apps"

echo "==> drone-follow installer"
echo "    apps-infra root: ${APPS_INFRA_ROOT}"
echo "    venv:            ${VENV}"

# --- Verify parent installer ran ----------------------------------------------
if [[ ! -d "${APPS_INFRA_ROOT}" ]]; then
  echo "ERROR: HAILO_APPS_PATH=${APPS_INFRA_ROOT} does not exist." >&2
  exit 1
fi
if [[ ! -d "${VENV}" ]]; then
  echo "ERROR: ${VENV} not found. Run ${APPS_INFRA_ROOT}/install.sh first." >&2
  exit 1
fi
if [[ ! -f "${ENV_FILE}" ]]; then
  echo "ERROR: ${ENV_FILE} not found. Run hailo-post-install (the parent installer does this)." >&2
  exit 1
fi

# --- Activate venv ------------------------------------------------------------
# shellcheck disable=SC1091
source "${VENV}/bin/activate"
python -c "import hailo_apps" >/dev/null 2>&1 || {
  echo "ERROR: hailo_apps not importable inside ${VENV}." >&2
  exit 1
}

# --- Install drone-follow editable --------------------------------------------
if ! ${SKIP_PYTHON}; then
  echo "==> pip install -e ${SCRIPT_DIR}"
  pip install --upgrade pip
  pip install -e "${SCRIPT_DIR}"
fi

# --- Download ReID HEFs (idempotent) ------------------------------------------
if ! ${SKIP_HEFS}; then
  REID_BASE_URL="https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.18.0/hailo8"
  declare -A HEFS=(
    [repvgg_a0_person_reid_512.hef]="${REID_BASE_URL}/repvgg_a0_person_reid_512.hef"
    [osnet_x1_0.hef]="${REID_BASE_URL}/osnet_x1_0.hef"
  )
  if [[ ! -d "${RESOURCES_HEF_DIR}" ]]; then
    sudo mkdir -p "${RESOURCES_HEF_DIR}"
    sudo chown -R "${USER}:${USER}" "$(dirname "$(dirname "${RESOURCES_HEF_DIR}")")"
  fi
  for hef in "${!HEFS[@]}"; do
    target="${RESOURCES_HEF_DIR}/${hef}"
    if [[ -f "${target}" ]]; then
      echo "==> ${hef} already present, skip"
      continue
    fi
    echo "==> downloading ${hef}"
    wget -q --show-progress -O "${target}" "${HEFS[$hef]}"
  done
fi

# --- Build the React UI (idempotent) -----------------------------------------
if ! ${SKIP_UI}; then
  if command -v npm >/dev/null 2>&1; then
    pushd "${SCRIPT_DIR}/drone_follow/ui" >/dev/null
    if [[ ! -f build/index.html ]] || [[ src/App.jsx -nt build/index.html ]]; then
      npm install
      npm run build
    else
      echo "==> UI build is up-to-date, skip"
    fi
    popd >/dev/null
  else
    echo "WARN: npm not found — skipping UI build. Install Node 18+ and rerun with no flags."
  fi
fi

echo
echo "==> drone-follow install done."
echo "    To run, from anywhere:"
echo "      source ${APPS_INFRA_ROOT}/setup_env.sh   # activates venv + exports HAILO_APPS_PATH"
echo "      drone-follow --help"
