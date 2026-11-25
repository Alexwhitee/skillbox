# Cloudflare Pages 发布

适用于静态介绍网站。命令参数可能变化，先看本机 Wrangler 的 `--help`；需要联网查证时使用下方 Cloudflare 官方文档。使用已安装的 Wrangler 或项目已有版本，不静默升级工具链。

## 确认账号与站点

```bash
WRANGLER_SEND_METRICS=false wrangler whoami
WRANGLER_SEND_METRICS=false wrangler pages project list
```

凭据失效时请用户在本机执行 `WRANGLER_SEND_METRICS=false wrangler login` 并完成浏览器授权，不索要令牌内容、不打印凭据或认证日志。登录后重查一次；同一认证错误不无限重试。可继续本地制作和验证，不能声称已发布。

有多个账号时结合已有配置选择；无法确定时询问。可用 `CLOUDFLARE_ACCOUNT_ID` 指定已确认账号，不把旧项目的账号、站点名、仓库地址或分支复制给新项目。

从现有配置和项目列表识别目标。已存在的项目必须先核对归属、域名、生产分支与发布方式，不能覆盖同名的其它网站。若用户需要 Git 自动部署，应在新建时选择对应方式；Direct Upload 项目不能原地切成 Git 集成，不自行引入 CI。

## 构建并直接上传

先运行项目实际构建与检查命令。以下变量必须替换为已核对的值，不能按示例猜生产分支；新站无现有生产分支时可用当前项目分支作为明确记录的选择。Pages 的生产分支只决定发布环境，不执行 Git 合并或推送。

```bash
# 在项目根目录设置本次目标；路径只指向待发布的静态输出。
site_project='actual-project-name'
site_production_branch='actual-production-branch'
site_output='site/dist'

# 仅当已确认需要新建且不存在该项目时运行。
WRANGLER_SEND_METRICS=false wrangler pages project create "$site_project" --production-branch "$site_production_branch"

# --branch 与站点配置的 production branch 一致才是生产发布。
WRANGLER_SEND_METRICS=false wrangler pages deploy "$site_output" --project-name "$site_project" --branch "$site_production_branch"
```

工作区有未提交的网站改动且当前任务允许发布它们时，加 `--commit-dirty=true`，不要为消除提示伪造干净状态或自动提交。若使用 Wrangler 配置文件，`pages_build_output_dir` 必须对应它所在目录的实际输出，保留已有配置，不顺手改变其它服务。

上传前查看目录内容：纯静态介绍站不应意外包含 `_worker.js`、Functions、source maps、源码密钥、私人文档。记录本次构建版本或输出摘要，线上比对同一产物。

静态站可在发布输出中放 `_headers`：以真实资源需求配置 CSP、`X-Content-Type-Options: nosniff`、Referrer-Policy 等。只用同源 CSS/JS 时可用 `script-src 'self'; style-src 'self'`；采用内联脚本或外部资源的已有框架时使用匹配的 hash/nonce/源，不为套用模板破坏页面或放开全部来源。`_headers` 对 Pages 静态资源生效，不代替 Functions 的响应头。

## 线上核验与故障边界

- 从 CLI 输出或 Cloudflare 项目信息取得真实部署 URL 和生产域名；名称被占用时域名可能有额外后缀，不能猜。
- 请求生产站的两种语言首页、手册路由和核心 CSS/JS，核对 HTTPS、状态、语言元数据和本次内容。用浏览器检查语言切换、章节深链接、主要交互和控制台。修复 404、旧内容或 CSP 阻断后重新核验。
- 网络失败先区分本机代理、TLS、认证和实际站点错误；可以用浏览器或其它现有 HTTP 客户端交叉检查，不能为通过测试关闭 TLS 校验。
- 相同错误在一次有依据的修正后仍重复，就报告具体阻塞并保留本地产物；不要持续创建新项目、换账号或覆盖其它站点。
- 不自动绑定/改动自定义域名、DNS、付费服务或账号权限。用户明确要求这些时，另按实际任务处理。

官方资料：
- [Wrangler Pages 命令](https://developers.cloudflare.com/workers/wrangler/commands/pages/)
- [Direct Upload](https://developers.cloudflare.com/pages/get-started/direct-upload/)
- [静态响应头](https://developers.cloudflare.com/pages/configuration/headers/)
