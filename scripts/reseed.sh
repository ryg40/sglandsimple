#!/usr/bin/env bash
# Re-apply the mongo-seed/*.js scripts against the running Mongo container.
#
# Why this exists: Stage 12 moved Mongo onto a host bind mount (./perm/db) so
# data survives `docker compose down` and `--build`. The trade-off is that the
# /docker-entrypoint-initdb.d seed scripts only run on FIRST init (empty data
# dir). After that the seeds never re-run automatically. Use this script to
# (re)apply the seed data — e.g. after adding fields to the seed scripts, or to
# refresh mock data — without wiping the volume.
#
# Usage:
#   scripts/reseed.sh            # run every mongo-seed/*.js in order
#   scripts/reseed.sh --wipe     # drop the enterprise DB first, then reseed

set -euo pipefail

CONTAINER="${MONGO_CONTAINER:-sglandsimple-mongo}"
USER="${MONGO_ROOT_USER:-root}"
PASS="${MONGO_ROOT_PASSWORD:-rootpw}"
DB="${MONGO_DB:-enterprise}"
SEED_DIR="$(cd "$(dirname "$0")/../mongo-seed" && pwd)"

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  echo "Error: container '${CONTAINER}' is not running. Start the stack first." >&2
  exit 1
fi

if [[ "${1:-}" == "--wipe" ]]; then
  echo "Dropping database '${DB}'..."
  docker exec "${CONTAINER}" mongosh --quiet \
    -u "${USER}" -p "${PASS}" --authenticationDatabase admin \
    --eval "db.getSiblingDB('${DB}').dropDatabase()"
fi

shopt -s nullglob
for f in "${SEED_DIR}"/*.js; do
  echo "Applying $(basename "$f")..."
  docker exec -i "${CONTAINER}" mongosh --quiet \
    -u "${USER}" -p "${PASS}" --authenticationDatabase admin < "$f"
done

echo "Reseed complete against '${DB}'."
