-- CreatorScan tables (prefix cs_ για coexistence με dental-case-preflight)
-- Run once in Supabase SQL editor: https://supabase.com/dashboard/project/vbmzmhodinrhqgtpjbtg/sql

-- ── Creators ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cs_creators (
    id              BIGSERIAL PRIMARY KEY,
    platform        TEXT    NOT NULL,
    platform_id     TEXT    NOT NULL,
    username        TEXT    NOT NULL,
    display_name    TEXT,
    followers       INTEGER,
    following       INTEGER,
    posts_count     INTEGER,
    avg_views       INTEGER,
    engagement_rate REAL,
    niche           TEXT,
    niches          TEXT,
    language        TEXT,
    country         TEXT,
    bio             TEXT,
    profile_url     TEXT,
    avatar_url      TEXT,
    email           TEXT,
    has_email       INTEGER DEFAULT 0,
    tags            TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(platform, platform_id)
);

CREATE INDEX IF NOT EXISTS idx_cs_platform  ON cs_creators(platform);
CREATE INDEX IF NOT EXISTS idx_cs_niche     ON cs_creators(niche);
CREATE INDEX IF NOT EXISTS idx_cs_followers ON cs_creators(followers);
CREATE INDEX IF NOT EXISTS idx_cs_has_email ON cs_creators(has_email);

-- ── API Keys ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cs_api_keys (
    id            BIGSERIAL PRIMARY KEY,
    key           TEXT    UNIQUE NOT NULL,
    name          TEXT    NOT NULL,
    tier          TEXT    DEFAULT 'free',
    calls_today   INTEGER DEFAULT 0,
    calls_total   INTEGER DEFAULT 0,
    limit_per_day INTEGER DEFAULT 100,
    active        BOOLEAN DEFAULT TRUE,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    last_used_at  TIMESTAMPTZ
);

-- ── API Usage ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cs_api_usage (
    id       BIGSERIAL PRIMARY KEY,
    key      TEXT NOT NULL,
    endpoint TEXT,
    params   TEXT,
    results  INTEGER,
    ts       TIMESTAMPTZ DEFAULT NOW()
);

-- ── RLS (Row Level Security) — DISABLED για service_role access ───────────────
-- Service role bypasses RLS automatically, so no policies needed.
-- If you want anon access later, add policies here.

ALTER TABLE cs_creators  DISABLE ROW LEVEL SECURITY;
ALTER TABLE cs_api_keys  DISABLE ROW LEVEL SECURITY;
ALTER TABLE cs_api_usage DISABLE ROW LEVEL SECURITY;
