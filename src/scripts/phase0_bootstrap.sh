#!/usr/bin/env bash
# phase0_bootstrap.sh — Day-1 bootstrap script for both machines.
#
# Run on M1:  ./phase0_bootstrap.sh m1
# Run on workstation:  ./phase0_bootstrap.sh station

set -euo pipefail

MACHINE="${1:?usage: $0 {m1|station}}"

if [[ "$MACHINE" == "m1" ]]; then
  echo "==> Bootstrapping M1 (macOS)"
  brew install python@3.11 git jq htop watch tree ripgrep
  mkdir -p ~/ai-brain/{venv,models,scripts,eval,launchd,hermes_config,logs,snapshots}
  echo "    Home folder: ~/ai-brain/"
  echo "    Next: clone repo, run Phase 1 deployment."

elif [[ "$MACHINE" == "station" ]]; then
  echo "==> Bootstrapping Workstation (Linux)"
  if command -v dnf >/dev/null; then
    sudo dnf install -y python3.11 python3.11-venv git jq htop watch tree ripgrep gcc gcc-c++ cmake make
    sudo dnf install -y vulkan-tools vulkan-loader vulkan-headers vulkan-validation-layers mesa-vulkan-drivers
  elif command -v apt >/dev/null; then
    sudo apt update
    sudo apt install -y python3.11 python3.11-venv git jq htop watch tree ripgrep gcc g++ cmake make
    sudo apt install -y vulkan-tools mesa-vulkan-drivers vulkan-validationlayers
  fi

  mkdir -p ~/ai-brain-station/{venv,llama.cpp,models,scripts,systemd,logs}

  echo "    Home folder: ~/ai-brain-station/"
  echo "    Next: build llama.cpp with Vulkan, run Phase 1 deployment."

else
  echo "Unknown machine: $MACHINE" >&2
  exit 1
fi

echo "==> Bootstrap complete for $MACHINE"
