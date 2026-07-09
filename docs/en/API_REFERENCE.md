# API Reference

> All 22 MCP tools exposed by Memory Engine. Connect via MCP protocol (stdio or HTTP).

## Quick Reference

| Tool | Layer | Description |
|------|-------|-------------|
| `memory_tree_ingest` | L1 | Ingest data into memory tree (auto-embeds) |
| `memory_tree_vector_search` | L1 | Semantic vector search (recommended) |
| `memory_tree_search` | L1 | Keyword search |
| `memory_tree_fetch` | L1 | Get full content by ID |
| `memory_tree_score` | L1 | Adjust relevance score |
| `memory_tree_delete` | L1 | Delete a record |
| `memory_tree_reindex` | L1 | Rebuild FAISS index |
| `memory_tree_summary` | L1 | Hierarchical summary (L0/L1/L2) |
| `memory_search` | All | Cross-layer search (best for agents) |
| `memory_stats` | All | Memory system statistics |
| `memory_health` | All | Health check + operational metrics |
| `preference_add` | L2 | Add a preference/rule |
| `preference_search` | L2 | Search preference rules |
| `preference_list` | L2 | List all preferences |
| `preference_disable` | L2 | Disable a preference |
| `error_check` | L3 | Check for past errors before task |
| `error_log` | L3 | Log an error + user correction |
| `error_list` | L3 | List error records |
| `error_delete` | L3 | Delete an error record |
| `entity_add` | L4 | Add an entity to knowledge graph |
| `entity_search` | L4 | Search entities |
| `entity_link` | L4 | Link two entities with a relation |
| `graph_query` | L4 | Query full entity graph |

---

## Layer 1: Memory Tree

### `memory_tree_ingest`

Ingest data into the memory tree. Automatically generates embeddings via FAISS.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `source` | string | ✅ | Source identifier (e.g., "feishu/doc_123") |
| `title` | string | ✅ | Title of the content |
| `content` | string | ✅ | The content to store |
| `source_type` | string | ❌ | Category tag (default: "manual") |
| `parent_id` | string | ❌ | Parent node ID for hierarchy |
| `metadata` | object | ❌ | Arbitrary JSON metadata |
| `generate_summary` | boolean | ❌ | Auto-generate summary (default: false) |

**Example:**
```json
{
    "source": "hr_policy_001",
    "title": "Employee Leave Policy 2026",
    "content": "All employees are entitled to 15 days of annual leave...",
    "source_type": "policy",
    "metadata": {"department": "HR", "version": "2.1"}
}
```

### `memory_tree_vector_search`

Semantic vector search using FAISS. Preferred over keyword search.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | ✅ | Natural language query |
| `max_results` | integer | ❌ | Max results (default: 10) |
| `source_type` | string | ❌ | Filter by source type |

**Returns:** Ranked results sorted by cosine similarity.

### `memory_tree_search`

Keyword search (LIKE-based fallback). Use when vector search returns poor results.

**Parameters:** Same as `memory_tree_vector_search`.

### `memory_tree_fetch`

Get the full content of a memory tree entry by ID.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Memory tree entry ID |

### `memory_tree_score`

Adjust the relevance score of an entry. Positive to promote, negative to demote.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Entry ID |
| `delta` | number | ✅ | Score change (e.g., +1.0, -0.5) |

### `memory_tree_delete`

Delete an entry from the memory tree and its FAISS index.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Entry ID to delete |

### `memory_tree_reindex`

Rebuild the FAISS index from scratch. Use after switching embedding models or if index is corrupted.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `async_mode` | boolean | ❌ | Run in background (default: false) |
| `force` | boolean | ❌ | Force reindex even if clean (default: false) |

**Returns:** `task_id` if async_mode=True, else completion status.

### `memory_tree_summary`

Get a hierarchical summary of the memory tree.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `level` | string | ❌ | `l0` (global), `l1` (grouped), `l2` (expanded), `all` (default) |
| `group_key` | string | ❌ | Group to expand (required for l2) |

---

## Cross-Layer

### `memory_search`

Search ALL 4 layers at once. The best entry point for agents.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | ✅ | Natural language query |
| `layers` | string | ❌ | `all` (default) or comma-separated |
| `max_results` | integer | ❌ | Max results per layer (default: 20) |

### `memory_stats`

Get statistics about the memory system.

**Returns:**
```json
{
    "memory_tree_count": 87,
    "preference_count": 42,
    "error_count": 13,
    "entity_count": 25,
    "faiss_index_size": 87
}
```

### `memory_health`

Run health check and return operational metrics.

**Returns:** Connection status, FAISS status, request latency, error rates.

---

## Layer 2: Preferences

### `preference_add`

Add a preference rule. Use when user corrects the agent.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `category` | string | ✅ | `field_alias`, `date_rule`, `naming`, `policy`, `format` |
| `condition` | string | ✅ | When does this rule apply? |
| `rule` | string | ✅ | The rule content |
| `scope` | string | ❌ | `personal` (default), `department`, `enterprise` |
| `confidence` | number | ❌ | Default: 0.8 |

### `preference_search`

Search preference rules by query.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | ✅ | Search query |
| `category` | string | ❌ | Filter by category |
| `scope` | string | ❌ | Filter by scope |

### `preference_list`

List all preference rules.

### `preference_disable`

Disable (soft-delete) a preference rule.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Preference ID |

---

## Layer 3: Error Memory

### `error_check`

**Call this BEFORE any task.** Checks if similar tasks have failed before.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_type` | string | ❌ | Task category filter |
| `task_description` | string | ❌ | Task description for matching |
| `max_results` | integer | ❌ | Default: 5 |

### `error_log`

Log an error and the user's correction. Auto-upgrades to rule after 3+ occurrences.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_type` | string | ✅ | Task type |
| `error_category` | string | ✅ | `field_selection`, `logic_error`, `scope_error`, `omission` |
| `mistake_description` | string | ✅ | What went wrong |
| `correction` | string | ✅ | How to fix it |
| `severity` | string | ❌ | `minor`, `major`, `critical` |
| `prevention_rule` | string | ❌ | Rule to prevent recurrence |

### `error_list`

List all error records.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `task_type` | string | ❌ | Filter by task type |
| `is_resolved` | integer | ❌ | 0=open, 1=resolved |

### `error_delete`

Delete an error record.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Error record ID |

---

## Layer 4: Knowledge Graph

### `entity_add`

Add an entity to the knowledge graph.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | string | ✅ | Entity type |
| `name` | string | ✅ | Entity name |
| `aliases` | string | ❌ | JSON array of aliases |
| `properties` | string | ❌ | JSON object of properties |
| `scope` | string | ❌ | Permission scope |

### `entity_search`

Search entities by name or alias.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | ✅ | Search query |
| `type` | string | ❌ | Filter by type |
| `max_results` | integer | ❌ | Default: 10 |

### `entity_link`

Link two entities with a relationship.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `source_name` | string | ✅ | Source entity name |
| `target_name` | string | ✅ | Target entity name |
| `relation` | string | ✅ | Relation type |
| `source_type` | string | ❌ | Source entity type |
| `target_type` | string | ❌ | Target entity type |

### `graph_query`

Query the full graph for an entity.

**Parameters:**
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `entity_name` | string | ✅ | Entity to explore |
