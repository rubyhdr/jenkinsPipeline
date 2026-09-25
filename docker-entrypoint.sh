#!/bin/sh
# Prepare the database (waits for Postgres), load demo data once, then start the app.
set -e

flask init-db
if [ "${SEED_DEMO_DATA:-true}" = "true" ]; then
  flask seed --if-empty
fi

exec "$@"
