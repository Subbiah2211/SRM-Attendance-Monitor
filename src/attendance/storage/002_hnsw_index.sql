-- Optional: switch vector matching from exact scan to an approximate HNSW index.
--
-- Apply this only once the enrolled population makes an exact scan too slow, and
-- re-measure accuracy afterwards. HNSW trades recall for speed, so it can change match
-- results, not just their latency. Two consequences worth knowing before applying it:
--
--   1. Recall depends on the runtime ef_search setting, which defaults to 40. The
--      matching code sets it explicitly per session; raising it improves recall at the
--      cost of query time.
--   2. The matching query filters to active students and a single model_version. With
--      an approximate index, Postgres applies those filters *after* the index returns
--      its candidates, so a query can come back with fewer rows than requested (or
--      none) even when matching rows exist. The partial index below keeps the filtered
--      case honest for the common query shape.

CREATE INDEX IF NOT EXISTS face_embeddings_hnsw_cosine_idx
    ON face_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
