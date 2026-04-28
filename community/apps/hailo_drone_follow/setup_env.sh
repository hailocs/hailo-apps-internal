#!/usr/bin/env bash
# Thin shim — activates the parent hailo-apps-infra venv.
# Source from anywhere: `source <app>/setup_env.sh`
#
# Resolves the parent path WITHOUT relying on this script's location, so
# the app dir can be moved freely. Resolution order:
#   1. $HAILO_APPS_PATH already exported
#   2. HAILO_APPS_PATH= line in /usr/local/hailo/resources/.env (case-insensitive)
#   3. error
ENV_FILE="/usr/local/hailo/resources/.env"

if [[ -z "${HAILO_APPS_PATH:-}" ]]; then
  if [[ -f "${ENV_FILE}" ]]; then
    HAILO_APPS_PATH=$(grep -iE '^HAILO_APPS_PATH=' "${ENV_FILE}" | tail -1 | cut -d= -f2- | tr -d '"')
    export HAILO_APPS_PATH
  fi
fi

if [[ -z "${HAILO_APPS_PATH:-}" || ! -d "${HAILO_APPS_PATH}" ]]; then
  echo "ERROR: HAILO_APPS_PATH unset/invalid. Run hailo-apps-infra/install.sh first." >&2
  return 1 2>/dev/null || exit 1
fi

_HAF_ORIG_PWD=$(pwd)
cd "${HAILO_APPS_PATH}" || { echo "ERROR: cannot cd to ${HAILO_APPS_PATH}" >&2; return 1 2>/dev/null || exit 1; }
# shellcheck disable=SC1091
source "${HAILO_APPS_PATH}/setup_env.sh"
cd "${_HAF_ORIG_PWD}"
unset _HAF_ORIG_PWD
