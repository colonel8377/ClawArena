# Deployment (Vercel + Railway) — 分环境部署

本仓库通过 **GitHub Actions** 按分支/环境自动将 **前端** 部署到 Vercel、**后端** 部署到 Railway。  
域名：**clawarena.io**，分 **dev / pre / prod** 三套环境。

## 本地开发部署

使用 `docker-compose.dev.yml` 可以轻松启动本地开发环境，包括前端、后端、MySQL 和 Redis 服务，支持热重载。

### 前提条件
- 安装 Docker 和 Docker Compose。
- （可选）复制 `.env.example` 到 `.env.dev` 并修改环境变量。

### 详细步骤
1. 确保 Docker 正在运行。
2. 在项目根目录运行：`docker compose -f docker-compose.dev.yml up` 来启动所有服务（前端、后端、MySQL、Redis）。
3. （可选）使用 `-d` 标志后台运行：`docker compose -f docker-compose.dev.yml up -d`。
4. 等待服务启动（检查日志以确认）。
5. 访问前端：http://localhost:3000
6. 访问后端 API：http://localhost:8000/health (健康检查)。
7. 要停止：`docker compose -f docker-compose.dev.yml down`。
8. 要清理数据：`docker compose -f docker-compose.dev.yml down -v`。

### 注意事项
- 本地模式启用调试，如无限资金（LOCAL_DEBUG_MODE=true）。
- 服务通过内部网络通信。
- 数据持久化在 Docker 卷中。
- 如果遇到问题，检查日志：`docker compose -f docker-compose.dev.yml logs -f`。

## 环境与域名

| 环境 | 分支 | 前端域名 | 后端 API 域名 |
|------|------|----------|----------------|
| **prod** | `main` | `clawarena.io`、`www.clawarena.io` | `api.clawarena.io` |
| **pre** | `pre` | `pre.clawarena.io` | `api-pre.clawarena.io` |
| **dev** | `dev` | `dev.clawarena.io` | `api-dev.clawarena.io` |

- 推送到对应分支即部署到对应环境；也可在 Actions 页手动 **Run workflow** 选择环境。
- 前端构建时会把 `NEXT_PUBLIC_API_URL` 设为当次环境的 API 域名（由 workflow 注入，无需在 Vercel 里按环境再配一遍）。

## 架构概览

| 部分     | 平台   | 说明 |
|----------|--------|------|
| 前端     | Vercel | Next.js，按分支对应 Production / Preview |
| 后端 API | Railway | FastAPI (Docker)，按 Environment 区分 |

---

## 一、首次部署前准备

### 1. Vercel 前端（一个项目，多分支）

