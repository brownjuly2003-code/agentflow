#!/usr/bin/env bash
# Apply the DV2 raw vault to a PostgreSQL database, in dependency order.
# Usage: PGHOST=... PGUSER=... PGDATABASE=... ./apply.sh
# (or set PSQL to a full psql invocation). Requires a running PostgreSQL.
set -euo pipefail

PSQL="${PSQL:-psql}"
DIR="$(cd "$(dirname "$0")" && pwd)"

$PSQL -v ON_ERROR_STOP=1 -f "$DIR/00_schema.sql"
$PSQL -v ON_ERROR_STOP=1 -f "$DIR/01_hubs.sql"
$PSQL -v ON_ERROR_STOP=1 -f "$DIR/02_links.sql"
for f in "$DIR"/satellites/*.sql; do
    $PSQL -v ON_ERROR_STOP=1 -f "$f"
done
$PSQL -v ON_ERROR_STOP=1 -f "$DIR/03_business_vault.sql"

echo "DV2 PostgreSQL raw vault applied."
