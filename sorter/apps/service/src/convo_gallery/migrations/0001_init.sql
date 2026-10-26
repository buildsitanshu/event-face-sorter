-- event-face-sorter schema (its own SQLite file, data/gallery.db). One row per Drive media item; faces
-- come from both photos and video frames; clusters == people; sessions group by time. The
-- status column is the resumable, race-free claim backbone (atomic UPDATE...WHERE...RETURNING).

CREATE TABLE IF NOT EXISTS sessions (
  id           INTEGER PRIMARY KEY,
  started_utc  INTEGER,
  ended_utc    INTEGER,
  media_count  INTEGER NOT NULL DEFAULT 0,
  label        TEXT
);

CREATE TABLE IF NOT EXISTS media_items (
  id                INTEGER PRIMARY KEY,
  drive_file_id     TEXT UNIQUE NOT NULL,          -- idempotency anchor: re-ingest = INSERT OR IGNORE
  filename          TEXT NOT NULL,
  drive_path        TEXT,
  size_bytes        INTEGER,
  mime_type         TEXT,
  kind              TEXT NOT NULL DEFAULT 'unknown', -- raw|jpeg|heic|video|other
  preview_path      TEXT,
  preview_source    TEXT,                            -- drive_thumbnail|previewimage|jpgfromraw|rawpy
  datetime_original TEXT,
  dt_utc            INTEGER,
  dt_is_tz_known    INTEGER NOT NULL DEFAULT 0,
  gps_lat           REAL,
  gps_lon           REAL,
  camera_make       TEXT,
  camera_model      TEXT,
  duration_sec      REAL,                            -- videos only
  session_id        INTEGER REFERENCES sessions(id),
  status            TEXT NOT NULL DEFAULT 'listed',  -- listed|claimed|processed|grouped|*_error|skipped
  claimed_by        TEXT,                            -- node id that claimed it (for example "local")
  attempts          INTEGER NOT NULL DEFAULT 0,
  error_msg         TEXT,
  created_at        INTEGER,
  processed_at      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_media_status  ON media_items(status);
CREATE INDEX IF NOT EXISTS idx_media_session ON media_items(session_id);
CREATE INDEX IF NOT EXISTS idx_media_kind    ON media_items(kind);
CREATE INDEX IF NOT EXISTS idx_media_dt      ON media_items(dt_utc);

CREATE TABLE IF NOT EXISTS clusters (
  id             INTEGER PRIMARY KEY,
  label          TEXT,                               -- optional manual name
  rep_face_id    INTEGER,                            -- representative face for the grid
  face_count     INTEGER NOT NULL DEFAULT 0,
  media_count    INTEGER NOT NULL DEFAULT 0,
  is_unknown     INTEGER NOT NULL DEFAULT 0,         -- singleton/outlier bucket
  cluster_run_id INTEGER NOT NULL DEFAULT 1,
  created_at     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_clusters_run ON clusters(cluster_run_id);

CREATE TABLE IF NOT EXISTS faces (
  id              INTEGER PRIMARY KEY,
  media_id        INTEGER NOT NULL REFERENCES media_items(id) ON DELETE CASCADE,
  source          TEXT NOT NULL DEFAULT 'photo',     -- photo|video
  frame_index     INTEGER,                            -- video frame ordinal (NULL for photos)
  timecode_sec    REAL,                               -- video timecode (NULL for photos)
  bbox            TEXT NOT NULL,                       -- json [x1,y1,x2,y2]
  det_score       REAL NOT NULL,
  face_px         INTEGER NOT NULL,
  blur_var        REAL,
  embedding       BLOB NOT NULL,                       -- 512 float32 = 2048 bytes
  embed_model_tag TEXT NOT NULL DEFAULT 'buffalo_l@cpu',
  crop_path       TEXT,
  cluster_id      INTEGER REFERENCES clusters(id),     -- NULL until grouped
  is_usable       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_faces_media   ON faces(media_id);
CREATE INDEX IF NOT EXISTS idx_faces_cluster ON faces(cluster_id);
CREATE INDEX IF NOT EXISTS idx_faces_usable  ON faces(is_usable);

-- students: visit and download counts per visitor id. Historical table name, kept for compatibility;
-- the face_cluster_ids column is the forward seam for a later "claim" feature.
CREATE TABLE IF NOT EXISTS students (
  roll_number      INTEGER PRIMARY KEY,
  first_seen_at    INTEGER,
  last_seen_at     INTEGER,
  downloads        INTEGER NOT NULL DEFAULT 0,
  face_cluster_ids TEXT
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
