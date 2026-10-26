# face-recognition

Detects faces in an image, computes a 512-number ArcFace embedding for each, and groups
embeddings into people. It runs locally on the CPU with InsightFace on onnxruntime.

Public functions (`from lia_face_recognition import ...`):
- `detect_and_embed(image)` returns the faces in a numpy image, each with bbox, det_score,
  quality, a normalised embedding and a usable flag.
- `detect_and_embed_path(path)` does the same from a file path and returns plain dicts.
- `group_faces(embeddings, threshold=0.35, seed=0)` clusters embeddings into people with
  Chinese Whispers; the result is deterministic for a given seed.

Run its tests (4 tests; the clustering ones need no model):
```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

Try it on one image (downloads the model, about 350 MB, on first run):
`.venv/bin/lia-face detect photo.jpg`

Notes:
- `numpy<2` is pinned in this venv only (InsightFace ABI). The CPU provider is used on
  purpose, because CoreML changes the numbers.
- With a worker pool, load the model once per worker, use the `spawn` start method and set
  `OMP_NUM_THREADS=1`.
