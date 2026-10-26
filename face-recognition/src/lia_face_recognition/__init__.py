# face-recognition: reusable library (detect + embed + group faces in any image).
# Local CPU (InsightFace/ArcFace via onnxruntime), zero LLM cost. Intake-agnostic.
from .embed import Face, detect_and_embed, detect_and_embed_path
from .group import group_faces

__version__ = "0.1.0"
__all__ = ["Face", "detect_and_embed", "detect_and_embed_path", "group_faces"]
