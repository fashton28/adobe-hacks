"""Run the viewer: `python -m webapp [--host localhost] [--port 8765]` from the repo root."""

import argparse
import os
import sys
import threading

from webapp.server import (
    LOCALHOST,
    make_servers,
    origin_matches,
    pipeline_names,
    server_url,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m webapp", description="CHAMELEON local viewer")
    parser.add_argument("--host", default=LOCALHOST,
                        help="interface to bind (default: localhost, meaning both 127.0.0.1 and ::1; "
                             "use 0.0.0.0 or :: to expose it on the network)")
    parser.add_argument("--port", type=int, default=8765, help="port to listen on (default: 8765, 0 = any free port)")
    parser.add_argument("--quiet", action="store_true", help="do not log each request")
    parser.add_argument("--allow-origin", action="append", default=[], metavar="PATTERN",
                        help="also accept browser requests from this origin, e.g. https://example.com or "
                             "https://*.example.com (repeatable; '*' accepts any origin). Loopback origins, "
                             "https://*.adobe.com and https://*.adobe-addons.com are always accepted")
    args = parser.parse_args(argv)
    bad = [o for o in args.allow_origin if o != "*" and not origin_matches(o.replace("://*.", "://x.", 1), o)]
    if bad:
        parser.error(f"--allow-origin expects scheme://host[:port] or scheme://*.domain, got {bad}")
    try:
        servers = make_servers(args.host, args.port, quiet=args.quiet, allow_origins=args.allow_origin)
    except OSError as exc:
        print(f"Could not listen on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1

    env = os.environ.get("CHAMELEON_PIPELINE")
    names, default = pipeline_names()
    if env and env not in names:
        print(f"Ignoring unknown CHAMELEON_PIPELINE={env!r}; available: {', '.join(names)}", file=sys.stderr)
    bound = ", ".join(str(s.server_address[0]) for s in servers)
    print(f"CHAMELEON viewer running at {server_url(servers[0], args.host)}  "
          f"(listening on {bound}; default pipeline {default}; Ctrl+C to stop)", flush=True)

    threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers[1:]]
    for thread in threads:
        thread.start()
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        print("\nStopping viewer.")
    finally:
        for server in servers[1:]:
            server.shutdown()
        for server in servers:
            server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
