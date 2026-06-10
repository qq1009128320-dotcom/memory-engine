-- =============================================================================
-- 记忆引擎 - 数据库 Schema
-- 存储后端：SQLite（单机）/ PostgreSQL（生产）
-- =============================================================================

-- =============================================================================
-- 第一层：Memory Tree — 外部数据的感知层
-- =============================================================================

CREATE TABLE IF NOT EXISTS memory_tree_chunks (
    id             TEXT PRIMARY KEY,
    source         TEXT NOT NULL,
    source_type    TEXT NOT NULL,
    title          TEXT,
    content        TEXT NOT NULL,
    content_hash   TEXT NOT NULL,
    chunk_index    INTEGER DEFAULT 0,
    parent_id      TEXT,
    summary        TEXT,
    score          FLOAT DEFAULT 0.0,
    freshness_score FLOAT DEFAULT 1.0,
    retrieval_count INTEGER DEFAULT 0,
    ingest_count   INTEGER DEFAULT 1,
    correction_count INTEGER DEFAULT 0,
    importance_score FLOAT DEFAULT 0.5,
    entity_count   INTEGER DEFAULT 0,
    faiss_id       INTEGER DEFAULT -1,
    is_indexed     INTEGER DEFAULT 0,   -- P0-1: FAISS 索引同步标记，1=已索引，0=待索引
    metadata       JSON,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    vector         BLOB
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mt_hash   ON memory_tree_chunks(content_hash);
CREATE INDEX       IF NOT EXISTS idx_mt_source  ON memory_tree_chunks(source_type, source);
CREATE INDEX       IF NOT EXISTS idx_mt_score   ON memory_tree_chunks(score DESC);
CREATE INDEX       IF NOT EXISTS idx_mt_parent  ON memory_tree_chunks(parent_id);
CREATE INDEX       IF NOT EXISTS idx_mt_faissid ON memory_tree_chunks(faiss_id);
CREATE INDEX IF NOT EXISTS idx_mt_created ON memory_tree_chunks(created_at);
CREATE INDEX IF NOT EXISTS idx_mt_updated ON memory_tree_chunks(updated_at);

-- =============================================================================
-- 第二层：偏好记忆
-- =============================================================================

CREATE TABLE IF NOT EXISTS preference_memory (
    id               TEXT PRIMARY KEY,
    category         TEXT NOT NULL,
    condition        TEXT NOT NULL,
    rule             TEXT NOT NULL,
    rule_hash        TEXT NOT NULL,
    source           TEXT,
    source_type      TEXT DEFAULT 'manual',
    confidence       FLOAT DEFAULT 0.8,
    correction_count INTEGER DEFAULT 0,
    last_corrected_by TEXT,
    scope            TEXT DEFAULT 'personal',
    department       TEXT,
    is_active        INTEGER DEFAULT 1,
    metadata         JSON,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX        IF NOT EXISTS idx_pm_category ON preference_memory(category);
CREATE INDEX        IF NOT EXISTS idx_pm_scope    ON preference_memory(scope);
CREATE INDEX        IF NOT EXISTS idx_pm_active   ON preference_memory(is_active);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pm_hash     ON preference_memory(rule_hash);
CREATE INDEX IF NOT EXISTS idx_pm_created ON preference_memory(created_at);
CREATE INDEX IF NOT EXISTS idx_pm_updated ON preference_memory(updated_at);

-- =============================================================================
-- 第三层：纠错记忆
-- =============================================================================

CREATE TABLE IF NOT EXISTS error_memory (
    id                   TEXT PRIMARY KEY,
    task_type            TEXT NOT NULL,
    error_category       TEXT NOT NULL,
    mistake_description  TEXT NOT NULL,
    correction           TEXT NOT NULL,
    prevention_rule      TEXT,
    conversation_id      TEXT,
    severity             TEXT DEFAULT 'minor',
    occurrence_count     INTEGER DEFAULT 1,
    last_occurrence      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_resolved          INTEGER DEFAULT 0,
    resolved_to          TEXT,
    metadata             JSON,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_em_task     ON error_memory(task_type);
CREATE INDEX IF NOT EXISTS idx_em_active   ON error_memory(is_resolved);
CREATE INDEX IF NOT EXISTS idx_em_severity ON error_memory(severity);
CREATE INDEX IF NOT EXISTS idx_em_created ON error_memory(created_at);
CREATE INDEX IF NOT EXISTS idx_em_updated ON error_memory(updated_at);

-- =============================================================================
-- 第四层：知识图谱
-- =============================================================================

CREATE TABLE IF NOT EXISTS entities (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    name       TEXT NOT NULL,
    aliases    JSON,
    properties JSON,
    scope      TEXT DEFAULT 'personal',
    department TEXT,
    created_by TEXT,
    metadata   JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ent_type  ON entities(type);
CREATE INDEX IF NOT EXISTS idx_ent_name  ON entities(name);
CREATE INDEX IF NOT EXISTS idx_ent_scope ON entities(scope);
CREATE INDEX IF NOT EXISTS idx_ent_created ON entities(created_at);
CREATE INDEX IF NOT EXISTS idx_ent_updated ON entities(updated_at);

CREATE TABLE IF NOT EXISTS relationships (
    id         TEXT PRIMARY KEY,
    source_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_id  TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation   TEXT NOT NULL,
    properties JSON,
    scope      TEXT DEFAULT 'personal',
    department TEXT,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rel_source   ON relationships(source_id);
CREATE INDEX IF NOT EXISTS idx_rel_target   ON relationships(target_id);
CREATE INDEX IF NOT EXISTS idx_rel_relation ON relationships(relation);
CREATE INDEX IF NOT EXISTS idx_rel_scope    ON relationships(scope);
CREATE INDEX IF NOT EXISTS idx_rel_created  ON relationships(created_at);

-- =============================================================================
-- 元数据：同步状态跟踪
-- =============================================================================

CREATE TABLE IF NOT EXISTS sync_status (
    source         TEXT PRIMARY KEY,
    last_sync_at   TIMESTAMP,
    last_sync_hash TEXT,
    items_synced   INTEGER DEFAULT 0,
    status         TEXT DEFAULT 'pending',
    error_message  TEXT,
    updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- P2-⑩ 修复: 为 sync_status 添加查询索引
CREATE INDEX IF NOT EXISTS idx_sync_status ON sync_status(status, last_sync_at);
