#!/bin/bash

if [ "$EUID" -ne 0 ]; then
  echo "Root privileges are required. Re-running the script with sudo."
  sudo "$0" "$@"
  exit $?
fi

echo "Running with root privileges."

systemctl stop traffic_anls-gpu_server.service