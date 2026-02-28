# AgDevOps 运维平台

<p align="center">
  <strong>基于 Django + Vue 3 的现代化运维管理平台</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Django-≥5.0-092E20?logo=django" alt="Django">
  <img src="https://img.shields.io/badge/Vue-3.5-4FC08D?logo=vue.js" alt="Vue 3">
  <img src="https://img.shields.io/badge/Vite-6.x-646CFF?logo=vite" alt="Vite">
  <img src="https://img.shields.io/badge/Element%20Plus-2.9-409EFF" alt="Element Plus">
  <img src="https://img.shields.io/badge/License-MIT-blue" alt="License">
</p>

---

## ✨ 功能特性

- 📊 **仪表盘** — 主机、部署、告警实时统计，ECharts 数据可视化
- 🖥️ **主机管理** — 完整 CRUD，CPU / 内存 / 磁盘使用率进度条
- 🚀 **部署管理** — 支持 生产 / 预发布 / 测试 / 开发 多环境管理
- 📋 **日志中心** — 集成 Loki 日志查询，类 Grafana Explore 的 LogQL 体验
- 🔔 **告警中心** — 严重 / 警告 / 信息 多级别告警，支持确认处理
- 🛡️ **SQL 审计 (新)** — MySQL 数据源管理、SQL 工单提交流程（自动语法安全检查）、只读 SQL 线上查询
- 👥 **用户管理** — 基于 Django Auth 的用户角色体系

## 🏗️ 技术栈

**后端：** Django 5+ · Django REST Framework · django-cors-headers · SQLite

**前端：** Vue 3 (Composition API) · Vite · Element Plus · Pinia · ECharts · Axios · Vue Router

## 📁 项目结构

```
agdevops/
├── backend/                       # Django 后端
│   ├── agdevops/                  #   主项目配置
│   ├── ops/                       #   核心业务应用
│   │   ├── models.py              #     数据模型
│   │   ├── views.py               #     REST API 视图
│   │   ├── loki_views.py          #     Loki 日志代理
│   │   ├── serializers.py         #     序列化器
│   │   └── management/commands/   #     管理命令
│   ├── sqlaudit/                  #   SQL 审计应用 (新)
│   │   ├── models.py              #     数据源/工单数据模型
│   │   ├── views.py               #     审计流 API 视图
│   │   ├── sql_checker.py         #     DDL/DML 语法与安全检查器
│   │   └── db_executor.py         #     MySQL 查询与执行引擎
│   ├── requirements.txt
│   └── manage.py
│
└── frontend/                      # Vue 3 前端
    ├── src/
    │   ├── views/                 #   页面组件（包含 SqlOrders, SqlQuery 等 9 个视图）
    │   ├── layout/                #   布局组件
    │   ├── api/                   #   API 封装层
    │   ├── stores/                #   Pinia 状态管理
    │   └── assets/                #   全局样式
    ├── vite.config.js
    └── package.json
```

## 🚀 快速启动

### 环境要求

- Python ≥ 3.10
- Node.js ≥ 18

### 1. 启动后端

```bash
cd backend

# 安装依赖
pip install -r requirements.txt

# 数据库迁移
python manage.py migrate

# （可选）生成演示数据
python manage.py seed_data

# 启动开发服务器
python manage.py runserver 0.0.0.0:8000
```

### 2. 启动前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

启动后使用浏览器访问 **http://localhost:3000** 即可使用。

> 💡 **内网访问提示**：前端 Vite 已配置监听 `0.0.0.0`，因此你可以直接将本机的局域网 IP（例如 `http://192.168.1.x:3000`）分享给同事访问本平台。前提是你本机的防火墙放行了 3000 和 8000 端口。

> 前端已配置 Vite 代理，将 `/api` 请求自动转发到 `http://127.0.0.1:8000`。

## 📡 API 概览

| 端点 | 说明 |
|------|------|
| `GET /api/dashboard/stats/` | 仪表盘聚合统计 |
| `/api/hosts/` | 主机管理 (CRUD) |
| `/api/deployments/` | 部署记录管理 (CRUD) |
| `/api/alerts/` | 告警管理 (CRUD) |
| `/api/logs/` | 日志记录管理 (CRUD) |
| `/api/loki/*` | Loki 日志代理 (labels / query_range / series) |
| `/api/sqlaudit/datasources/` | MySQL 数据源管理 |
| `/api/sqlaudit/orders/` | SQL 审计工单与审核流 |
| `/api/sqlaudit/query/` | 线上数据库安全只读查询 |

## 📦 数据模型

| 模型 | 说明 | 主要字段 |
|------|------|---------|
| **Host** | 主机 | hostname, ip_address, os_type, status, cpu/memory/disk_usage |
| **Deployment** | 部署记录 | app_name, version, environment, status, deployer, host(FK) |
| **Alert** | 告警 | title, level, source, message, is_acknowledged, host(FK) |
| **LogEntry** | 日志 | level, service, message, host(FK), timestamp |
| **DataSource** | MySQL数据源 | name, host, port, username, password(加密), charset |
| **SqlOrder** | SQL 工单 | title, datasource(FK), database, sql_type, sql_content, status |

## ⚙️ 配置说明

### Loki 集成

在 `backend/agdevops/settings.py` 中配置 Loki 地址：

```python
LOKI_URL = 'http://your-loki-host:3100'
```

后端会代理前端的 Loki 请求，避免浏览器跨域问题。

### CORS

默认开启全量跨域（开发模式）：

```python
CORS_ALLOW_ALL_ORIGINS = True
```

生产环境建议设置 `CORS_ALLOWED_ORIGINS` 白名单。

## 📄 License

MIT
