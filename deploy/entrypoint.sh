#!/bin/sh
set -eu
# Railway mounts volumes as root. Fix only our named data directory, then drop privileges.
if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    chown quest:quest /data
    chmod 700 /data
    exec gosu quest "$0" "$@"
fi
exec xvfb-run -a -s '-screen 0 1280x900x24 -nolisten tcp' python -m badminton_reservation.web_server --host 0.0.0.0 --data /data "$@"
