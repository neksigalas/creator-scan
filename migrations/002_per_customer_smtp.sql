-- ============================================================
-- CreatorScan — Migration 002
-- Per-customer SMTP + daily send log
-- Run in Supabase SQL Editor
-- ============================================================

-- ── Per-license SMTP credentials (encrypted password at rest) ─
CREATE TABLE IF NOT EXISTS cs_license_smtp (
  license_key   TEXT PRIMARY KEY REFERENCES cs_license_keys(key) ON DELETE CASCADE,
  smtp_host     TEXT NOT NULL,
  smtp_port     INT  NOT NULL DEFAULT 587,
  smtp_user     TEXT NOT NULL,
  smtp_pass_enc TEXT NOT NULL,  -- Fernet-encrypted
  display_name  TEXT,           -- shown as "Name <email>" sender
  daily_cap     INT  NOT NULL DEFAULT 50,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Readable only by service role; anon key cannot select
ALTER TABLE cs_license_smtp ENABLE ROW LEVEL SECURITY;
CREATE POLICY cs_license_smtp_service_only
  ON cs_license_smtp
  USING (auth.role() = 'service_role');

-- ── Daily send log (audit trail + cap enforcement) ───────────
CREATE TABLE IF NOT EXISTS cs_email_send_log (
  id             BIGSERIAL PRIMARY KEY,
  license_key    TEXT    NOT NULL,
  recipient_count INT    NOT NULL,
  dry_run        BOOLEAN NOT NULL DEFAULT FALSE,
  sent_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cs_send_log_key_date
  ON cs_email_send_log(license_key, sent_at);
