#!/usr/bin/env bash
# Create the secondary 'temporal' database alongside the default 'bene' DB.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE temporal;
    GRANT ALL PRIVILEGES ON DATABASE temporal TO $POSTGRES_USER;
EOSQL
