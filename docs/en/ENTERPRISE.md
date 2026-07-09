# Memory Engine Enterprise

> Production-grade persistent memory for enterprise AI agents.
> Self-hosted. On-premise. Your data never leaves your network.

---

## Open Source vs Enterprise

| Feature | Open Source (MIT) | Enterprise |
|---------|:-----------------:|:----------:|
| **Memory Tree (L1)** — Vector search + summaries | ✅ | ✅ |
| **Preferences (L2)** — Learned rules | ✅ | ✅ |
| **Error Memory (L3)** — Auto-learn from mistakes | ✅ | ✅ |
| **Knowledge Graph (L4)** — Entity relationships | ✅ | ✅ |
| **22 MCP Tools** | ✅ | ✅ |
| **FAISS + SQLite (lightweight)** | ✅ | ✅ |
| **Docker + systemd** | ✅ | ✅ |
| **CI/CD** | ✅ | ✅ |
| **30-point audit** | ✅ | ✅ |
| **Availability** | Community support | **SLA-backed 99.9%** |
| **Milvus + PostgreSQL + Redis (heavy)** | ❌ | ✅ |
| **Multi-node cluster** | ❌ | ✅ |
| **Horizontal scaling (10M+ vectors)** | ❌ | ✅ |
| **LDAP / SSO integration** | ❌ | ✅ |
| **Audit log export (Elasticsearch)** | ❌ | ✅ |
| **Grafana + Prometheus monitoring** | ❌ | ✅ |
| **Data encryption at rest** | ❌ | ✅ |
| **WeChat Work / DingTalk integration** | ❌ | ✅ |
| **Private deployment training** | ❌ | ✅ |
| **Phone / WeChat technical support** | ❌ | ✅ |
| **Custom data source integration** | ❌ | ✅ |
| **On-site deployment assistance** | ❌ | ✅ |

## Why Enterprise?

### 1. Your Data Stays Yours

Unlike cloud-only solutions (Mem0, Letta), Memory Engine Enterprise deploys entirely within your network. No data ever leaves your premises. No third-party API calls. No cloud dependencies.

### 2. Scale to Millions of Vectors

The open-source version handles up to ~100K vectors on a single node. Enterprise adds Milvus + PostgreSQL + Redis, supporting **10M+ vectors** across a cluster with horizontal scaling.

### 3. Production Monitoring

Grafana dashboards for real-time monitoring. Prometheus metrics. Elasticsearch audit log export. You see every query, every error, every recall.

### 4. Enterprise Integrations

- **LDAP / SSO** — Single sign-on with your existing identity provider
- **WeChat Work / DingTalk** — Chinese enterprise messaging integration
- **Custom data sources** — We'll build connectors for your internal systems

### 5. SLA-Backed Support

99.9% uptime SLA. Phone and WeChat support during business hours. 4-hour response time for critical issues.

---

## Pricing

### Annual Subscription (Yearly)

| Tier | Price | Data Volume | Nodes | Support |
|------|-------|-------------|-------|---------|
| **Starter** | **5,000 RMB / year** (~$700) | ≤100K vectors | 1 | Email + Remote |
| **Professional** | **15,000 RMB / year** (~$2,100) | ≤1M vectors | 3 | WeChat + Phone |
| **Enterprise** | **50,000 RMB / year** (~$7,000) | Unlimited | Unlimited | Dedicated group + SLA |

### One-Time Services

| Service | Price | Description |
|---------|-------|-------------|
| Standard Deployment | **20,000 RMB** (~$2,800) | Environment setup, data migration, training (3 days) |
| Custom Data Source | **10,000 - 30,000 RMB** each | Complexity-dependent |
| System Integration | **5,000 - 20,000 RMB** each | Per integration point |
| Annual Maintenance | **15% of deployment fee/year** | Minor upgrades + bug fixes |

### Launch Promotion

| Offer | Terms |
|-------|-------|
| **First 5 enterprise customers** | **50% off first year** |

---

## Minimum Requirements

### Lightweight (FAISS + SQLite)

| Spec | Requirement |
|------|-------------|
| vCPU | 2 cores |
| RAM | 2 GB |
| Disk | 10 GB SSD |
| OS | Linux (Ubuntu 22.04+, Debian 12+) |
| Python | 3.10+ |

### Heavy (Milvus + PostgreSQL + Redis)

| Component | Spec |
|-----------|------|
| Application node | 4 vCPU, 8 GB RAM |
| Milvus cluster | 8 vCPU, 16 GB RAM (3 nodes recommended) |
| PostgreSQL | 4 vCPU, 8 GB RAM |
| Redis | 2 vCPU, 4 GB RAM |
| Disk | 100 GB+ SSD |

---

## Deployment Options

| Method | Complexity | Time | Best For |
|--------|-----------|------|----------|
| Docker Compose | Low | 10 min | Single-node evaluation |
| Kubernetes | Medium | 1 hour | Production cluster |
| On-site assisted | High | 3 days | Enterprise with compliance |

---

## Get Started

**Ready to try?** The open-source version is fully functional — no features removed, no trial period.

- [Download from GitHub](https://github.com/qq1009128320-dotcom/memory-engine)
- [Quick Start Guide](QUICKSTART.md)
- [Architecture Overview](ARCHITECTURE.md)

**Need enterprise?** Contact us:
- Email: [1009128320@qq.com](mailto:1009128320@qq.com)
- Or open a [GitHub issue](https://github.com/qq1009128320-dotcom/memory-engine/issues/new) tagged `enterprise`

---

*All prices in RMB. International pricing available on request.*
*Enterprise features are under active development — contact us for availability timelines.*
