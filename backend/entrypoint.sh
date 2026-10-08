#!/bin/sh
set -e

echo "[entrypoint] waiting for database..."
python - <<'PYEOF'
import asyncio
import os
import sys
import time

import asyncpg


async def wait():
    url = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    for _ in range(60):
        try:
            conn = await asyncpg.connect(url)
            await conn.close()
            return
        except Exception:
            time.sleep(2)
    sys.exit("[entrypoint] database never became ready")


asyncio.run(wait())
PYEOF

echo "[entrypoint] running migrations..."
alembic upgrade head

if [ "$RUN_SEED" = "true" ]; then
  echo "[entrypoint] checking demo data..."
  python - <<'PYEOF'
import asyncio
from sqlalchemy import select, func
from app.core.database import AsyncSessionLocal
from app.models import Underlying


async def has_data() -> bool:
    async with AsyncSessionLocal() as session:
        count = (await session.execute(select(func.count()).select_from(Underlying))).scalar_one()
        return count > 0


if not asyncio.run(has_data()):
    import subprocess
    subprocess.run(["python", "-m", "scripts.seed"], check=True)
else:
    print("[entrypoint] demo data already present, skipping seed")
PYEOF
fi

echo "[entrypoint] starting: $@"
exec "$@"
