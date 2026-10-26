# video-frame-reader

Samples a video into JPEG frames with timecodes using ffmpeg. The sorter feeds each frame to
`face-recognition` to find who appears in a clip.

Public functions (`from lia_video_frame_reader import ...`):
- `sample_frames(video_path, out_dir, fps=1.0, max_frames=None)` writes frames to disk and
  returns a list of `Frame` objects with their timecodes.
- `iter_frames(...)` yields the same frames one at a time.
- `probe(video_path)` returns duration, resolution, codec and frame rate.

Run its tests (2 tests; they build a small clip with ffmpeg):
```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

Needs `ffmpeg` and `ffprobe` on PATH (`brew install ffmpeg`).
