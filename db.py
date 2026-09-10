"""
SQLite database layer για το CreatorScan.
Αποθηκεύει creators και scan jobs.
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "creators.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Δημιουργεί τους πίνακες αν δεν υπάρχουν."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS creators (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
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
                niches          TEXT,       -- JSON array
                language        TEXT,
                country         TEXT,
                bio             TEXT,
                profile_url     TEXT,
                avatar_url      TEXT,
                email           TEXT,
                has_email       INTEGER DEFAULT 0,
                tags            TEXT,       -- JSON array
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now')),
                UNIQUE(platform, platform_id)
            );

            CREATE TABLE IF NOT EXISTS scan_jobs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                query           TEXT,
                platform        TEXT,
                niche           TEXT,
                min_followers   INTEGER,
                max_followers   INTEGER,
                creators_found  INTEGER DEFAULT 0,
                status          TEXT DEFAULT 'running',
                started_at      TEXT DEFAULT (datetime('now')),
                completed_at    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_platform    ON creators(platform);
            CREATE INDEX IF NOT EXISTS idx_niche       ON creators(niche);
            CREATE INDEX IF NOT EXISTS idx_followers   ON creators(followers);
            CREATE INDEX IF NOT EXISTS idx_has_email   ON creators(has_email);

            CREATE TABLE IF NOT EXISTS api_keys (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                key           TEXT    UNIQUE NOT NULL,
                name          TEXT    NOT NULL,
                tier          TEXT    DEFAULT 'free',
                calls_today   INTEGER DEFAULT 0,
                calls_total   INTEGER DEFAULT 0,
                limit_per_day INTEGER DEFAULT 100,
                active        INTEGER DEFAULT 1,
                created_at    TEXT    DEFAULT (datetime('now')),
                last_used_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS api_usage (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                key        TEXT NOT NULL,
                endpoint   TEXT,
                params     TEXT,
                results    INTEGER,
                ts         TEXT DEFAULT (datetime('now'))
            );
        """)


def upsert_creator(data: dict) -> bool:
    """
    Insert or update ένα creator.
    Επιστρέφει True αν ήταν νέος, False αν update.
    """
    sql = """
        INSERT INTO creators
            (platform, platform_id, username, display_name, followers, following,
             posts_count, avg_views, engagement_rate, niche, niches, language,
             country, bio, profile_url, avatar_url, email, has_email, tags, updated_at)
        VALUES
            (:platform, :platform_id, :username, :display_name, :followers, :following,
             :posts_count, :avg_views, :engagement_rate, :niche, :niches, :language,
             :country, :bio, :profile_url, :avatar_url, :email, :has_email, :tags,
             datetime('now'))
        ON CONFLICT(platform, platform_id) DO UPDATE SET
            display_name    = excluded.display_name,
            followers       = excluded.followers,
            following       = excluded.following,
            posts_count     = excluded.posts_count,
            avg_views       = excluded.avg_views,
            engagement_rate = excluded.engagement_rate,
            niche           = excluded.niche,
            niches          = excluded.niches,
            bio             = excluded.bio,
            email           = excluded.email,
            has_email       = excluded.has_email,
            tags            = excluded.tags,
            updated_at      = datetime('now')
    """
    # Serialize lists to JSON
    if isinstance(data.get("niches"), list):
        data["niches"] = json.dumps(data["niches"])
    if isinstance(data.get("tags"), list):
        data["tags"] = json.dumps(data["tags"])

    with get_connection() as conn:
        before = conn.execute(
            "SELECT id FROM creators WHERE platform=? AND platform_id=?",
            (data["platform"], data["platform_id"])
        ).fetchone()
        conn.execute(sql, data)
        is_new = before is None
    return is_new


def _build_conditions(
    platform=None, niche=None, min_followers=2000, max_followers=100_000,
    has_email=None, language=None, search=None,
):
    conditions = ["followers BETWEEN ? AND ?"]
    params: list = [min_followers, max_followers]
    if platform:
        conditions.append("platform = ?");  params.append(platform)
    if niche:
        conditions.append("niche = ?");     params.append(niche)
    if has_email is not None:
        conditions.append("has_email = ?"); params.append(1 if has_email else 0)
    if language:
        conditions.append("LOWER(language) = LOWER(?)"); params.append(language)
    if search:
        conditions.append(
            "(LOWER(display_name) LIKE ? OR LOWER(username) LIKE ? OR LOWER(bio) LIKE ?)"
        )
        q = f"%{search.lower()}%"
        params += [q, q, q]
    return conditions, params


