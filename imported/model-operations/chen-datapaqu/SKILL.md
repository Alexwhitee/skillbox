---
name: chen-datapaqu
description: 操作 chen-datapaqu，通过账号密码或手动 Cookie 会话采集 Aimass/NewAPI 网站用量日志，创建任务、检查进度并导出 JSONL/CSV/XLSX。适用于抓取网站用量记录；已有 MySQL 报表服务的查询与导出使用 chen-wufuqi。
---

# Chen 用量采集

复用现有 Next.js + PostgreSQL + Playwright 采集器，不另写爬虫。本 skill 是本机项目的操作入口，不包含应用源码或数据库。

## 入口

- 项目通常位于工作区的 `jiaoben/zong/chen-datapaqu`。优先使用用户指定目录；路径不匹配时，在当前工作区定位 `package.json` 名称为 `aimass-usage-crawler` 的项目；找不到时再请用户提供项目位置。
- 先读 [references/operations.md](references/operations.md)。接口变化以项目 `app/api/`、`lib/validators.js` 和 services 为准；README 未完整描述手动会话能力。
- 区分采集服务地址与目标网站 `baseUrl`；先识别实际服务。两个项目默认都用 3000，不能仅凭端口判断服务。

## 流程

1. 确定目标站点或已有 `connectionId`、分组、起止时间、可选筛选和格式。优先复用已有连接；不默认全部历史。无时区时间按北京时间理解并说明，无法确定范围时再询问。
2. 优先使用已运行的服务。需要新环境才按参考准备数据库与进程；仅导出已有任务不需要启动会消费整个队列的 Worker。
3. 使用密码或手动会话。凭据从环境变量读取，在内存中组装请求；不在命令、skill 或输出中写入真实密码/Cookie。
4. 手动模式创建连接后，必须单独保存会话并检查 `valid`，创建接口不会持久化 Cookie。过期时更新会话，不尝试空密码登录；验证码/MFA 由用户完成。
5. 测试连接、以相同条件预估、创建任务。默认 `pageSize=100,crawlDelayMs=300,concurrency=1`；只在用户要求或运行证据支持时调整。
6. 轮询原任务至 `succeeded/failed/partial`。无完成证据不重复建单；长期无进展时检查 Worker、会话、代理和最后错误，报告任务 ID 与阻塞，不无限重试。
7. 成功后创建导出并下载到指定目录或独立输出目录，检查文件存在、非空及数据行数。`partial` 可按需要导出现有记录，但必须标明不完整；失败不能称为完整导出。

## 数据与交付

- API 时间必须是 UTC ISO，例如 `new Date('2026-11-12T00:00:00+08:00').toISOString()`。不能把北京时间直接拼成 `Z`；页面与导出时间按北京时间处理。
- 去重键为 `(connectionId,sourceRecordId)`。重跑会更新记录及其 `jobId`，旧任务查询/导出可能改变；需历史快照时先下载原产物，不能承诺任务结果不可变。
- 任务详情包含连接和原始页面；只输出状态、页数、记录数和脱敏错误，不转储完整响应或凭据。
- 交付文件绝对路径、任务 ID、实际筛选、北京时间范围、状态和记录数；零条与采集失败分开说明。
