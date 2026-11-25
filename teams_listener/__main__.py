import logging
import sys
import warnings

from .config import DEFAULT_SETTINGS_PATH


def main() -> None:
    log_path = DEFAULT_SETTINGS_PATH.parent / "app.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=log_path, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    warnings.filterwarnings("ignore", message="data discontinuity in recording")
    sys.excepthook = lambda *exc: logging.getLogger("teams_listener").critical("unhandled", exc_info=exc)

    from .ui.app import App

    App().run()


if __name__ == "__main__":
    main()
