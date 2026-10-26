# sorter: the application

The event face sorter. It reads a folder of photos and videos, finds faces with
`face-recognition`, samples video frames with `video-frame-reader`, groups faces into people,
and writes one folder per person plus a local web gallery. Data lives in `data/`
(SQLite file `gallery.db`, previews, crops, `sorted/`, `web/`).

The Python module is still named `convo_gallery`. Historical names such as `grad_cluster`,
`is_graduate`, `graduates_total` and the `students` table remain in code and output for
compatibility. They do not mean anything beyond "named person".

Layout:
- `apps/service/src/convo_gallery/` holds the pipeline, the CLI (`cli.py`) and the FastAPI
  viewer (`api.py`, `viewer/`).
- `tests/` holds the unit tests. Run the tests with `./.venv/bin/python -m pytest -q`; the floor for this suite lives in `scripts/check.sh`.

Run the tests (from this folder, after `../setup.sh`):
```bash
.venv/bin/python -m pytest -q
```

Public entry points: `python -m convo_gallery.cli run-all|sort|export-web|classify|summary`
and `convo_gallery.api:app` (served by `../view.sh`).
