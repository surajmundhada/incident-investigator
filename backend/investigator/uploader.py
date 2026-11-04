"""Optional artifact delivery process. Never creates cloud resources."""

import argparse
import time

from sqlalchemy.exc import SQLAlchemyError

from .artifacts import configured_artifacts
from .config import Settings
from .db import make_engine, sessions_for
from .repository import LostLease, Repository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    engine = make_engine(settings)
    manager = configured_artifacts(Repository(sessions_for(engine), settings))
    if manager is None:
        raise ValueError("Configure an artifact backend before starting the uploader")
    try:
        while True:
            try:
                worked = manager.deliver_once()
            except LostLease:
                worked = True  # Another owner reconciles the stable object key.
            except SQLAlchemyError:
                worked = False  # Database reconnect/reclaim stays in the authoritative path.
            if args.once:
                break
            if not worked:
                time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
