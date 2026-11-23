"""Run the Time Library server: python -m tl_server --data-dir /data"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys

from . import DEFAULT_PORT, SERVER_VERSION
from .app import create_server

RESTART = 75  # tells the container's launcher to start the server again (see deploy/nas/launcher.py)


def _stop(*_args) -> None:
    raise KeyboardInterrupt


def main() -> None:
    parser = argparse.ArgumentParser(prog="tl_server", description="Time Library server")
    parser.add_argument("--data-dir", default=os.environ.get("TL_DATA_DIR", "./data"))
    parser.add_argument("--host", default=os.environ.get("TL_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("TL_PORT", DEFAULT_PORT)))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    httpd = create_server(args.data_dir, args.host, args.port)
    store = httpd.store  # type: ignore[attr-defined]
    signal.signal(signal.SIGTERM, _stop)  # stopping the container ends the same way as Ctrl-C: nothing half-written
    logging.getLogger("tl_server").info(
        "version %s listening on %s:%s · server_id=%s · admin token file: %s",
        SERVER_VERSION,
        args.host,
        httpd.server_address[1],
        store.server_id,
        store.admin_token_path,
    )
    httpd.local_model.resume_on_boot()  # type: ignore[attr-defined]
    httpd.distiller.run_scheduler()  # type: ignore[attr-defined]
    httpd.evolution.run_scheduler()  # type: ignore[attr-defined]
    httpd.vectors.start()  # type: ignore[attr-defined]  (only if recall by meaning is switched on)
    httpd.doctor.run_scheduler()  # type: ignore[attr-defined]
    httpd.words.start()  # type: ignore[attr-defined]
    httpd.continuity.run_scheduler()  # type: ignore[attr-defined]
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.evolution.shutdown()  # type: ignore[attr-defined]
        httpd.vectors.shutdown()  # type: ignore[attr-defined]
        httpd.doctor.shutdown()  # type: ignore[attr-defined]
        httpd.distiller.shutdown()  # type: ignore[attr-defined]
        httpd.recall.shutdown()  # type: ignore[attr-defined]
        httpd.words.shutdown()  # type: ignore[attr-defined]
        httpd.continuity.shutdown()  # type: ignore[attr-defined]
        httpd.local_model.shutdown()  # type: ignore[attr-defined]
        httpd.server_close()
        store.close()
    if httpd.restart_requested.is_set():  # type: ignore[attr-defined]
        sys.exit(RESTART)


if __name__ == "__main__":
    main()
