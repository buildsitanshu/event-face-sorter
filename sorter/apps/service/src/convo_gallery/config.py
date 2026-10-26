# Runtime config. Inputs are a local photo folder (default) or Google Drive folder ids; outputs live under DATA_DIR.
import os

# INPUT 1: the media folder: photos + videos to organise by face.
ROOT_FOLDER_ID = os.environ.get("CONVO_ROOT_FOLDER_ID", "")
# INPUT 2: the headshot folder: one clear headshot per person to identify.
ROSTER_FOLDER_ID = os.environ.get("CONVO_ROSTER_FOLDER_ID", "")
# Local-folder mode: a directory of photos/videos to sort, and an OPTIONAL directory of headshots.
MEDIA_DIR = os.environ.get("CONVO_MEDIA_DIR", "")
ROSTER_DIR = os.environ.get("CONVO_ROSTER_DIR", "")
# Google Drive OAuth token json (drive.readonly is enough).
OAUTH_PATH = os.environ.get("CONVO_OAUTH", os.path.expanduser("~/.config/event-face-sorter/oauth.json"))
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

DATA_DIR = os.environ.get(
    "CONVO_DATA_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../data")),
)
DB_PATH = os.path.join(DATA_DIR, "gallery.db")
PREVIEWS_DIR = os.path.join(DATA_DIR, "previews")
CROPS_DIR = os.path.join(DATA_DIR, "crops")
FRAMES_DIR = os.path.join(DATA_DIR, "frames")
ORIGINALS_DIR = os.path.join(DATA_DIR, "originals")

# Output of the sort step: one folder per person. MIN_PHOTOS hides people seen in fewer photos.
SORTED_DIR = os.path.join(DATA_DIR, "sorted")
WEB_DIR = os.path.join(DATA_DIR, "web")
MIN_PHOTOS = int(os.environ.get("CONVO_MIN_PHOTOS", "2"))
SORT_MODE = os.environ.get("CONVO_SORT_MODE", "copy")  # copy | hardlink | symlink

# Video sampling rate (frames/sec) for face detection in clips.
VIDEO_FPS = float(os.environ.get("CONVO_VIDEO_FPS", "0.5"))

# Session gap: a time gap larger than this (seconds) starts a new event/session.
SESSION_GAP_SEC = int(os.environ.get("CONVO_SESSION_GAP_SEC", str(90 * 60)))


def ensure_dirs() -> None:
    for d in (DATA_DIR, PREVIEWS_DIR, CROPS_DIR, FRAMES_DIR, ORIGINALS_DIR):
        os.makedirs(d, exist_ok=True)
