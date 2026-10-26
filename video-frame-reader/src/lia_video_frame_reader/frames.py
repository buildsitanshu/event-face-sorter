# Frame sampling: one ffmpeg pass writes evenly-spaced JPEG frames to out_dir; we attach a
# timecode (seconds) to each. Uniform sampling => timecode = index / fps (first frame ~t=0).
# Frames land on disk because the downstream consumer (face.detect) takes file paths, and the
# GUI's frame-strip view serves them directly.
from __future__ import annotations

import glob
import os
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class Frame:
    index: int
    timecode_sec: float
    frame_path: str

    def as_dict(self) -> dict:
        return {"index": self.index, "timecode_sec": self.timecode_sec, "frame_path": self.frame_path}


def sample_frames(
    video_path: str,
    out_dir: str,
    *,
    fps: float = 1.0,
    max_frames: int | None = None,
    quality: int = 3,
) -> list[Frame]:
    """Sample `fps` frames/second from the video into out_dir. Returns Frames with timecodes.
    `quality` is ffmpeg -q:v (2=best..31=worst); 3 is a sharp, small JPEG good for face detection."""
    if fps <= 0:
        raise ValueError("fps must be > 0")
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "frame_%06d.jpg")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", f"fps={fps}",
        "-q:v", str(quality),
    ]
    if max_frames:
        cmd += ["-frames:v", str(int(max_frames))]
    cmd += ["-y", pattern]
    subprocess.run(cmd, check=True)

    files = sorted(glob.glob(os.path.join(out_dir, "frame_*.jpg")))
    return [Frame(index=i, timecode_sec=round(i / fps, 3), frame_path=p) for i, p in enumerate(files)]


def iter_frames(
    video_path: str, out_dir: str, *, fps: float = 1.0, max_frames: int | None = None
) -> Iterator[Frame]:
    """Generator over sampled frames: lets a consumer process frame-by-frame without holding
    all frames in memory at once."""
    yield from sample_frames(video_path, out_dir, fps=fps, max_frames=max_frames)
