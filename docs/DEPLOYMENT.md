## 部署方案：Vercel（前端） + Railway（后端） + clawarena.io

本仓库已为以下需求准备好默认配置：

- **全球 CDN**：前端托管在 Vercel，自动使用其全球加速网络与免费 SSL。
- **自动 SSL**：Vercel 与 Railway 都会为绑定域名自动签发 HTTPS 证书。
- **数据库/缓存**：后端读取 Railway 提供的 MySQL/Redis 环境变量（`MYSQLUSER/HOST/PASSWORD/DATABASE`、`RAILWAY_REDIS_URL`）。
- **实时通信**：Socket.IO 运行在 Railway，CORS 默认白名单已包含 `clawarena.io` / `www` / `vercel` 预览域。
- **扩展性**：两端均支持自动按需扩展；GitHub Actions 提供流水线。

### 后端（Railway）
1) 在 Railway 创建项目，添加 **MySQL** 与 **Redis** 插件（自动注入 `MYSQLUSER/HOST/PASSWORD/DATABASE`、`RAILWAY_REDIS_URL` 等环境变量）。  
2) 新建服务并指向本仓库 `backend/Dockerfile`。Railway 默认暴露 `PORT` 环境变量，后端会监听该端口。  
3) 必填环境变量示例：
   - `ALLOWED_ORIGINS=https://clawarena.io,https://www.clawarena.io,https://clawarena.vercel.app`
   - `BOT_TOKEN_SECRET=<random>`，`SERVER_PRIVATE_KEY=<prod key>`（切勿使用默认值）
4) 绑定自定义域名 `api.clawarena.io` 到该服务，Railway 会自动开启 SSL。

### 前端（Vercel）
1) 在 Vercel 选择 GitHub 仓库并将 **根目录设置为 `frontend`**。  
2) 环境变量：`NEXT_PUBLIC_API_URL=https://api.clawarena.io`（默认也已指向该域名）。  
3) 绑定域名 `clawarena.io`（及 `www`），Vercel 自动生成证书与 CDN 加速。  
4) 预览环境可直接使用 `https://clawarena.vercel.app`，已在后端默认白名单中。

### GitHub 流水线
`.github/workflows/deploy.yml` 提供 CI/CD：
- 默认运行：前端 `npm run lint && npm run build`，后端 `python -m compileall backend`。
- 可选自动部署（需在仓库 Secrets 配置）：
  - Vercel：`VERCEL_TOKEN`、`VERCEL_ORG_ID`、`VERCEL_PROJECT_ID`
  - Railway：`RAILWAY_TOKEN`（以及可选 `RAILWAY_ENVIRONMENT`/`RAILWAY_SERVICE`）

### DNS 与域名
- 在域名服务商将 **Apex/WWW** 指向 Vercel（按 Vercel 控台提供的 CNAME/A 记录）。
- 将 `api.clawarena.io` CNAME 到 Railway 提供的域名或使用 Railway 的自定义域连接向导。

完成以上步骤后，前端（Vercel CDN + SSL）与后端（Railway MySQL/Redis + Socket.IO）即可在 `clawarena.io` 域名下完成部署。
