#!/bin/bash
# Usage: ./rollback.sh <ID> <SNAPSHOT_NAME>
# ID can be LXC container ID or VM ID

ID="$1"
SNAPSHOT="$2"

if [ -z "$ID" ] || [ -z "$SNAPSHOT" ]; then
  echo "Usage: $0 <ID> <SNAPSHOT_NAME>"
  exit 1
fi

# Check if ID corresponds to LXC or VM
if pct status "$ID" &>/dev/null; then
  TYPE="lxc"
elif qm status "$ID" &>/dev/null; then
  TYPE="vm"
else
  echo "Error: No LXC or VM found with ID $ID"
  exit 2
fi

if [ "$TYPE" == "lxc" ]; then
  echo "Detected LXC container with ID $ID"
  pct stop "$ID"
  pct rollback "$ID" "$SNAPSHOT"
  pct start "$ID"
  echo "Rollback and restart done for LXC $ID to snapshot $SNAPSHOT"
elif [ "$TYPE" == "vm" ]; then
  echo "Detected VM with ID $ID"
  qm stop "$ID"
  qm rollback "$ID" "$SNAPSHOT"
  qm start "$ID"
  echo "Rollback and restart done for VM $ID to snapshot $SNAPSHOT"
fi
