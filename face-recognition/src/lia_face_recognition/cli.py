# Tiny local CLI for smoke-testing the library.
#   lia-face health
#   lia-face detect <image-path>
from __future__ import annotations

import argparse
import json

from . import __version__


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="lia-face")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("health")
    d = sub.add_parser("detect")
    d.add_argument("image")
    args = p.parse_args(argv)

    if args.cmd == "health":
        print(json.dumps({"ok": True, "tool": "face-recognition", "version": __version__}))
    elif args.cmd == "detect":
        from .embed import detect_and_embed_path

        faces = detect_and_embed_path(args.image)
        summary = [{k: v for k, v in f.items() if k != "embedding"} for f in faces]
        print(json.dumps({"image": args.image, "count": len(faces), "faces": summary}, indent=2))


if __name__ == "__main__":
    main()
