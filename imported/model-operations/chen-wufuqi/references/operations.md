# 操作参考

路径相对项目根目录；接口以 `src/server/routes.ts`、`auth.ts` 为准。

## 登录与查询

`POST /api/auth/login` 发 `{username,password}`，保存 `report_session` Cookie 并随后续请求携带。JSON 成功通常是 `{data:...}`，失败 `{error:{message}}`，同时检查 HTTP 状态。凭据从环境在进程内组装，不能展开到 shell 命令或工具输出。

| 目的 | 方法和路径 | 关键参数/行为 |
| --- | --- | --- |
| 项目 | `GET /api/sources` | 读取实际 `data[].key` |
| 用户 | `GET /api/filters/users?projectKey=...` | `id,username,display_name`，最多 1000 条 |
| 其他筛选 | `GET /api/filters/models`、`/tokens`、`/channels` | 都需要 projectKey |
| 明细 | `GET /api/reports/usage/details` | projectKey,start,end；pageSize 1..500 默认 50；后续传 cursor |
| 总数 | `GET /api/reports/usage/details/count` | 同筛选，较慢，分页不必先查总数 |
| 汇总 | `GET /api/reports/usage/summary` | 同范围；groupBy=hour/day/user/model，默认 day |
| 同步 | `GET /api/sync/status` | states,counts；核对时间与 last_error |
| 诊断 | `GET /api/health/performance`、`/api/operations` | operations 支持 projectKey,component,status,page,pageSize |
| 手动同步 | `POST /api/sync/run` | 用户要求时发 `{projectKey}`，再查状态，不循环发起 |

`start/end` 为非负 Unix **秒**，包含两端：`created_at >= start AND created_at <= end`。整日为北京时间 00:00:00 至 23:59:59 后转秒，不能传毫秒。先验证时间有效和顺序。

明细/汇总可选筛选：`userId,model,tokenId,channelId,group,ip,requestId`；用户名先解析成 userId，不是明细的直接参数。

明细返回 `{data:[...],meta:{pageSize,hasNextPage,nextCursor}}`；没有 page/offset 模式。后续保持相同筛选只换 cursor；若游标重复或缺失却仍有下一页，停止报告异常。503 时缩小范围或导出，不高频重试 count/summary。

## 服务端异步导出

1. `POST /api/exports`：`{type:"details"或"summary",format:"csv"或"xlsx",filters:{projectKey,start,end,...}}`；汇总可加 groupBy，不传分页参数，客户端先验证时间。
2. 保存 `data.id`，查 `GET /api/exports/:id`；pending/running 等待，completed 下载，failed/expired 停止。`GET /api/exports` 可查已有队列，避免重复创建。
3. `GET /api/exports/:id/download`：409 未完成、410 已过期。默认 TTL 24 小时，以实际 `EXPORT_TTL_HOURS` 为准。

需要服务 Worker；仅导出不自动启动远程 Worker或重置队列。

## 按用户名导出脚本

Node 需支持 fetch、Headers、Headers.getSetCookie，先检查能力。直接分页脚本还需项目 exceljs，缺依赖且有锁文件时 `npm ci`。

每次显式提供以下环境变量，不能用脚本历史默认值：

```text
REPORT_BASE_URL           当前报表服务 URL
REPORT_ADMIN_USERNAME     管理员账号
REPORT_ADMIN_PASSWORD     管理员密码，仅通过环境提供
REPORT_PROJECT_KEY        /api/sources 的实际 key
REPORT_USAGE_USERNAME     当前目标用户名
REPORT_START              北京时间 YYYY-MM-DD HH:mm[:ss]
REPORT_END                北京时间 YYYY-MM-DD HH:mm[:ss]
REPORT_OUTPUT_DIR         本次独立输出目录，优先绝对路径
```

配置已确定且校验后，在项目目录选一种运行：

```bash
node scripts/export-usage-by-username.mjs
```

建服务端 details/xlsx 任务、轮询、下载。可选 `REPORT_POLL_INTERVAL_MS=2000`、`REPORT_TIMEOUT_MS=600000`。整体执行额外设置有界超时，因为单次 fetch 没有请求超时；超时保留已建任务 ID。

```bash
node scripts/export-usage-direct.mjs
```

游标分页查询明细 API，流式写本地 XLSX，无需导出 Worker。可选 `REPORT_PAGE_SIZE=500`（最大 500）、`REPORT_REQUEST_TIMEOUT_MS=120000`；额外设置有界总执行时间。失败文件不能当成功产物交付。

两个脚本按 username 或 display_name 取首个匹配，仅覆盖单用户明细 XLSX。要明确 ID、其他筛选、汇总或 CSV 时用已有 API，不扩写脚本。

## 明确需要本地服务/同步时

- 先读 `src/server/config.ts`、`db.ts`、`src/worker/index.ts`、`package.json`。操作已部署服务无需本地 MySQL。
- 报表库 `REPORT_DB_HOST/PORT/USER/PASSWORD/NAME`；源库 `SOURCE_DB_*` 或 `SOURCE_PROJECTS_JSON`。源账号只读，写入独立报表库。
- 多源 JSON 每项：`key,label,port,dbHost,dbPort,dbUser,dbPassword,dbName`，key 唯一；不把真实密码配置复制到文档/输出。
- 初始化配置：`ADMIN_USERNAME,ADMIN_PASSWORD,SESSION_SECRET`；另有 `PORT,PUBLIC_BASE_URL,EXPORT_DIR,EXPORT_TTL_HOURS`。新环境使用自有凭据，不沿用开发默认值。两个项目默认都占 3000，先选空闲端口。
- `npm run dev` 启动后端；`npm run build` 构建前后端；`npm start` 运行构建；`npm run worker` 启动调度。项目不自动加载 `.env`，通过父进程安全提供配置，不把 `.env` 当 shell 脚本执行。后端源码绑定 `0.0.0.0`，启动前核对运行环境的网络范围。
- 服务/Worker 启动都会执行 runMigrations，会建表、改索引、初始化管理员；Worker 还重置卡住的导出并清理过期文件。因此启动不是只读诊断。
- scheduler 按北京时间日窗口同步并修复最近两天；60 秒轮询不代表源数据每分钟更新。准确时间读 `src/worker/sync.ts` 的 shouldRunDailySync/getShanghaiDayWindow。
- `WORKER_MODE=backfill` 要求 `BACKFILL_START_DATE/BACKFILL_END_DATE`，回填后仍循环处理导出，不会一次性退出；未请求不启动。
- 修改应用后先 `npm run check`，再按影响 `npm test`。仅封装/使用 skill 不必构建应用或接触真实数据库。
