#!/bin/bash
# Force Gazebo Garden (gz-sim7) when Gazebo Harmonic (gz-sim8) is the system
# default.  PX4 v1.14's gz_bridge links against gz-transport12 which is
# incompatible with Harmonic's transport13.
#
# Sourced by start_sim.sh.  Exports GZ_SIM_BIN and defines gz_garden_cleanup().
#
# On systems where Garden is the default (or where no Gazebo is installed and
# setup_sim.sh will install Garden), this is a no-op.

gz_garden_cleanup() { :; }  # default no-op; overridden below if needed

# If gz-sim7 (Garden) CLI exists, prefer it over Harmonic.
if command -v gz-sim-server7 &>/dev/null || [ -x "/usr/bin/gz" ]; then
    # Check if Harmonic is the default by looking for gz-sim8
    if dpkg -s gz-sim8-cli &>/dev/null; then
        echo -e "${YELLOW:-}  Harmonic detected — forcing Gazebo Garden (gz-sim7)${NC:-}"
        # Garden installs its plugin path under gz-sim-7; make sure it's found
        export GZ_SIM_SYSTEM_PLUGIN_PATH="/usr/lib/x86_64-linux-gnu/gz-sim-7/plugins:${GZ_SIM_SYSTEM_PLUGIN_PATH:-}"
    fi
fi
