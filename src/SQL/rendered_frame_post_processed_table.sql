-- Streaming frame bus: these four tables are the ones the Python client tails
-- with `SELECT ... STREAM` (continuous queries, ClickHouse 26.6+).
--
-- Why MergeTree instead of Memory:
--   `STREAM` rejects the Memory engine ("Storage Memory doesn't support STREAM",
--   ILLEGAL_STREAM). Continuous queries are only supported on MergeTree-family
--   tables, so the post-processed output must live in MergeTree.
--
-- Why the TTL:
--   MergeTree is append-only, and every frame is a ~300 KB row. Without cleanup
--   a play session would grow the table without bound. Each INSERT lands as its
--   own part (one row), so `ttl_only_drop_parts = 1` lets whole parts age out
--   cheaply and `merge_with_ttl_timeout = 1` checks for expired parts every
--   second. The live STREAM keeps tailing new inserts while old parts drop, so
--   the table stays bounded to a few seconds of frames.

CREATE TABLE doomhouse.rendered_frame_post_processed_1 (
    frame_id UInt64,
    pos_x Float32,
    pos_y Float32,
    image_data Array(UInt32),
    ts DateTime DEFAULT now()
)
ENGINE = MergeTree ORDER BY tuple()
TTL ts + INTERVAL 10 SECOND
SETTINGS ttl_only_drop_parts = 1, merge_with_ttl_timeout = 1;

CREATE TABLE doomhouse.rendered_frame_post_processed_2 (
    frame_id UInt64,
    pos_x Float32,
    pos_y Float32,
    image_data Array(UInt32),
    ts DateTime DEFAULT now()
)
ENGINE = MergeTree ORDER BY tuple()
TTL ts + INTERVAL 10 SECOND
SETTINGS ttl_only_drop_parts = 1, merge_with_ttl_timeout = 1;

CREATE TABLE doomhouse.rendered_frame_post_processed_3 (
    frame_id UInt64,
    pos_x Float32,
    pos_y Float32,
    image_data Array(UInt32),
    ts DateTime DEFAULT now()
)
ENGINE = MergeTree ORDER BY tuple()
TTL ts + INTERVAL 10 SECOND
SETTINGS ttl_only_drop_parts = 1, merge_with_ttl_timeout = 1;

CREATE TABLE doomhouse.rendered_frame_post_processed_4 (
    frame_id UInt64,
    pos_x Float32,
    pos_y Float32,
    image_data Array(UInt32),
    ts DateTime DEFAULT now()
)
ENGINE = MergeTree ORDER BY tuple()
TTL ts + INTERVAL 10 SECOND
SETTINGS ttl_only_drop_parts = 1, merge_with_ttl_timeout = 1;
