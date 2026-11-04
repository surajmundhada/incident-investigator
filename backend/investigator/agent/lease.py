import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def keep_lease(repo, claim):
    stop = threading.Event()

    def beat():
        while not stop.wait(10):
            try:
                repo.heartbeat(claim)
            except Exception:
                # Do not log SQL parameters, incident contents, or credentials.
                logger.warning(
                    "Lease heartbeat stopped; ownership will be checked before further actions"
                )
                return

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)
