# Process-singleton InsightFace model. Loaded ONCE per process (heavy: ~326 MB).
# In a multiprocessing pool each worker calls get_app() once in its initializer, so the
# model is never pickled across the process boundary nor reloaded per task.
import threading

from . import config
from .config import DET_SIZE, DET_THRESH, MODEL_NAME, PROVIDERS

_lock = threading.Lock()
_app = None


def get_app():
    """Return the shared FaceAnalysis app (detector + ArcFace), CPU execution provider.
    Falls back to buffalo_l if the configured model can't be loaded, the det_size fix is the
    main accuracy win regardless of model."""
    global _app
    if _app is None:
        with _lock:
            if _app is None:
                # Imported lazily so the module imports cheaply (tests that only exercise
                # clustering never pay the onnxruntime/insightface import cost).
                from insightface.app import FaceAnalysis

                name = MODEL_NAME
                try:
                    app = FaceAnalysis(name=name, providers=list(PROVIDERS))
                except Exception:
                    name = "buffalo_l"
                    config.MODEL_TAG = "buffalo_l@cpu"
                    app = FaceAnalysis(name=name, providers=list(PROVIDERS))
                # ctx_id is irrelevant when providers force CPU; det_thresh recovers small faces.
                app.prepare(ctx_id=0, det_thresh=DET_THRESH, det_size=DET_SIZE)
                _app = app
    return _app
