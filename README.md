# pdf-mineru-extract

> 把 PDF（以及 docx / ppt / 图片 / html）转成高保真 Markdown 的 Skill——保留原文图片、表格与公式，适合论文精读、文献解读时引用原图。

[MinerU](https://mineru.net) 官方解析能力封装成的一个可直接使用的 Agent Skill（Claude Code / 豆包类 skills 目录通用），核心是一个零依赖膨胀的单文件脚本 `scripts/parse_pdf.py`。

## 它解决什么问题

普通 PDF 文本提取（`pdftotext`、PyPDF）拿到的是"塌掉"的纯文本：表格变乱码、公式变符号噪点、图片全部丢失。做文献精读时，往往需要**引用原文的图和表**，纯文本提取做不到。

本 Skill 调用 MinerU 的文档解析服务，输出：

- `markdown.md` —— 保留标题层级、表格、公式（LaTeX）、图片引用的结构化正文
- `images/` —— 正文里的图、表、公式素材，按页号与块号命名（如 `page_0_image_1.png`）
- 中间 JSON —— 任务与解析元信息

markdown 中的 `![...](images/xxx.png)` 与本地文件一一对应，可以直接按路径引用、上传或嵌入 PPT/网页。

## 特性

- **双通道 + 自动降级**：优先走官方 SDK（`mineru-open-sdk`）；SDK 不可用或失败时自动切换到 requests 直连 v4 API（签名上传 → 轮询 batch → 下载 zip 解压），结果一致。
- **两种解析模型**：`vlm`（默认，精度更高）/ `pipeline`（更快）。
- **免 token 的轻量通道**：`--flash` 走 Agent 轻量接口，≤10MB、≤20 页，仅返回文本（无图片），应急用。
- **细粒度控制**：`--pages` 指定页码、`--ocr` 处理扫描件、`--timeout` 控制总等待。
- **token 不进 stdout、不进仓库**：优先级 `--token` > 环境变量 `MINERU_TOKEN` > 本地 `.token` 文件。

## 安装

把整个目录放进你的 skills 目录即可（以 Claude Code 为例）：

```bash
git clone https://github.com/LinNanzhen/pdf-mineru-extract.git \
  ~/.claude/skills/pdf-mineru-extract
```

依赖（仅 `--flash` 之外的通道需要）：

```bash
pip install requests
pip install mineru-open-sdk   # 可选，装了走 SDK 主路径
```

## 配置 token

精准解析需要 MinerU API token（[申请地址](https://mineru.net/apiManage/token)，有效期约 90 天）。二选一：

```bash
# 方式一：环境变量（推荐）
export MINERU_TOKEN="your-token-here"

# 方式二：技能目录下的 .token 文件
printf '%s' "your-token-here" > pdf-mineru-extract/.token && chmod 600 pdf-mineru-extract/.token
```

`.token` 已在 `.gitignore` 中排除，不会被误提交。

## 用法

```bash
# 基础：输出到 <文件名>_mineru/
python3 scripts/parse_pdf.py paper.pdf

# 指定输出目录
python3 scripts/parse_pdf.py paper.pdf --output ./parsed/paper

# 只解析前 10 页，用 pipeline 模型（更快）
python3 scripts/parse_pdf.py paper.pdf --pages 1-10 --model pipeline

# 扫描版 PDF 开 OCR
python3 scripts/parse_pdf.py scan.pdf --ocr

# 免 token 轻量解析（≤10MB、≤20 页、无图片）
python3 scripts/parse_pdf.py small.pdf --flash
```

`stdout` 末尾会输出一段 JSON 摘要（`ok` / `task_id` / `state` / 输出路径 / 图片清单），便于脚本或 Agent 解析结果。

### 参数

| 参数 | 说明 |
| --- | --- |
| `--output`, `-o` | 输出目录，默认输入旁 `<名称>_mineru/` |
| `--model` | `vlm`（默认，精度高）/ `pipeline`（更快） |
| `--ocr` | 开启 OCR，扫描版/图片型 PDF 必开 |
| `--pages` | 页码范围，如 `1-10`、`2,4-6` |
| `--timeout` | 总等待上限（秒），默认 600 |
| `--flash` | 走轻量接口：免 token、≤10MB、≤20 页、仅文本 |
| `--token` | 临时指定 token |
| `--no-sdk` | 强制走 requests 直连（测试/降级用） |

## 作为 Skill 使用

`SKILL.md` 是这个技能的说明书（frontmatter 含 `name` / `description`），装进 skills 目录后，Agent 在遇到"上传 PDF 并要求引用原图、还原表格公式"的场景会自动触发，按其中的工作流调用脚本。

## 许可

暂无。如需开源授权，建议补一个（如 MIT）。
