# video-frame-reader: sample any video into frames + timecodes.
# ffmpeg engine, zero LLM. Frames are written to disk (consumers like face-recognition take paths).
from .frames import Frame, iter_frames, sample_frames
from .probe import probe

__version__ = "0.1.0"
__all__ = ["Frame", "sample_frames", "iter_frames", "probe"]
