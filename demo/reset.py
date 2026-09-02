#!/usr/bin/env python3
"""Reset AutoBuy to a clean, known state before a demo take.

Recording is iterative — you will re-shoot. Each take must start from the same
place or the audit trail accumulates junk from earlier attempts and the story
stops being legible.

    python demo/reset.py            # empty trail, no grant (clip 2 starts here)
    python demo/reset.py --granted  # empty trail, ₹5,000 authorised (clip 1)

Clip 1 (interoperability) needs a live grant, because the external agent must be
able to buy. Clip 2 (revocation) must start with none, so the first beat is the
agent being refused.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"

# A demo reset should print what it did, not a wall of SQL. DEBUG=true in a
# local .env turns on SQLAlchemy echo, which makes this unwatchable on camera.
os.environ["DEBUG"] = "false"


def run(label: str, *args: str) -> None:
    print(f"  {label} ...", end=" ", flush=True)
    result = subprocess.run(
        args, cwd=BACKEND, capture_output=True, text=True, env=os.environ
    )
    if result.returncode != 0:
        print("FAILED")
        print(result.stdout[-1500:])
        print(result.stderr[-1500:])
        sys.exit(1)
    print("ok")


async def grant(cap_minor: int, hours: int) -> None:
    # A relative SQLite path in DATABASE_URL resolves against the *current*
    # directory, so importing the app from anywhere but `backend/` silently
    # opens a different, empty database — and the grant lands somewhere the
    # server will never read.
    os.chdir(BACKEND)
    sys.path.insert(0, str(BACKEND))
    from app.db.session import SessionLocal, engine
    from app.services.grants import grant_access

    async with SessionLocal() as session:
        g = await grant_access(
            session,
            spend_cap_minor=cap_minor,
            expires_in_hours=hours,
            note="Granted by demo/reset.py",
        )
        print(f"  granted {g.spend_cap_minor / 100:,.2f} for {hours}h  ({g.id})")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset AutoBuy for a demo take.")
    parser.add_argument(
        "--granted",
        action="store_true",
        help="Also grant the agent ₹5,000 for 24h (clip 1 needs this).",
    )
    parser.add_argument("--cap-minor", type=int, default=500_000)
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    python = str(BACKEND / ".venv" / "bin" / "python")
    if not Path(python).exists():
        python = sys.executable

    print("\nResetting AutoBuy for a clean take")

    db = BACKEND / "autobuy.db"
    if db.exists():
        db.unlink()
        print("  dropped the local database ... ok")

    run("applying migrations", python, "-m", "alembic", "upgrade", "head")
    run("seeding the catalog", python, "-m", "scripts.seed_catalog")

    if args.granted:
        asyncio.run(grant(args.cap_minor, args.hours))
    else:
        print("  no grant issued — the agent starts with no authority")

    print("\nReady.\n")


if __name__ == "__main__":
    main()
