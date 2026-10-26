# face.detect + face.embed: the per-image step. Returns one Face per detection with
# a 512-d L2-normalized ArcFace embedding, the bbox, quality metrics, and the usable verdict.
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from .config import DEFAULT_GATE, QualityGate


@dataclass
class Face:
    bbox: list[int]            # [x1, y1, x2, y2] in image pixels
    det_score: float           # detector confidence (0..1)
    face_px: int               # min(width, height) of the bbox
    blur_var: float            # variance-of-Laplacian sharpness
    embedding: list[float]     # 512 float32, L2-normalized (cosine-ready)
    is_usable: bool            # passed all quality gates

    def as_dict(self) -> dict:
        return asdict(self)


def _load_bgr(image) -> np.ndarray:
    """Accept a path (str), raw bytes, or an HxWx3 BGR uint8 ndarray; return BGR uint8."""
    import cv2

    if isinstance(image, np.ndarray):
        return image
    if isinstance(image, (bytes, bytearray)):
        arr = np.frombuffer(bytes(image), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    else:  # path-like
        img = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"could not decode image: {image!r}")
    return img


def _blur_var(crop_bgr: np.ndarray) -> float:
    import cv2

    if crop_bgr.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def detect_and_embed(image, *, gate: QualityGate = DEFAULT_GATE) -> list[Face]:
    """Detect every face in `image`, embed it, score quality. Pure: no I/O beyond decoding."""
    from .detector import get_app

    img = _load_bgr(image)
    h, w = img.shape[:2]
    faces: list[Face] = []
    for f in get_app().get(img):
        x1, y1, x2, y2 = (int(v) for v in f.bbox)
        x1c, y1c, x2c, y2c = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        face_px = int(min(x2 - x1, y2 - y1))
        blur = _blur_var(img[y1c:y2c, x1c:x2c])
        det = float(f.det_score)
        emb = np.asarray(f.normed_embedding, dtype=np.float32)
        usable = det >= gate.min_det_score and face_px >= gate.min_face_px and blur >= gate.min_blur_var
        faces.append(
            Face(
                bbox=[x1, y1, x2, y2],
                det_score=det,
                face_px=face_px,
                blur_var=blur,
                embedding=emb.tolist(),
                is_usable=bool(usable),
            )
        )
    return faces


def detect_and_embed_path(path: str, *, gate: QualityGate = DEFAULT_GATE) -> list[dict]:
    """JSON-friendly variant: takes a file path, returns a list of plain dicts."""
    return [f.as_dict() for f in detect_and_embed(path, gate=gate)]
