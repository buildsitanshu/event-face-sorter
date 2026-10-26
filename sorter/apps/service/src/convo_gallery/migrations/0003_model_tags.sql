-- Accuracy reprocess (det_size 1600 + antelopev2). Two columns make the work resumable and the
-- matching space provable:
--   media_items.detect_model_tag : the model a photo was LAST detected at. redetect filters on it
--     (skip photos already at the current model) and stamps it on success, even when 0 faces are
--     found: so a kill/power-outage resumes exactly where it stopped and never redoes a photo.
--   reference_faces.embed_model_tag: the model a headshot was enrolled at. Matching asserts the
--     roster and the candid faces share ONE model: cosine distance across model spaces is
--     meaningless, so mixing buffalo_l with antelopev2 silently corrupts every match.
ALTER TABLE media_items ADD COLUMN detect_model_tag TEXT;
ALTER TABLE reference_faces ADD COLUMN embed_model_tag TEXT NOT NULL DEFAULT 'buffalo_l@cpu';

-- Backfill detect_model_tag from the faces already written, so the live DB's 69%-complete redetect
-- resumes instead of restarting. A photo whose faces are all antelopev2 is done; one with any
-- buffalo face still needs redetect; one with zero faces is left NULL (re-checked, cheap).
UPDATE media_items SET detect_model_tag = 'antelopev2@cpu'
 WHERE id IN (SELECT media_id FROM faces GROUP BY media_id
              HAVING SUM(embed_model_tag <> 'antelopev2@cpu') = 0 AND COUNT(*) > 0);

CREATE INDEX IF NOT EXISTS idx_media_detect_tag ON media_items(detect_model_tag);
CREATE INDEX IF NOT EXISTS idx_faces_model ON faces(embed_model_tag);
