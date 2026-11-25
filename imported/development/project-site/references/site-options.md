# 选型与样站

## 先看项目现有结构

| 方案 | 采用条件 |
| --- | --- |
| 现有站点 | 首选。利用当前发布路径、品牌组件、真相源和框架已有的本地化能力。 |
| 随附静态样站 | 新站以介绍和几页手册为主，首页需要独立视觉设计。只需 Node.js 构建，输出纯静态文件，无 npm 依赖。 |
| Astro + Starlight | 新站有多页 Markdown/MDX 文档，需要侧栏、本地搜索和多语言菜单。可用 Astro 做独立首页，或从 Starlight 的 splash 页面起步。 [官方入门](https://starlight.astro.build/getting-started/) · [本地化](https://starlight.astro.build/guides/i18n/) |
| VitePress | 现有 Vue/VitePress 项目，或文档以 Markdown 为主且默认主题已经够用。为各语言配置导航、侧栏和 UI 标签。 [首页](https://vitepress.dev/reference/default-theme-home-page) · [本地化](https://vitepress.dev/guide/i18n) |
| Docusaurus | 现有 Docusaurus 项目，或团队需要维护多个发行版的文档和译文，已有 React 工作流。 [官方本地化指南](https://docusaurus.io/docs/i18n/tutorial) |

## 使用静态样站

[assets/starter](../assets/starter/) 是以 `project-site` 本身为内容的可运行中英文样站。参考它在真实页面展示路由的思路，按当前项目决定视觉与内容。复制源文件到项目自有站点目录，替换 `content.mjs` 中两种文案和项目名。首页、手册节奏和静态链接在 `build.mjs`，颜色和排版在 `site.css`。项目已有文档源时改为复用对应文档。最后核对所有示例文案和命令都已换成当前项目内容。

在样站或复制后的目录运行：

```bash
node build.mjs
python3 -m http.server 4173 --bind 127.0.0.1 --directory dist
```

打开 `http://127.0.0.1:4173/`。构建自检验证站内链接、页面配对目标和共享锚点。普通语言链接可在禁用 JS 时切换页面，`site.js` 为配对的章节附带深链接。资源使用相对路径。发布时将 `PROJECT_SITE_URL` 设为已核实、以斜杠结尾的生产站点根 URL，重新构建以写入 canonical 和交替语言链接。只发布 `dist/`。

## 已筛选的参考

- ScrewFast 将独立展示页与 Starlight 文档放在同一项目。展示页为英语和法语，文档含简体中文。浅克隆位于 `/Users/xi/dev2/agent-skills/GitHub-xiangmu/ScrewFast`，核对的是 `b17aca4` 的 README、MIT LICENSE、Astro 配置与语言路由。样站借鉴共享视图和独立译文的组织方式，依赖清单、主题和素材由目标项目决定。 [ScrewFast 源码](https://github.com/mearashadowfax/ScrewFast/tree/b17aca4)
- 用户本机案例 G Skills（`kaifa/gearbox/site`）用源码与 README 生成静态介绍和手册。DSH（`GitHub-xiangmu/dsh-desktop/deepseek-harness/website`）已有 VitePress 双语路由和分别配置的中英文导航。二者可作为不同规模的实现参考。
- Anthropic 的 `frontend-design` 提供从项目实际内容推导视觉方向的工作法。Vercel 的 `web-interface-guidelines` 适合补查键盘、焦点与响应式问题。当前技能内已经整理了本类站点的设计和验收步骤。 [frontend-design](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md) · [Web Interface Guidelines](https://github.com/vercel-labs/web-interface-guidelines)
