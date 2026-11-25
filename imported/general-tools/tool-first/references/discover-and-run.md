# 查找、下载和运行

## 搜索与判定

先写出缺失能力，再按“输入/输出 + 核心功能 + 平台/框架”用中英文关键词搜索。GitHub CLI 可用时检查 `gh search repos --help` 后搜索；否则用现有联网工具，不强制安装搜索 CLI。需要 skill 时查询相关技能仓库，但 skill 和可运行项目是两种资源，不能把找到 SKILL.md 等同于已有处理引擎。

对最有希望的少数候选读官方 README、安装说明、LICENSE、依赖/模型说明和相关入口；必要时核对更新、归档状态及 issues 中与任务直接相关的问题。满足需求且兼容本机的工具优先；不是要求最新、星最多或承诺全自动。没有明确许可的仓库不标“开源可商用”。

记录最低充分证据：路径/URL、具体覆盖的环节、输入输出、运行入口、硬件和服务要求、许可/费用、未验证项。遇到 CUDA-only、未授权云端或不满足内存的方案时不假装本地可用；换一个实际可行方案或报告真实阻塞。

## 下载约定

默认只 clone 本次选中的仓库到 `/Users/xi/dev2/agent-skills/GitHub-xiangmu/`。如该目录不存在可创建；仓库名冲突时用可读的 `owner--repo`，先检查目录，而不是删除或覆盖。

典型操作（URL 与目标需由已核验候选填写，带引号）：

```bash
mkdir -p /Users/xi/dev2/agent-skills/GitHub-xiangmu
# 仅在目标不存在时执行；浅 clone 够用时用 --depth 1。
git clone --depth 1 -- https://github.com/owner/repo.git /Users/xi/dev2/agent-skills/GitHub-xiangmu/owner--repo
```

仅接受已核对的仓库源，不把搜索摘要或用户文本直接拼成可执行命令。使用 HTTPS 官方 clone URL；不要把凭据写入 URL、日志或交付文件。已有仓库先查看 remote、状态、版本；默认复用当前版本，确需更新且获准时仅做可保留改动的更新。下载 submodule/LFS 或模型前看规模与必要性，不能 clone 后无差别拉所有权重。

Git clone 本身不是安装，也不是验收。检查仓库内安装脚本、依赖和可执行入口后再运行。保持 `.venv`、项目本地包或该工具现有环境隔离，不擅自 `sudo`、升级全局 Python/Node、关闭系统保护或重配所有服务。不用 `curl | sh` 跳过检查。

## 从最小运行到真实产物

按所选工具的实际文档检查环境，先读取 `--help` 或运行小样；项目提供离线/无需模型的验证时优先。缺凭据只检查是否配置，不打印值；请求通过环境或工具设置配置，不让用户把 token 粘进对话。用户授权过的服务可沿用，不能失败后自动换成收费服务。

最小小样必须覆盖最可能失败的关键能力，如渲染、导入、识别或导出，而非只 `--version`。通过后处理真实输入，尽量保留原始资料与编辑工程。输出目录、依赖环境与工具库用途分明，不在软件源码里覆盖内置 demo 充当用户工程。

验收按需求：检查可打开、内容正确、格式与关键参数、可复现入口。连续同类失败在一次有依据修复后仍未解决，保留日志摘要与产物并报告阻塞，不反复重装、下载不同大模型或无限换项目。可完成的独立部分继续。

## 参考了哪些相近 skill

这是自编的任务路由与执行流程，参考以下公开思路，不复制第三方实现、不要求安装它们，也不采用它们的子代理调度或 stars 硬阈值：

- [vercel-labs/skills 的 find-skills](https://github.com/vercel-labs/skills/blob/main/skills/find-skills/SKILL.md)：发现已有技能、围绕能力检索，适合补充 skill 发现环节；本身不是本地项目执行器。
- [everything-claude-code 的 search-first](https://github.com/affaan-m/everything-claude-code/blob/main/skills/search-first/SKILL.md)：先查现成方案，再决定直接采用、少量适配或实现；本 skill 加入用户指定本地库、下载位置与真实产物验收。

没有把任何推荐软件预下载到项目库。以后有实际任务再选所需工具；不能为了“完善工具箱”占用磁盘、安装后端或触发费用。
