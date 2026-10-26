-- Accompaniment ("who came with you") tables. All additive; the matching/classification tables are
-- untouched. Co-presence is computed strictly within the single antelopev2 embedding space (the only
-- space faces are clustered in), so no cross-model leak is possible here.

-- Guard flags per cluster: a 'fixture' is ubiquitous (appears in too many photos to be a personal
-- companion: staff, the photographer, or an over-merged cluster); a 'connector' shares
-- intimate frames with too many distinct named people (usher, or a merged identity). Both are excluded
-- from companion candidates. 'ok' clusters are eligible.
CREATE TABLE IF NOT EXISTS cluster_flags (
  cluster_id   INTEGER PRIMARY KEY,
  flag         TEXT NOT NULL DEFAULT 'ok',   -- 'ok' | 'fixture' | 'connector'
  reason       TEXT,
  media_count  INTEGER NOT NULL DEFAULT 0,
  grad_breadth INTEGER NOT NULL DEFAULT 0,   -- # distinct named people sharing an intimate frame
  created_at   INTEGER
);

-- Symmetric co-presence edges between ANY two clusters that share a photo (includes unknown<->unknown,
-- the "full social graph"). Stored once per unordered pair with a_cluster < b_cluster. weight = sum of
-- per-photo pair_weight (crowd-down-weighted, foreground-gated); intimate/burst are witness counters.
CREATE TABLE IF NOT EXISTS co_presence_edges (
  a_cluster       INTEGER NOT NULL,
  b_cluster       INTEGER NOT NULL,
  co_photos       INTEGER NOT NULL,          -- # photos both appear in (within the edge-build cap)
  intimate_photos INTEGER NOT NULL,          -- # shared photos with <= 2 distinct people (gold witness)
  small_photos    INTEGER NOT NULL,          -- # shared photos with <= 5 distinct people (non-crowd witness)
  burst_photos    INTEGER NOT NULL,          -- # shared photos time-adjacent to another shared photo
  weight          REAL    NOT NULL,          -- summed pair_weight
  PRIMARY KEY (a_cluster, b_cluster)
);
CREATE INDEX IF NOT EXISTS idx_cpe_a ON co_presence_edges(a_cluster);
CREATE INDEX IF NOT EXISTS idx_cpe_b ON co_presence_edges(b_cluster);

-- Per named person ranked companion suggestions (anchored on a named person, guards applied). These are CANDIDATES
-- the named person confirms; they are never presented as fact. bucket = high|likely|maybe.
CREATE TABLE IF NOT EXISTS companion_candidates (
  grad_cluster    INTEGER NOT NULL,
  cand_cluster    INTEGER NOT NULL,
  score           REAL    NOT NULL,
  co_photos       INTEGER NOT NULL,
  intimate_photos INTEGER NOT NULL,
  small_photos    INTEGER NOT NULL,
  burst_photos    INTEGER NOT NULL,
  bucket          TEXT    NOT NULL,
  rank            INTEGER NOT NULL,
  PRIMARY KEY (grad_cluster, cand_cluster)
);
CREATE INDEX IF NOT EXISTS idx_cc_grad ON companion_candidates(grad_cluster, rank);

-- The human ground truth: a named person confirms or denies a suggested companion. This is the external
-- signal the whole feature is gated on, and the label store that lets the ranker improve over time.
CREATE TABLE IF NOT EXISTS companion_confirmations (
  grad_cluster INTEGER NOT NULL,
  cand_cluster INTEGER NOT NULL,
  decision     TEXT    NOT NULL,             -- 'yes' | 'no'
  decided_at   INTEGER NOT NULL,
  PRIMARY KEY (grad_cluster, cand_cluster)
);
