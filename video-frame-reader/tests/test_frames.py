# Real ffmpeg test: synthesize a 3-second test pattern, probe it, sample at 1 fps, and assert
# we get ~3 frames on disk with monotonic timecodes. Exercises the actual ffmpeg/ffprobe path.
import os
import subprocess

from lia_video_frame_reader.frames import sample_frames
from lia_video_frame_reader.probe import probe


def _make_video(path: str, seconds: int = 3) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc=duration={seconds}:size=320x240:rate=25", "-y", path],
        check=True,
    )


def test_probe_and_sample(tmp_path):
    video = str(tmp_path / "t.mp4")
    _make_video(video, 3)

    info = probe(video)
    assert info["duration_sec"] >= 2.5
    assert info["width"] == 320 and info["height"] == 240

    out = str(tmp_path / "frames")
    frames = sample_frames(video, out, fps=1.0)
    assert 2 <= len(frames) <= 4  # ~3 frames for a 3s clip at 1 fps
    assert frames[0].timecode_sec == 0.0
    assert all(os.path.exists(f.frame_path) for f in frames)
    tcs = [f.timecode_sec for f in frames]
    assert tcs == sorted(tcs)


def test_max_frames(tmp_path):
    video = str(tmp_path / "t.mp4")
    _make_video(video, 5)
    frames = sample_frames(video, str(tmp_path / "f"), fps=2.0, max_frames=3)
    assert len(frames) == 3