def query_creators(
    platform: str | None = None,
    niche: str | None = None,
    min_followers: int = 2000,
    max_followers: int = 100_000,
    has_email: bool | None = None,
    language: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Query creators με φίλτρα."""
    conditions, params = _build_conditions(
        platform, niche, min_followers, max_followers, has_email, language, search
    )
    where = " AND ".join(conditions)
    params += [limit, offset]
    sql = f"SELECT * FROM creators WHERE {where} ORDER BY followers DESC LIMIT ? OFFSET ?"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def count_creators(
    platform=None, niche=None, min_followers=2000, max_followers=100_000,
    has_email=None, language=None, search=None,
) -> int:
    conditions, params = _build_conditions(
        platform, niche, min_followers, max_followers, has_email, language, search
    )
    where = " AND ".join(conditions)
    with get_connection() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM creators WHERE {where}", params).fetchone()[0]


def get_stats() -> dict:
    """Συνολικά στατιστικά της DB."""
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM creators").fetchone()[0]
        by_platform = conn.execute(
            "SELECT platform, COUNT(*) as cnt FROM creators GROUP BY platform"
        ).fetchall()
        by_niche = conn.execute(
            "SELECT niche, COUNT(*) as cnt FROM creators GROUP BY niche ORDER BY cnt DESC LIMIT 15"
        ).fetchall()
        with_email = conn.execute(
            "SELECT COUNT(*) FROM creators WHERE has_email=1"
        ).fetchone()[0]
    return {
        "total": total,
        "with_email": with_email,
        "by_platform": {r["platform"]: r["cnt"] for r in by_platform},
        "by_niche": {r["niche"]: r["cnt"] for r in by_niche},
    }


def export_csv(filepath: str, **filter_kwargs):
    """Εξάγει results σε CSV."""
    import csv
    creators = query_creators(**filter_kwargs, limit=100_000)
    if not creators:
        return 0
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=creators[0].keys())
        writer.writeheader()
        writer.writerows(creators)
    return len(creators)


# ── API Key Management ────────────────────────────────────────────────────────

def create_api_key(name: str, tier: str = "free") -> dict:
    """Δημιουργεί νέο API key και το επιστρέφει."""
    import secrets
    tiers = {"free": 100, "pro": 5000, "unlimited": 999_999}
    limit = tiers.get(tier, 100)
    key = f"cs_{secrets.token_urlsafe(32)}"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO api_keys (key, name, tier, limit_per_day) VALUES (?, ?, ?, ?)",
            (key, name, tier, limit),
        )
    return get_api_key(key)


def get_api_key(key: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM api_keys WHERE key=?", (key,)).fetchone()
    return dict(row) if row else None


def list_api_keys() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def revoke_api_key(key: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute("UPDATE api_keys SET active=0 WHERE key=?", (key,))
    return cur.rowcount > 0


def check_and_increment(key: str) -> tuple[bool, dict | None]:
    """
    Ελέγχει αν το key είναι valid και δεν έχει ξεπεράσει το limit.
    Αυξάνει τους μετρητές αν ΟΚ.
    Επιστρέφει (allowed: bool, key_info: dict | None).
    """
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key=? AND active=1", (key,)
        ).fetchone()
        if not row:
            return False, None
        info = dict(row)

        # Reset daily counter αν είναι νέα μέρα
        if info.get("last_used_at") and info["last_used_at"][:10] != today:
            conn.execute(
                "UPDATE api_keys SET calls_today=0 WHERE key=?", (key,)
            )
            info["calls_today"] = 0

        if info["calls_today"] >= info["limit_per_day"]:
            return False, info

        conn.execute(
            """UPDATE api_keys SET
               calls_today  = calls_today + 1,
               calls_total  = calls_total + 1,
               last_used_at = datetime('now')
               WHERE key=?""",
            (key,),
        )
    return True, info


def log_api_usage(key: str, endpoint: str, params: str, results: int):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO api_usage (key, endpoint, params, results) VALUES (?,?,?,?)",
            (key, endpoint, params, results),
        )


def get_key_usage(key: str, days: int = 7) -> list[dict]:
    """Χρήση ανά ημέρα για το συγκεκριμένο key."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT date(ts) as day, COUNT(*) as calls, SUM(results) as total_results
               FROM api_usage WHERE key=?
               AND ts >= datetime('now', ?)
               GROUP BY day ORDER BY day DESC""",
            (key, f"-{days} days"),
        ).fetchall()
    return [dict(r) for r in rows]