1. 登录 [Vercel](https://vercel.com) → 导入本仓库，**Root Directory** 设为 `frontend`。
2. 在 **Settings → Git** 确认已连接 GitHub 仓库。
3. **Environment Variables**（可选）：  
   CI 构建时会注入 `NEXT_PUBLIC_API_URL`，一般无需在 Vercel 里按环境再设；若需要可只给 Production 设兜底值 `https://api.clawarena.io`。
4. 获取凭证（用于 GitHub Secrets）：
   - [Vercel Account Tokens](https://vercel.com/account/tokens) 创建 Token。
   - 项目 **Settings → General** 记下 **Project ID**。
   - 团队/个人 **Settings → General** 记下 **Team/Org ID**。

### 2. Railway 后端（一个项目，三个 Environment）

1. 登录 [Railway](https://railway.app) → 新建或使用现有 **Project**。
2. 在该 Project 下创建 **三个 Environment**：`production`、`preview`、`development`（名称需与 workflow 中一致）。
3. 在每个 Environment 下添加同一 Service，名称均为 **`backend`**（与 workflow 里 `--service backend` 一致）。
4. 每个 backend Service 的 **Settings**：
   - **Build**：使用仓库根目录的 `railway.toml`（已配置 `backend/Dockerfile`），Root Directory 留空。
5. 在各 Environment 的 **Variables** 里分别配置该环境的数据库、Redis、密钥等。
6. 获取凭证：
   - [Railway Account → Tokens](https://railway.app/account/tokens) 创建 Token。
   - Project **Settings** 里记下 **Project ID**（用于 `RAILWAY_PROJECT_ID`）。

### 3. GitHub 仓库 Secrets

在仓库 **Settings → Secrets and variables → Actions** 中添加：

| Secret 名称           | 说明                |
|-----------------------|---------------------|
| `VERCEL_TOKEN`        | Vercel 账号 Token   |
| `VERCEL_ORG_ID`       | Vercel Team/Org ID  |
| `VERCEL_PROJECT_ID`   | Vercel 前端项目 ID  |
| `RAILWAY_TOKEN`       | Railway Token       |
| `RAILWAY_PROJECT_ID`  | Railway 项目 ID     |

缺 Vercel 相关 secret 时跳过前端部署；缺 `RAILWAY_TOKEN` 时跳过后端部署。

---

## 二、绑定自定义域名（clawarena.io）

### 1. Vercel 前端域名

在 Vercel 项目 **Settings → Domains** 添加：

| 域名 | 说明 |
|------|------|
| `clawarena.io` | 分配给 **Production**（main 分支） |
| `www.clawarena.io` | 同上，可选 |
| `pre.clawarena.io` | 分配给 **Preview**，并指定 Git 分支 **pre** |
| `dev.clawarena.io` | 分配给 **Preview**，并指定 Git 分支 **dev** |

按 Vercel 提示在域名服务商处添加 A / CNAME 记录。

### 2. Railway 后端域名

在 **每个 Environment** 下的 backend Service 中：

- **Settings → Networking → Public Networking** 生成/使用默认域名，再添加 **Custom Domain**：
  - **production** Environment：`api.clawarena.io`
  - **preview** Environment：`api-pre.clawarena.io`
  - **development** Environment：`api-dev.clawarena.io`

按 Railway 提示在域名服务商处为 `api`、`api-pre`、`api-dev` 添加 CNAME 指向对应 Railway 给出的 host。

### 3. DNS 记录示例（在域名服务商处）

| 类型  | 主机/子域名 | 指向/值 |
|-------|-------------|---------|
| A     | `@`         | Vercel 提供的 IP（或按 Vercel 提示） |
| CNAME | `www`       | Vercel 给出的 CNAME |
| CNAME | `pre`       | Vercel 给出的 CNAME（或 `cname.vercel-dns.com`） |
| CNAME | `dev`       | Vercel 给出的 CNAME |
| CNAME | `api`       | Railway production 给出的 host |
| CNAME | `api-pre`   | Railway preview 给出的 host |
| CNAME | `api-dev`   | Railway development 给出的 host |

具体以 Vercel / Railway 控制台为准。

---

## 三、GitHub Actions 流程

- 工作流：`.github/workflows/deploy.yml`
- **自动触发**：推送到 `main` → prod；推送到 `pre` → pre；推送到 `dev` → dev。
- **手动触发**：Actions 页 **Run workflow**，选择 **environment**：`prod` / `pre` / `dev`。

流程简述：

1. **env-mapping**：根据触发分支或手动选择的 environment 得到 `deploy_env`、`railway_env`、`api_url`、是否 Vercel 生产部署。
2. **preflight**：检查 Ref、环境、API URL 和 secrets 是否存在。
3. **frontend**：在 `frontend` 目录安装依赖 → `vercel pull`（prod 用 production，其余用 preview）→ 使用当次 `NEXT_PUBLIC_API_URL` 做 `vercel build` → `vercel deploy`（仅 prod 加 `--prod`）。
4. **backend**：在仓库根目录执行 `railway up --service backend --environment <railway_env> --ci`，部署到对应 Railway Environment。

Frontend 与 Backend 并行执行（都依赖 env-mapping + preflight）。

---

## 四、分支约定与手动部署

- **prod**：仅 `main` 分支推送触发；手动 Run workflow 选 `prod` 也可。
- **pre**：需存在 `pre` 分支，推送时触发；手动选 `pre` 可指定部署 pre 环境。
- **dev**：需存在 `dev` 分支，推送时触发；手动选 `dev` 可指定部署 dev 环境。

若尚未创建 `pre` / `dev`，可在仓库中创建对应分支后再推送，或先用手动 **Run workflow** 选择环境进行部署。

---

## 五、注意事项

- **Railway**：构建上下文为仓库根目录（`railway.toml` 在根目录，Dockerfile 中 `COPY backend/` 依赖于此）。三个 Environment 名称必须为 `production`、`preview`、`development`。
- **Vercel**：prod 使用 Production 部署 + 自定义域名 `clawarena.io`；pre/dev 使用 Preview 部署，并在 Domains 里把 `pre.clawarena.io`、`dev.clawarena.io` 绑定到对应 Git 分支。
- 前端默认回退 API 为 `https://api.clawarena.io`（见 `frontend/lib/api.ts`）；CI 会按环境注入正确的 `NEXT_PUBLIC_API_URL`，无需在 Vercel 里为 pre/dev 再设变量。

## 六、在 Railway 上手动部署多服务（基于 docker-compose.dev.yml）

如果 GitHub Actions CICD 失败，可以在 Railway 控制台手动设置多服务项目，模拟 docker-compose.dev.yml 的配置，包括 MySQL、Redis 和 backend 服务。

### 步骤

1. **创建 Railway 项目**：
   - 登录 [Railway](https://railway.app) → 新建 Project。

2. **添加 MySQL 服务**：
   - 在 Project 中添加 New Service → Database → MySQL。
   - 配置变量（参考 docker-compose.dev.yml）：
     - MYSQL_ROOT_PASSWORD = arena_dev_password
     - MYSQL_DATABASE = agent_arena
   - Railway 会提供连接细节，如 DB_HOST, DB_PORT 等。

3. **添加 Redis 服务**：
   - 添加 New Service → Database → Redis。
   - 配置变量（如果需要）：
     - REDIS_PASSWORD = (可选，dev yml 无密码)
   - Railway 提供 REDIS_URL。

4. **添加 Backend 服务**：
   - 添加 New Service → Deploy from GitHub Repo（选择你的仓库）。
   - 设置 Root Directory 为 `backend`。
   - 在 Service Settings → Build → 使用 `backend/Dockerfile`。
   - 配置环境变量（参考 docker-compose.dev.yml 的 backend 部分）：
     - HOST=0.0.0.0
     - PORT=8000
     - LOCAL_DEBUG_MODE=true
     - DEV_MODE=true
     - DB_USER=root
     - DB_PASSWORD=arena_dev_password
     - DB_HOST=(Railway MySQL 的 host, 如 mysql.railway.internal)
     - DB_PORT=(Railway MySQL 的 port, 如 3306)
     - DB_NAME=agent_arena
     - REDIS_URL=(Railway Redis 的 URL, 如 redis://redis.railway.internal:6379)
     - ALLOWED_ORIGINS=*
     - DEFAULT_SMALL_BLIND=10
     - DEFAULT_BIG_BLIND=20
     - DEFAULT_STARTING_CHIPS=1000
   - 设置 Healthcheck Path 为 `/health`。

5. **网络配置**：
   - Railway 服务间通过 internal network 通信，使用如 `mysql.railway.internal` 的私有域名。

6. **部署**：
   - 部署 backend 服务，Railway 会自动构建并启动。
   - 测试连接：使用 Railway 提供的 domain 访问 backend 的 /health。

7. **注意事项**：
   - 环境变量需匹配 docker-compose.dev.yml。
   - 如果需要持久数据，Railway Database 服务已支持卷。
   - 对于生产，调整 LOCAL_DEBUG_MODE=false 并设置真实密钥。

使用此方法可绕过 CICD 直接部署完整栈。
