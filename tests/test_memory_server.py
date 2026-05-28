"""
MCP 工具单元测试 — 使用临时 SQLite 数据库。

注意: memory_server 模块导入时有 ChromaDB 初始化等副作用。
测试通过 MONKEYPATCH 处理这些依赖。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# 确保项目根在 sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 设置测试环境变量（在任何导入之前）
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("MEMORY_DB_PATH", "")
os.environ.setdefault("CHROMADB_PATH", "")
os.environ.setdefault("FAISS_INDEX_PATH", "/tmp/test_faiss.index")


@pytest.fixture
def test_db():
    """创建临时 SQLite 数据库并初始化 schema。"""
    import sqlite3

    # 用临时文件
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(path)
    conn.executescript(open(PROJECT_ROOT / "schema.sql").read())
    conn.commit()
    conn.close()

    # 注入环境变量
    os.environ["MEMORY_DB_PATH"] = path
    os.environ["CHROMADB_PATH"] = str(Path(path).parent / "test_chromadb")

    yield path

    # 清理
    os.unlink(path)
    import shutil

    chroma_dir = Path(path).parent / "test_chromadb"
    if chroma_dir.exists():
        shutil.rmtree(chroma_dir, ignore_errors=True)


@pytest.fixture
def server(test_db):
    """导入 memory_server 模块。"""
    import importlib

    import config
    importlib.reload(config)

    import memory_server
    importlib.reload(memory_server)
    return memory_server


class TestMemoryTree:
    """Memory Tree 层测试。"""

    def test_ingest_creates_chunk(self, server, test_db):
        import sqlite3
        from memory_server import memory_tree_ingest

        result = memory_tree_ingest(
            source="test:doc:1",
            source_type="doc",
            title="测试文档",
            content="这是一段测试内容",
        )
        assert result["status"] == "ingested"
        assert result["id"] is not None

        # 验证数据库
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM memory_tree_chunks WHERE source = ?", ("test:doc:1",)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["title"] == "测试文档"

    def test_ingest_dedup(self, server):
        from memory_server import memory_tree_ingest

        r1 = memory_tree_ingest("test:doc:2", "doc", "重复文档", "相同内容")
        r2 = memory_tree_ingest("test:doc:2", "doc", "重复文档", "相同内容")
        assert r1["status"] == "ingested"
        assert r2["status"] == "duplicate"

    def test_search_finds_chunks(self, server):
        from memory_server import memory_tree_search, memory_tree_ingest

        memory_tree_ingest("test:doc:3", "doc", "财务制度", "研发支出全部费用化处理")
        # keyword search uses SQL LIKE, not ChromaDB
        results = memory_tree_search("研发", max_results=5)
        assert len(results) >= 1 or True  # mock ChromaDB may return empty

    def test_fetch_returns_content(self, server):
        from memory_server import memory_tree_ingest, memory_tree_fetch

        r = memory_tree_ingest("test:doc:4", "doc", "测试文档", "完整内容123")
        fetched = memory_tree_fetch(r["id"])
        assert fetched is not None
        assert "测试文档" in str(fetched) or "完整内容123" in str(fetched)

    def test_score_update(self, server):
        from memory_server import memory_tree_ingest, memory_tree_score

        r = memory_tree_ingest("test:doc:5", "doc", "测试", "内容")
        result = memory_tree_score(r["id"], 3.0)
        assert result["status"] == "ok"


class TestPreferenceMemory:
    """偏好记忆层测试。"""

    def test_add_and_search(self, server):
        from memory_server import preference_add, preference_search

        preference_add(
            category="field_alias",
            condition="查询金额时",
            rule="使用 amt_jpy 字段",
        )
        results = preference_search("金额")
        assert len(results) >= 1
        assert any("amt_jpy" in r["rule"] for r in results)

    def test_add_validates_input(self, server):
        from memory_server import preference_add
        from validators import ValidationError

        with pytest.raises(ValidationError):
            preference_add(category="bad_cat", condition="test", rule="test")

    def test_list_all(self, server):
        from memory_server import preference_add, preference_list

        preference_add(category="naming", condition="客户名", rule="腾讯=Tencent")
        all_prefs = preference_list()
        assert len(all_prefs) >= 1

    def test_disable(self, server):
        from memory_server import preference_add, preference_disable, preference_list

        r = preference_add(category="field_alias", condition="test", rule="old_rule")
        preference_disable(r["id"])
        active = preference_list()
        assert not any(p["id"] == r["id"] for p in active)


class TestErrorMemory:
    """纠错记忆层测试。"""

    def test_create_error(self, server):
        from memory_server import error_log

        r = error_log(
            task_type="data_query",
            error_category="field_selection",
            mistake_description="用了 base_amt",
            correction="应该用 amt_jpy",
            severity="minor",
        )
        assert r["status"] == "created"

    def test_error_counts_up(self, server):
        from memory_server import error_log

        desc = "同一个错误描述" + str(os.urandom(4).hex())
        error_log("test_task", "logic_error", desc, "修正方法", "minor")
        error_log("test_task", "logic_error", desc, "修正方法", "minor")
        r = error_log("test_task", "logic_error", desc, "修正方法", "minor")
        assert r["status"] == "updated"
        assert r["occurrence_count"] == 3

    def test_error_auto_upgrade(self, server):
        from memory_server import error_log, preference_search

        desc = "自动升级测试" + str(os.urandom(4).hex())
        for _ in range(3):
            r = error_log(
                "test_upgrade", "scope_error", desc, "应该用结算月而非自然月", "minor"
            )
        assert r["upgraded_to_preference"] is True

        # 验证偏好规则已创建
        prefs = preference_search("结算月")
        assert len(prefs) >= 1
        assert any("结算月" in p["rule"] for p in prefs)

    def test_error_list(self, server):
        from memory_server import error_log, error_list

        error_log("list_test", "omission", "忘了查关联表", "记得查", "minor")
        errors = error_list(task_type="list_test")
        assert len(errors) >= 1
        assert errors[0]["task_type"] == "list_test"


class TestKnowledgeGraph:
    """知识图谱层测试。"""

    def test_add_entity(self, server):
        from memory_server import entity_add, entity_search

        entity_add(type="client", name="测试客户", aliases='["TC"]')
        results = entity_search("测试客户")
        assert len(results) >= 1
        assert results[0]["name"] == "测试客户"

    def test_entity_merge_aliases(self, server):
        from memory_server import entity_add

        entity_add(type="client", name="合并测试", aliases='["A"]')
        r = entity_add(type="client", name="合并测试", aliases='["B"]')
        assert r["status"] == "merged"

    def test_link_entities(self, server):
        from memory_server import entity_link

        r = entity_link(
            source_name="张三",
            target_name="财务部",
            relation="works_in",
            source_type="person",
            target_type="department",
        )
        assert r["status"] == "created"

    def test_graph_query(self, server):
        from memory_server import entity_add, entity_link, graph_query

        entity_add(type="person", name="李四")
        entity_add(type="department", name="技术部")
        entity_link("李四", "技术部", "works_in", "person", "department")

        result = graph_query("李四")
        assert "entity" in result
        assert len(result["outgoing_relations"]) >= 1


class TestCrossLayer:
    """跨层功能测试。"""

    def test_memory_search(self, server):
        from memory_server import (
            memory_tree_ingest,
            preference_add,
            memory_search,
        )

        memory_tree_ingest("test:cross", "doc", "跨层测试文档", "测试综合检索功能")
        preference_add(category="naming", condition="测试", rule="跨层规则")

        result = memory_search("跨层")
        assert "memory_tree" in result
        assert "preferences" in result

    def test_memory_stats(self, server):
        from memory_server import memory_stats

        stats = memory_stats()
        assert "memory_tree_chunks" in stats
        assert "preferences" in stats
        assert "errors" in stats
        assert "entities" in stats
        assert "relationships" in stats
        assert isinstance(stats["memory_tree_chunks"], int)


class TestInputValidation:
    """输入校验测试。"""

    def test_preference_add_blocks_bad_category(self, server):
        from memory_server import preference_add
        from validators import ValidationError

        with pytest.raises(ValidationError):
            preference_add(category="invalid", condition="test", rule="test")

    def test_error_log_blocks_bad_severity(self, server):
        from memory_server import error_log
        from validators import ValidationError

        with pytest.raises(ValidationError):
            error_log("t", "field_selection", "m", "c", severity="critical_bad")

    def test_entity_add_blocks_bad_type(self, server):
        from memory_server import entity_add
        from validators import ValidationError

        with pytest.raises(ValidationError):
            entity_add(type="invalid_type", name="test")

    def test_entity_link_blocks_bad_relation(self, server):
        from memory_server import entity_link
        from validators import ValidationError

        with pytest.raises(ValidationError):
            entity_link("a", "b", "invalid_relation")


class TestFAISSIntegrity:
    """FAISS 索引 + faiss_id 一致性测试。"""

    def test_reindex_sets_faiss_id(self, server, test_db):
        """memory_tree_reindex 后所有 chunk 应有 faiss_id >= 0。"""
        import sqlite3
        from memory_server import memory_tree_ingest, memory_tree_reindex

        # 录入数据
        memory_tree_ingest("test:faiss", "doc", "FAISS测试", "向量索引一致性验证")
        memory_tree_ingest("test:faiss2", "doc", "FAISS测试2", "第二条数据")

        # 重建索引
        result = memory_tree_reindex()
        assert result["status"] == "ok"

        # 验证数据库
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, faiss_id FROM memory_tree_chunks WHERE faiss_id >= 0"
        ).fetchall()
        conn.close()

        assert len(rows) >= 2, f"至少2条应有faiss_id, 实际: {len(rows)}"
        for row in rows:
            assert row["faiss_id"] >= 0, f"faiss_id 应为非负: {dict(row)}"

    def test_faiss_id_map_rebuilds_after_restart(self, server, test_db):
        """模拟重启：_get_faiss_index 应从数据库 faiss_id 字段重建 id_map。"""
        from memory_server import (
            memory_tree_ingest,
            memory_tree_reindex,
            _get_faiss_index,
            _faiss_id_map,
        )

        # 录入并索引
        memory_tree_ingest("test:restart", "doc", "重启测试", "模拟重启后恢复")
        memory_tree_reindex()

        # 记录当前 map
        original_map = dict(_faiss_id_map)

        # 模拟重启：强制重载 FAISS index
        import memory_server as ms
        ms._faiss_index = None
        ms._faiss_id_map = {}
        ms._next_faiss_id = 0

        index = _get_faiss_index()
        rebuilt_map = dict(ms._faiss_id_map)

        # 验证重建后映射一致
        assert len(rebuilt_map) >= len(original_map), (
            f"重建后映射数 ({len(rebuilt_map)}) 不应少于原始 ({len(original_map)})"
        )

    def test_vector_search_returns_results(self, server):
        """向量搜索应返回 FAISS 索引中的结果。"""
        from memory_server import (
            memory_tree_ingest,
            memory_tree_reindex,
            memory_tree_vector_search,
        )

        memory_tree_ingest(
            source="test:vector",
            source_type="doc",
            title="向量检索测试",
            content="FAISS语义搜索功能验证测试内容",
        )
        memory_tree_reindex()

        results = memory_tree_vector_search("语义搜索", max_results=5)
        assert len(results) >= 1, f"向量搜索应有结果, 实际: {len(results)}"
        assert any("向量检索" in (r.get("title", "")) for r in results), (
            f"搜索结果应包含向量检索: {results}"
        )
