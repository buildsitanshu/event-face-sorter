-- Local-folder input mode. media_items.source is 'drive' (default, every pre-existing row) or
-- 'local'; local_path is the absolute source file for local items (NULL for Drive items). For
-- local items drive_file_id holds a stable "local-<sha1>" key. reference_faces.local_path is the
-- absolute headshot file for locally enrolled references.
ALTER TABLE media_items ADD COLUMN source TEXT NOT NULL DEFAULT 'drive';
ALTER TABLE media_items ADD COLUMN local_path TEXT;
ALTER TABLE reference_faces ADD COLUMN local_path TEXT;
