# 操作参考

文件路径相对项目根目录。服务 JSON 为 `{success:true,data:...}` 或 `{success:false,error,details}`；同时检查 HTTP 状态与 `success`。

## 已有服务 API

| 操作 | 方法和路径 | 参数/结果 |
| --- | --- | --- |
| 列连接 | `GET /api/connections` | 按站点、模式、分组匹配 |
| 建连接 | `POST /api/connections` | `name,adapterKind:"aimass-newapi",baseUrl,authMode,defaultGroup`；返回 `data.id` |
| 保存会话 | `POST /api/connections/:id/session` | `{manualCookie,manualUserId}`；检查 `data.valid`，保存成功不等于会话有效 |
| 测试 | `POST /api/connections/:id/test` | `data.success`；密码模式会登录并保存会话 |
| 预估 | `POST /api/jobs/estimate` | `{connectionId,filters}` |
| 建任务 | `POST /api/jobs` | `{connectionId,pageSize,crawlDelayMs,concurrency,filters}`；返回 `data.id` |
| 查任务 | `GET /api/jobs/:id` | `status,recordsCount,progressCurrentPage,progressTotalPages,lastError` |
| 明细 | `GET /api/jobs/:id/records?page=1&pageSize=50` | `data.items,total,page,pageSize` |
| 导出 | `POST /api/jobs/:id/export` | `{format:"jsonl"}` 或 csv/xlsx；同步生成，检查 `data.status === "ready"` |
| 下载 | `GET /api/exports/:id` | 用导出产物 ID，不是任务 ID；返回文件 |

连接的 `password` 模式额外要求 `username,password`。`manual_session` 创建请求的 validator 要求 `manualCookie,manualUserId`，但创建 service 忽略两字段，因此还必须调用保存会话接口。

任务参数例子（替换连接、时间与分组）：

```json
{
  "connectionId": "existing-connection-id",
  "pageSize": 100,
  "crawlDelayMs": 300,
  "concurrency": 1,
  "filters": {
    "group": "requested-group",
    "startAt": "2026-11-11T16:00:00.000Z",
    "endAt": "2026-11-12T15:59:59.000Z"
  }
}
```

该时间为北京时间 11 月 12 日 00:00:00 至 23:59:59；上游边界以 adapter 和实际响应为准。客户端先验证日期有效且结束不早于开始。可选筛选：`username,tokenName,modelName,channel,requestId`。

## 新建本地环境时

先检查 `package.json`、数据库状态。当前没有 README 提到的 `.env.example`，不能盲目复制。

- 必需：PostgreSQL `DATABASE_URL`、恰好 32 个 UTF-8 字节的 `APP_ENCRYPTION_KEY`。Web/Worker 必须一致；已有数据库不能随意换 key，否则旧凭据无法解密。
- 可选：`STORAGE_DIR,APP_BASE_URL,PLAYWRIGHT_HEADLESS,PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,WORKER_POLL_MS`。
- 缺依赖时用锁文件执行 `npm ci`，再 `npm run prisma:generate`。仅密码登录且缺浏览器时才 `npx playwright install chromium`，也可用已有浏览器路径。
- `npm run prisma:migrate` 是 `prisma migrate dev`，仅用于核对后的开发库；如提示 reset/丢数据就停止，不自动重置或对生产库执行。
- Web：`npm run dev -- --hostname 127.0.0.1 --port 3000`，冲突时选空闲端口。应用没有登录保护，本地绑定回环，不替用户公开部署。
- Worker：同目录同环境运行 `node --env-file=.env worker/index.js`（Node 支持此参数时）；父进程已提供环境可 `npm run worker`。普通 Node 不像 Next.js 自动加载 `.env`，不要把 `.env` 当 shell 脚本执行。

## 排障与核验

- queued：检查 Worker 和数据库配置；Worker 会消费整个待处理队列。
- running 无进展：核对页数、进程和最后错误，不直接改库或重复建任务。
- 会话失效：密码模式重新测试登录；手动模式更新会话。采集走 `/api/log/stat`、`/api/log/`，adapter 可回退 self 接口；不改用 `/api/data` 或数据库直连。
- 网络：项目 Node 请求优先 `HTTPS_PROXY/HTTP_PROXY/ALL_PROXY`，其次 macOS 系统代理；复用现有网络代码。
- 实现入口：`lib/adapters/aimass-newapi.js`、`lib/services/{connection-service,crawl-job-service,repositories}.js`、`lib/time.js`。
- 导出数量按解析后的数据行核对，CSV 物理换行数不等于记录数。仅操作接口不必构建；修改应用代码才跑 `npm test`。
