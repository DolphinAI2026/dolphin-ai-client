#!/usr/bin/env bash
set -euo pipefail

backend_dir="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$backend_dir"

mysql_name="tenant-public-id-mysql-$$"
pg_name="tenant-public-id-postgresql-$$"
mysql_image="${TENANT_PUBLIC_ID_MYSQL_IMAGE:-mysql:8.4}"
postgresql_image="${TENANT_PUBLIC_ID_POSTGRES_IMAGE:-postgres:16}"

database_host() {
  if [[ "${DOCKER_HOST:-}" == tcp://* ]]; then
    local docker_endpoint="${DOCKER_HOST#tcp://}"
    printf '%s\n' "${docker_endpoint%%[:/]*}"
    return
  fi
  printf '%s\n' "127.0.0.1"
}

port_bind_host() {
  if [[ "${DOCKER_HOST:-}" == tcp://* ]]; then
    printf '%s\n' "0.0.0.0"
    return
  fi
  printf '%s\n' "127.0.0.1"
}

cleanup() {
  docker rm -f "$mysql_name" "$pg_name" >/dev/null 2>&1 || true
}

wait_for_mysql() {
  for _ in $(seq 1 60); do
    if docker exec "$mysql_name" mysqladmin ping -h 127.0.0.1 -uroot -ptest --silent >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  docker logs "$mysql_name"
  return 1
}

wait_for_postgresql() {
  for _ in $(seq 1 60); do
    if docker exec "$pg_name" pg_isready -U postgres -d builder >/dev/null 2>&1; then
      return
    fi
    sleep 1
  done
  docker logs "$pg_name"
  return 1
}

prepare_cli_legacy_table() {
  local database_url="$1"
  DATABASE_URL="$database_url" python - <<'PY'
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS tenants"))
            await conn.execute(text(
                "CREATE TABLE tenants ("
                "id INTEGER PRIMARY KEY, "
                "tenant_name VARCHAR(128) NOT NULL, "
                "tenant_code VARCHAR(64) NOT NULL UNIQUE"
                ")"
            ))
            await conn.execute(text(
                "INSERT INTO tenants (id, tenant_name, tenant_code) "
                "VALUES (1, 'tenant-1', 'tenant-1')"
            ))
    finally:
        await engine.dispose()


asyncio.run(main())
PY
}

run_dialect() {
  local dialect="$1"
  local database_url="$2"

  TENANT_PUBLIC_ID_TEST_DATABASE_URL="$database_url" \
    python -m pytest -q \
      tests/test_tenant_public_id_migration.py::test_reconcile_runs_against_configured_sql_dialect \
      tests/test_tenant_public_id_migration.py::test_ensure_tenant_public_id_concurrently_reads_current_value_on_configured_sql_dialect
  prepare_cli_legacy_table "$database_url"
  DATABASE_URL="$database_url" \
    python -m app.tenant_public_id reconcile --verify-only-after-write
  echo "${dialect}=passed"
}

main() {
  trap cleanup EXIT

  export LLM_API_KEY="tenant-public-id-test-key"
  export JWT_SECRET_KEY="tenant-public-id-test-secret"
  export APAAS_ENCRYPTION_KEY="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
  export ALLOW_DEFAULT_ENCRYPTION_KEY="1"

  python -m pytest -q tests/test_tenant_public_id.py tests/test_tenant_public_id_migration.py
  echo "sqlite=passed"

  local bind_host
  bind_host="$(port_bind_host)"
  docker run -d --rm --name "$mysql_name" \
    -e MYSQL_ROOT_PASSWORD=test \
    -e MYSQL_DATABASE=builder \
    -p "${bind_host}::3306" \
    "$mysql_image"
  docker run -d --rm --name "$pg_name" \
    -e POSTGRES_PASSWORD=test \
    -e POSTGRES_DB=builder \
    -p "${bind_host}::5432" \
    "$postgresql_image"

  wait_for_mysql
  wait_for_postgresql

  local mysql_port
  local pg_port
  local db_host
  mysql_port="$(docker port "$mysql_name" 3306/tcp | awk -F: 'NR == 1 { print $NF }')"
  pg_port="$(docker port "$pg_name" 5432/tcp | awk -F: 'NR == 1 { print $NF }')"
  db_host="$(database_host)"
  local mysql_url="mysql+aiomysql://root:test@${db_host}:${mysql_port}/builder"
  local postgresql_url="postgresql+asyncpg://postgres:test@${db_host}:${pg_port}/builder"

  run_dialect mysql "$mysql_url"
  run_dialect postgresql "$postgresql_url"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
