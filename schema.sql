-- =============================================================================
-- 记忆引擎 - 数据库 Schema
-- 存储后端：SQLite（单机）/ PostgreSQL（生产）
-- =============================================================================

-- =============================================================================
-- 第一层：Memory Tree — 外部数据的感知层（借鉴 OpenHuman）
-- 存储从飞书/数据库/文件系统自动同步的文档和结构化数据
-- =============================================================================

CREATE TABLE IF NOT EXISTS memory_tree_chunks (
    id TEXT PRIMARY KEY,                              -- UUID
    source TEXT NOT NULL,                             -- 数据来源: feishu:doc:xxx, postgres:table:yyy, file:/path
    source_type TEXT NOT NULL,                        -- doc | table | file | approval
    title TEXT,                                       -- 文档标题 / 表名 / 文件名
    content TEXT NOT NULL,                            -- 内容（Markdown 规范化后）
    content_hash TEXT NOT NULL,                       -- SHA256，用于去重
    chunk_index INTEGER DEFAULT 0,                    -- 分块序号
    parent_id TEXT,                                   -- 父节点（用于层级摘要树）
    summary TEXT,                                     -- 本块的摘要（LLM 生成）
    score FLOAT DEFAULT 0.0,                          -- 综合评分
    freshness_score FLOAT DEFAULT 1.0,                -- 新鲜度（指数衰减）
    retrieval_count INTEGER DEFAULT 0,                -- 被检索次数
    correction_count INTEGER DEFAULT 0,               -- 被用户纠正次数（负向因子）
    importance_score FLOAT DEFAULT 0.5,               -- 重要性（用户标记/实体密度）
    entity_count INTEGER DEFAULT 0,                   -- 关联的实体数量
    metadata JSON,                                    -- {author, created_at, updated_at, tags, ...}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    vector BLOB                                       -- 384维FAISS向量（all-MiniLM-L6-v2编码）
);

CREATE INDEX IF NOT EXISTS idx_mt_source ON memory_tree_chunks(source_type, source);
CREATE INDEX IF NOT EXISTS idx_mt_score ON memory_tree_chunks(score DESC);
CREATE INDEX IF NOT EXISTS idx_mt_parent ON memory_tree_chunks(parent_id);

-- =============================================================================
-- 第二层：偏好记忆 — 自动从对话中学习的规则层（借鉴 Mem0）
-- 存储字段映射、别名、日期规则、会计政策等
-- =============================================================================

CREATE TABLE IF NOT EXISTS preference_memory (
    id TEXT PRIMARY KEY,                              -- UUID
    category TEXT NOT NULL,                           -- field_alias | date_rule | naming | policy | format
    condition TEXT NOT NULL,                          -- 触发条件（自然语言描述）
    rule TEXT NOT NULL,                               -- 规则内容（自然语言 + 可选 SQL/代码片段）
    rule_hash TEXT NOT NULL,                          -- SHA256(condition + rule)，去重
    source TEXT,                                      -- 来源：对话ID / 用户手动添加
    source_type TEXT DEFAULT 'manual',                -- manual | extracted | corrected
    confidence FLOAT DEFAULT 0.8,                     -- 置信度 0-1
    correction_count INTEGER DEFAULT 0,               -- 被纠正次数（越多越可信）
    last_corrected_by TEXT,                           -- 最后纠正者
    scope TEXT DEFAULT 'personal',                    -- personal | team:财务部 | team:* | organization
    department TEXT,                                  -- 所属部门
    is_active INTEGER DEFAULT 1,                      -- 0=已弃用 1=活跃
    metadata JSON,                                    -- 扩展字段
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pm_category ON preference_memory(category);
CREATE INDEX IF NOT EXISTS idx_pm_scope ON preference_memory(scope);
CREATE INDEX IF NOT EXISTS idx_pm_active ON preference_memory(is_active);
CREATE UNIQUE INDEX IF NOT EXISTS idx_pm_hash ON preference_memory(rule_hash);

-- =============================================================================
-- 第三层：纠错记忆 — Agent 的"不要再犯"系统（本方案独有）
-- 存储错误模式、纠正记录、预防规则
-- =============================================================================

CREATE TABLE IF NOT EXISTS error_memory (
    id TEXT PRIMARY KEY,                              -- UUID
    task_type TEXT NOT NULL,                          -- 任务类型: financial_report | data_query | file_archive | ...
    error_category TEXT NOT NULL,                     -- field_selection | logic_error | scope_error | omission
    mistake_description TEXT NOT NULL,                -- 犯了什么错（自然语言）
    correction TEXT NOT NULL,                         -- 应该怎么做（自然语言）
    prevention_rule TEXT,                             -- 预防规则（可供 Agent 执行前检查的条件）
    conversation_id TEXT,                             -- 来源对话
    severity TEXT DEFAULT 'minor',                    -- minor | major | critical
    occurrence_count INTEGER DEFAULT 1,               -- 同一错误出现次数
    last_occurrence TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_resolved INTEGER DEFAULT 0,                    -- 0=活跃 1=已解决（升级为偏好规则）
    resolved_to TEXT,                                 -- 升级为哪条偏好记忆的 ID
    metadata JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_em_task ON error_memory(task_type);
CREATE INDEX IF NOT EXISTS idx_em_active ON error_memory(is_resolved);
CREATE INDEX IF NOT EXISTS idx_em_severity ON error_memory(severity);

-- =============================================================================
-- 第四层：知识图谱 — 部门级共享智能（借鉴 Zep）
-- 存储实体和关系，支持跨部门知识共享
-- =============================================================================

CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,                              -- UUID
    type TEXT NOT NULL,                               -- person | department | client | policy | document | field | project
    name TEXT NOT NULL,                               -- 规范名称
    aliases JSON,                                     -- ["别名1", "别名2", ...]
    properties JSON,                                  -- {"信用期": "45天", "结算货币": "CNY", ...}
    scope TEXT DEFAULT 'personal',                    -- personal | team | organization
    department TEXT,                                  -- 所属部门
    created_by TEXT,                                  -- 创建者
    metadata JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,                              -- UUID
    source_id TEXT NOT NULL REFERENCES entities(id),
    target_id TEXT NOT NULL REFERENCES entities(id),
    relation TEXT NOT NULL,                           -- belongs_to | manages | alias_of | depends_on | owns | approves
    properties JSON,                                  -- {"source": "CFO确认于2026-04-10", "confidence": 0.95}
    scope TEXT DEFAULT 'personal',                    -- personal | team | organization
    department TEXT,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ent_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_ent_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_ent_scope ON entities(scope);
CREATE INDEX IF NOT EXISTS idx_rel_source ON relationships(source_id);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relationships(target_id);
CREATE INDEX IF NOT EXISTS idx_rel_relation ON relationships(relation);
CREATE INDEX IF NOT EXISTS idx_rel_scope ON relationships(scope);

-- =============================================================================
-- 元数据表：同步状态跟踪
-- =============================================================================

CREATE TABLE IF NOT EXISTS sync_status (
    source TEXT PRIMARY KEY,                          -- 数据源标识
    last_sync_at TIMESTAMP,                           -- 上次同步时间
    last_sync_hash TEXT,                              -- 上次同步的内容哈希（增量判断）
    items_synced INTEGER DEFAULT 0,                   -- 本次同步条目数
    status TEXT DEFAULT 'pending',                    -- pending | running | success | failed
    error_message TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
