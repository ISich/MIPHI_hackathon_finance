#!/usr/bin/env bash
# List backend servers started by QA (DD_HOME under a qa-http-*/probe dir); prints nothing if none.
for p in $(ps -eo pid=,comm= | awk '$2 ~ /^python/ {print $1}'); do
  if tr '\0' ' ' 2>/dev/null < /proc/$p/cmdline | grep -q "uvicorn dd_backend.app"; then
    echo "$p $(tr '\0' '\n' 2>/dev/null < /proc/$p/environ | grep ^DD_HOME=)"
  fi
done
