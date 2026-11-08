---
name: pdf-mineru-extract
description: 使用 MinerU 在线 API 将 PDF（或 docx/ppt/图片）转换为高保真 Markdown，保留图片（fig）、表格、公式素材，用于文献深度解读、论文精读、引用原文图片（fig）等需要高质量结构化解析的场景。用户上传 PDF/文献并期望引用原图、还原表格公式，或需要比纯文本提取更完整的文档结构时使用。
---

# PDF → Markdown（MinerU）

## 何时使用

用户上传 PDF 并期望深度解读、引用原文图片（fig）、还原表格/公式，或需要完整文档结构时，优先用本技能（比基础文本提取更保真，且带图片素材）。

## 快速开始

1. 解析（输出目录默认建在输入文件旁 `<名称>_mineru/`）：

```bash
python3 <本技能目录>/scripts/parse_pdf.py <input.pdf> --output <输出目录>
```

2. 产物：`markdown.md` + `images/`（`page_N_image_M.png` 等图片/表格/公式素材）+ 中间 JSON。
3. 解读：Read markdown 全文；markdown 中 `![描述](images/xxx.png)` 即图片引用，按需 Read 对应图片（细节不清时提高 `thumbnail_size`）。

## 参数

| 参数 | 说明 |
| --- | --- |
| `--model vlm`（默认）| vlm 精度更高；`pipeline` 更快 |
| `--ocr` | 扫描版/图片型 PDF 开启 OCR |
| `--pages 1-10` | 只解析指定页 |
| `--timeout 600` | 总等待上限（秒） |
| `--flash` | Agent 轻量接口：免 token、≤10MB、≤20 页、仅文本无图片（降级） |
| `--token` | 临时指定 token（默认读 `MINERU_TOKEN` 或技能目录 `.token`） |

## Token 管理

- 用户的 MinerU API token 已保存在技能目录 `.token`（权限 600），脚本自动读取；环境变量 `MINERU_TOKEN` 优先级更高，`--token` 最高。
- token 是私密凭据：不得写入回复、交付物、日志或文档；脚本 stdout 不回显 token。
- token 有效期约 90 天，过期后需用户到 https://mineru.net/apiManage/token 重新申请并更新 `.token`（或设置 MINERU_TOKEN）。

## 工作流

1. 精准解析（默认）：官方 SDK（mineru-open-sdk）提交 → 轮询至 done → 保存 markdown 与 images/。SDK 不可用或失败时自动降级为 requests 直连 v4 API（`/api/v4/file-urls/batch` 签名上传 → `/api/v4/extract-results/batch/{batch_id}` 轮询 → 下载 zip 解压）。
2. 任务状态：`done`=成功；`failed`=解析失败（读 err_msg，可重试一次）；超时=增大 `--timeout` 或按 `--pages` 分页。
3. 图片素材：`images/` 下按页号与块号命名（如 `page_0_image_1.png`）；markdown 引用路径与文件一一对应；引用图时直接 Read 本地图片。
4. 输出目录落在用户项目目录（勿放 /tmp）；后续交付 HTML/PPT/表格需引用图片时，先上传图片获取 URL 再引用。
5. 解析失败时如实报告原因与重试建议，不静默降级为纯文本。
