# ffprobe wrapper: duration, resolution, codec, frame rate. Pure read, no decode.
from __future__ import annotations

import json
import subprocess


def probe(video_path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(video_path),
    ]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    vstream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    duration = data.get("format", {}).get("duration") or vstream.get("duration") or 0
    return {
        "duration_sec": float(duration),
        "width": vstream.get("width"),
        "height": vstream.get("height"),
        "codec": vstream.get("codec_name"),
        "avg_frame_rate": vstream.get("avg_frame_rate"),
    }
