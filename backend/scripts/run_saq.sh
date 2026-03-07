#!/usr/bin/env sh
set -e

WEB_ENABLE="${SAQ_WEB_ENABLE:-false}"

if [ "${WEB_ENABLE}" = "true" ]; then
  PORT="${SAQ_WEB_PORT:-8081}"
  saq backend.workers.saq_settings --web --host 0.0.0.0 --port "${PORT}"
else
  saq backend.workers.saq_settings
fi
