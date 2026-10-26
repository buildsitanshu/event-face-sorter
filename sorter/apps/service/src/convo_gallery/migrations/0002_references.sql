-- Reference roster: the known faces we actually care about (the roster headshots). Each row is one
-- headshot's primary-face embedding; ref_person_id groups multiple headshots of the same person
-- after dedupe. Candid faces in `faces` are matched to the nearest reference person; non-matches
-- are filtered out of the gallery (cluster_id stays NULL).
CREATE TABLE IF NOT EXISTS reference_faces (
  id            INTEGER PRIMARY KEY,
  drive_file_id TEXT,
  filename      TEXT NOT NULL,
  embedding     BLOB NOT NULL,        -- 512 float32
  ref_person_id INTEGER               -- assigned by dedupe (groups same-person headshots)
);
CREATE INDEX IF NOT EXISTS idx_reffaces_person ON reference_faces(ref_person_id);
