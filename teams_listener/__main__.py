import sys

from .logsetup import setup_logging


def main() -> None:
    if "--tk" in sys.argv[1:]:
        setup_logging()
        from .ui.app import App

        App().run()
    else:
        from .server import main as server_main

        server_main()


if __name__ == "__main__":
    main()
