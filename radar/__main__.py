"""CLI: python -m radar run|digest [--dry-run]."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from radar import pipeline
from radar.config import DEFAULT_DIR, load_config
from radar.http import Http
from radar.store import Store
from radar.timeutil import utcnow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="radar", description="Truwealth viral content radar")
    parser.add_argument("command", choices=["run", "digest"])
    parser.add_argument("--dry-run", action="store_true", help="write emails to --out instead of sending them")
    parser.add_argument("--db", default=os.environ.get("RADAR_DB", "radar.db"))
    parser.add_argument("--out", default="out")
    parser.add_argument("--config", default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(Path(args.config))
    store = Store(args.db)
    http = Http()
    try:
        if args.command == "run":
            return pipeline.run(cfg, store, http, utcnow(), dry_run=args.dry_run, out_dir=Path(args.out), env=os.environ)
        return pipeline.digest(cfg, store, utcnow(), dry_run=args.dry_run, out_dir=Path(args.out), env=os.environ)
    finally:
        http.close()
        store.close()


if __name__ == "__main__":
    sys.exit(main())
