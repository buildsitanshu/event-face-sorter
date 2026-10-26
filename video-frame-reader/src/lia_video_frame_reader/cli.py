# Local CLI smoke test:
#   lia-video probe <video>
#   lia-video frames <video> <out_dir> [--fps 1.0]
from __future__ import annotations

import argparse
import json


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="lia-video")
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("probe")
    pr.add_argument("video")
    fr = sub.add_parser("frames")
    fr.add_argument("video")
    fr.add_argument("out_dir")
    fr.add_argument("--fps", type=float, default=1.0)
    args = p.parse_args(argv)

    if args.cmd == "probe":
        from .probe import probe

        print(json.dumps(probe(args.video), indent=2))
    elif args.cmd == "frames":
        from .frames import sample_frames

        frames = sample_frames(args.video, args.out_dir, fps=args.fps)
        print(json.dumps({"count": len(frames), "frames": [f.as_dict() for f in frames]}, indent=2))


if __name__ == "__main__":
    main()
