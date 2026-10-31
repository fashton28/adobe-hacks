"""Run the viewer: `python -m webapp [--host 127.0.0.1] [--port 8765]` from the repo root."""

import argparse
import sys

from webapp.server import make_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m webapp", description="CHAMELEON local viewer")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="port to listen on (default: 8765, 0 = any free port)")
    parser.add_argument("--quiet", action="store_true", help="do not log each request")
    args = parser.parse_args(argv)
    try:
        server = make_server(args.host, args.port, quiet=args.quiet)
    except OSError as exc:
        print(f"Could not listen on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    host, port = server.server_address[:2]
    shown = "127.0.0.1" if host in ("0.0.0.0", "") else host
    print(f"CHAMELEON viewer running at http://{shown}:{port}  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping viewer.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
