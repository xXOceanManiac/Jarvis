#!/usr/bin/env bash
set -euo pipefail

echo "Local video devices:"
ls -l /dev/video* || true
echo
echo "Stable camera IDs:"
ls -l /dev/v4l/by-id/ || true
echo
echo "V4L2 devices:"
v4l2-ctl --list-devices || true
