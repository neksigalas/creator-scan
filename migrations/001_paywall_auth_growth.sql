-- ============================================================
-- CreatorScan — Migration 001
-- Adds: license keys, creator snapshots, auth_score column
-- Run in Supabase SQL Editor
-- ============================================================

-- ── License keys (paywall) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS cs_license_keys (
  id           BIGSERIAL PRIMARY KEY,
  key          TEXT UNIQUE NOT NULL,
  email        TEXT,
  tier         TEXT DEFAULT 'starter',   -- starter | pro | agency
  active       BOOLEAN DEFAULT TRUE,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  expires_at   TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ,
  usage_count  INT DEFAULT 0,
  metadata     JSONB
);

CREATE INDEX IF NOT EXISTS idx_cs_license_key    ON cs_license_keys(key);
CREATE INDEX IF NOT EXISTS idx_cs_license_active ON cs_license_keys(active);

-- ── Creator follower snapshots (growth tracking) ─────────────
CREATE TABLE IF NOT EXISTS cs_creator_snapshots (
  id          BIGSERIAL PRIMARY KEY,
  creator_id  BIGINT NOT NULL REFERENCES cs_creators(id) ON DELETE CASCADE,
  followers   BIGINT NOT NULL,
  date        DATE NOT NULL DEFAULT CURRENT_DATE,
  UNIQUE(creator_id, date)
);

CREATE INDEX IF NOT EXISTS idx_cs_snaps_creator ON cs_creator_snapshots(creator_id, date DESC);

-- ── Auth score column on creators ────────────────────────────
ALTER TABLE cs_creators ADD COLUMN IF NOT EXISTS auth_score INT;
ALTER TABLE cs_creators ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'scan';

-- ── Join requests (self-registered creators) ─────────────────
CREATE TABLE IF NOT EXISTS cs_join_requests (
  id           BIGSERIAL PRIMARY KEY,
  platform     TEXT NOT NULL,
  username     TEXT NOT NULL,
  profile_url  TEXT,
  niche        TEXT,
  followers    BIGINT,
  contact_email TEXT,
  bio          TEXT,
  status       TEXT DEFAULT 'pending',   -- pending | approved | rejected
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  reviewed_at  TIMESTAMPTZ
);
