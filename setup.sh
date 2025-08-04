#!/bin/bash

if [ "$EUID" -ne 0 ]; then
  echo "Root privileges are required. Re-running the script with sudo."
  sudo "$0" "$@"
  exit $?
fi

echo "Running with root privileges."

# traffic_anls-gpu_server.service
SERVICE_PATH_GPU="service_files/traffic_anls-gpu_server.service"
SERVICE_FILE_GPU=$(basename $SERVICE_PATH_GPU)
SYSTEMD_PATH_GPU="/etc/systemd/system/$SERVICE_FILE_GPU"

cp $SERVICE_PATH_GPU $SYSTEMD_PATH_GPU
chmod 644 $SYSTEMD_PATH_GPU

echo "$SERVICE_FILE_GPU copied and permissions set."

systemctl daemon-reload
systemctl enable $SERVICE_FILE_GPU
systemctl start $SERVICE_FILE_GPU
echo "$SERVICE_FILE_GPU setup and started successfully!"