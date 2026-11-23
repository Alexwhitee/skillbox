# 兼容性实测数据

实测方式：用 puppeteer 加载各版本 `mermaid` 官方发行文件，对每个写法调用 `mermaid.parse()`；超过 4 秒没返回记为卡死（HG）。测试日期 2026-11。表格是实测结果，不要凭印象改动。

## 1. 关键字的版本差异

| 开头写法 | 7.1 | 8.0 | 8.4 | 8.6 | 8.8 | 8.13 | 9.1 | 10.9 | 12 |
|---|---|---|---|---|---|---|---|---|---|
| `graph LR` | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| `flowchart LR` | XX | XX | XX | ok | ok | ok | ok | ok | ok |

结论：一律写 `graph`。`graph` 从 7.1 到 12 全部可用，`flowchart` 在 8.4 及以下直接报错。

## 2. 图内写法的版本差异

| 写法 | 7.1 | 8.0 | 8.4 | 8.6 | 8.8 | 8.13 | 9.1 | 10.9 | 12 |
|---|---|---|---|---|---|---|---|---|---|
| 裸文字：中文 / 英文 / 数字 / 空格 | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| 裸文字含 `，` `。` `：` `、` `（）` `《》` `“”` | XX | XX | XX | XX | XX | XX | XX | ok | ok |
| 裸文字含 `①` `≥` `×` `−` `→` `·` `…` `％` | XX | XX | XX | XX | XX | XX | XX | ok | ok |
| 裸文字含 `;` `~` `@` | XX | XX | XX | XX | XX | XX | XX | ok | ok |
| 裸文字含 `,` `:` `.` `-` `+` `=` `/` `%` `?` `!` `'` `` ` `` | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| 裸文字含 `(` `)` `[` `]` `{` `}` `\|` `"` | XX | XX | XX | XX | XX | XX | XX | HG | HG |
| 加引号 `A["任意文字"]` | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| `<br/>` 换行 | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| `style A fill:...` | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| `classDef` + `class` | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| `subgraph` 分组 | XX | XX | ok | ok | ok | ok | ok | ok | ok |
| `A & B --> C` 并列 | XX | XX | ok | ok | ok | ok | ok | ok | ok |
| `-->|文字|` 边标签 | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| `-- 文字 -->` 边标签 | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| `-.->` / `==>` | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| `A{文字?}` 菱形 | ok | ok | ok | ok | ok | ok | ok | ok | ok |
| 边标签里的 `( )` | XX | XX | XX | XX | XX | XX | XX | HG | HG |
| `%%` 注释 | ok | ok | ok | ok | ok | ok | ok | ok | ok |

"XX" = 解析失败，"HG" = 解析卡死（图永远出不来，比报错更糟）。

## 3. 图表类型的起始版本

| 类型 | 实测起始版本 | 能否用于"任意老环境" |
|---|---|---|
| `graph` | 7.1 | 可以 |
| `sequenceDiagram` | 7.1 | 可以 |
| `classDiagram` | 7.1 | 可以 |
| `gantt` | 7.1 | 可以 |
| `pie` | 8.4 | 谨慎，最好换成表 |
| `erDiagram` | 8.6 | 谨慎 |
| `stateDiagram-v2` | 8.6 | 谨慎 |
| `journey` | 8.6 | 谨慎 |
| `gitGraph` | 9.0 | 不要用 |
| `C4Context` | 9.0 | 不要用 |
| `quadrantChart` | 9.1（老版本卡死） | 不要用，改两行两列表 |
| `xychart-beta` | 10.4 | 不要用，改表格加 █ |
| `mindmap` / `timeline` / `block-beta` | 10.x | 不要用 |
| `sankey-beta` | 10.9 起也不稳 | 不要用 |

## 4. 编辑器侧的坑（实测过，和 mermaid 版本无关）

- **行首缩进被改写成 `&#160;`**：某些 markdown 编辑器把代码块内容当 HTML 处理，把行首两个空格变成 HTML 实体。实测在 mermaid 10.9 / 12 下直接卡死，图不渲染、原文照显示。对策：mermaid 块内每一行顶格写。
- **引号被转义成 `&quot;`**：同样的处理逻辑会把 `"` 转义。`A["甲"]` 会变成 `A[&quot;甲&quot;]`，标签里显示出 `&quot;`。对策：不用引号。
- **`<details>` 折叠块**：老渲染器可能不认，直接把 `<details>` 当文字显示。外部网站发布前先确认。
- **本地相对路径的图片**：`![](assets/x.png)` 复制到别的网站不会自动带过去，需要先上传图片再改链接。

## 5. 无法测到的部分

上面测的是官方 mermaid 发行版。个别编辑器用的是裁剪版或魔改版（比如只打包了 flowchart），遇到这类环境只能靠"只用最老的语法"加"人工确认"兜底。
