-- ECNU 小助手数据库结构（SQLite）
-- 时间统一存 UTC ISO8601 字符串；"day" 字段存用户时区的 YYYY-MM-DD。

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------------- 用户与会话 ----------------
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sso_subject   TEXT NOT NULL UNIQUE,
    sso_provider  TEXT NOT NULL DEFAULT 'dev',
    nickname      TEXT NOT NULL,
    avatar        TEXT NOT NULL DEFAULT 'preset:ocean',
    bio           TEXT NOT NULL DEFAULT '',
    major         TEXT NOT NULL DEFAULT '',
    department    TEXT NOT NULL DEFAULT '',
    grade         TEXT NOT NULL DEFAULT '',
    directions    TEXT NOT NULL DEFAULT '[]',
    courses       TEXT NOT NULL DEFAULT '[]',
    settings      TEXT NOT NULL DEFAULT '{}',
    role          TEXT NOT NULL DEFAULT 'user',
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    csrf       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip         TEXT NOT NULL DEFAULT '',
    ua         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS auth_states (
    state      TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- ---------------- 官网语料 ----------------
CREATE TABLE IF NOT EXISTS sites (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    key             TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT '其他',
    description     TEXT NOT NULL DEFAULT '',
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_crawled_at TEXT,
    doc_count       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id      INTEGER NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    url          TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    published_at TEXT,
    fetched_at   TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'text/html',
    sha256       TEXT NOT NULL,
    text         TEXT NOT NULL,
    char_count   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_documents_site ON documents(site_id);
CREATE INDEX IF NOT EXISTS idx_documents_fetched ON documents(fetched_at);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal     INTEGER NOT NULL DEFAULT 0,
    text        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);

CREATE TABLE IF NOT EXISTS crawl_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    site_ids     TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'running',
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    pages_ok     INTEGER NOT NULL DEFAULT 0,
    pages_failed INTEGER NOT NULL DEFAULT 0,
    detail       TEXT NOT NULL DEFAULT '{}'
);

-- ---------------- 待办与计划 ----------------
CREATE TABLE IF NOT EXISTS reminders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    notes         TEXT NOT NULL DEFAULT '',
    due_at        TEXT NOT NULL,
    recurrence    TEXT NOT NULL DEFAULT 'once',
    channels      TEXT NOT NULL DEFAULT '["inapp"]',
    done          INTEGER NOT NULL DEFAULT 0,
    completed_at  TEXT,
    created_at    TEXT NOT NULL,
    last_fired_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id, due_at);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(done, due_at);

CREATE TABLE IF NOT EXISTS reminder_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_id INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
    fired_at    TEXT NOT NULL,
    channel     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ok',
    detail      TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS plans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    category      TEXT NOT NULL DEFAULT 'custom',
    cadence       TEXT NOT NULL DEFAULT 'daily',
    weekdays      TEXT NOT NULL DEFAULT '[]',
    target_count  INTEGER NOT NULL DEFAULT 1,
    unit          TEXT NOT NULL DEFAULT '次',
    reminder_time TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plans_user ON plans(user_id, active);

CREATE TABLE IF NOT EXISTS plan_progress (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,
    done_count  INTEGER NOT NULL DEFAULT 0,
    completed   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL DEFAULT '',
    UNIQUE (plan_id, day)
);

CREATE TABLE IF NOT EXISTS plan_notices (
    plan_id INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    day     TEXT NOT NULL,
    PRIMARY KEY (plan_id, day)
);

CREATE TABLE IF NOT EXISTS vocab_reviews (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    word         TEXT NOT NULL,
    meaning      TEXT NOT NULL DEFAULT '',
    example      TEXT NOT NULL DEFAULT '',
    ease         REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 0,
    due_at       TEXT,
    lapses       INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (user_id, word)
);

CREATE TABLE IF NOT EXISTS vocab_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id      INTEGER REFERENCES plans(id) ON DELETE SET NULL,
    day          TEXT NOT NULL,
    items        TEXT NOT NULL DEFAULT '[]',
    status       TEXT NOT NULL DEFAULT 'active',
    score        INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    completed_at TEXT
);

-- ---------------- 论坛与社交 ----------------
CREATE TABLE IF NOT EXISTS posts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    author_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    tags       TEXT NOT NULL DEFAULT '[]',
    anonymous  INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'visible',
    moderation TEXT NOT NULL DEFAULT '{}',
    views      INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_status_created ON posts(status, created_at);
CREATE INDEX IF NOT EXISTS idx_posts_author ON posts(author_id);

CREATE TABLE IF NOT EXISTS post_likes (
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (post_id, user_id)
);

CREATE TABLE IF NOT EXISTS comments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    parent_id  INTEGER REFERENCES comments(id) ON DELETE CASCADE,
    body       TEXT NOT NULL,
    anonymous  INTEGER NOT NULL DEFAULT 0,
    status     TEXT NOT NULL DEFAULT 'visible',
    moderation TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id, created_at);

CREATE TABLE IF NOT EXISTS comment_likes (
    comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (comment_id, user_id)
);

CREATE TABLE IF NOT EXISTS bookmarks (
    post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (post_id, user_id)
);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    target_type TEXT NOT NULL,
    target_id   INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open',
    action      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    handled_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    handled_at  TEXT,
    UNIQUE (reporter_id, target_type, target_id)
);
CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status, created_at);

CREATE TABLE IF NOT EXISTS appeals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL,
    target_id   INTEGER NOT NULL,
    reason      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL,
    handled_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    handled_at  TEXT,
    reply       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_appeals_status ON appeals(status, created_at);

CREATE TABLE IF NOT EXISTS follows (
    follower_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    followee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (follower_id, followee_id)
);
CREATE INDEX IF NOT EXISTS idx_follows_followee ON follows(followee_id);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    recipient_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    body         TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    read_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_pair ON messages(sender_id, recipient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_recipient ON messages(recipient_id, read_at);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    read_at    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, read_at, created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action     TEXT NOT NULL,
    target     TEXT NOT NULL DEFAULT '',
    detail     TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_cache (
    key        TEXT PRIMARY KEY,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
