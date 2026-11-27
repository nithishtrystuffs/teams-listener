import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        from teams_listener import selftest

        sys.exit(selftest.main(sys.argv[2:]))
    from teams_listener.__main__ import main

    main()
