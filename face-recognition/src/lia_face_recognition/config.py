# Configuration: model + quality gates + the clustering operating point.
# These are the only knobs; an operator tunes the cluster threshold via the gallery's
# validation sweep and freezes the chosen value here (or passes it per call).
from dataclasses import dataclass

# antelopev2 = SCRFD-10G detector + Glint360K ResNet100 ArcFace (512-d), ~360 MB. Stronger than
# buffalo_l for studio-headshot -> crowd matching. Overridable via env for an easy A/B / fallback.
import os

MODEL_NAME = os.environ.get("FACE_MODEL", "antelopev2")
PROVIDERS = ("CPUExecutionProvider",)  # CPU-only; CoreML changes numerics + invalidates baselines
# det_size is the detector input. The OLD 640 downscaled our 2048px previews 3.2x, so >50% of faces
# fell <60px and 31% (<40px) were dropped. 1600 runs detection at ~full preview res -> recovers them.
DET_SIZE = (int(os.environ.get("FACE_DET_SIZE", "1600")),) * 2
DET_THRESH = float(os.environ.get("FACE_DET_THRESH", "0.4"))  # was RetinaFace default 0.5
MODEL_TAG = f"{MODEL_NAME}@cpu"  # stamped on each face row so models are never mixed


@dataclass(frozen=True)
class QualityGate:
    """A face must clear all three bars to be 'usable' (clustered + queried).
    Below-bar faces are still returned (is_usable=False) for audit, never silently dropped."""

    min_det_score: float = 0.50  # detector confidence
    min_face_px: int = 30        # was 40; higher-res detection finds more real small faces
    min_blur_var: float = 8.0    # variance-of-Laplacian sharpness floor


DEFAULT_GATE = QualityGate()

# Cosine DISTANCE on L2-normalized ArcFace embeddings. <= threshold => same person.
# 0.35 is the literature operating point; the gallery sweeps {0.30, 0.35, 0.40} and freezes one.
CLUSTER_THRESHOLD = 0.35
