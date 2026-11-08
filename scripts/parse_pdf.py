#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MinerU 文档解析：PDF（或 docx/ppt/图片）→ 高保真 Markdown + 图片素材。

用法：
  python3 parse_pdf.py paper.pdf --output ./parsed/paper
  python3 parse_pdf.py paper.pdf --pages 1-10 --model vlm
  python3 parse_pdf.py scan.pdf --ocr
  python3 parse_pdf.py big.pdf --flash        # 免 token 降级（<=10MB、<=20页，仅文本无图片）

输出：<输出目录>/markdown.md（或 full.md）+ images/（图片/表格/公式素材）+ 中间 JSON。
stdout 末尾输出 JSON 摘要（ok/task_id/state/输出路径/图片清单），供调用方解析。
"""
import argparse
import json
import os
import sys
import time
import uuid

API_BASE = "https://mineru.net"
TOKEN_FILE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".token"))

IMG_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def resolve_token(opt):
    if opt:
        return opt
    t = os.environ.get("MINERU_TOKEN")
    if t:
        return t
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, encoding="utf-8") as f:
            t = f.read().strip()
        if t:
            return t
    return None


def save_markdown_and_images(outdir, md_text, images):
    """手动保存 markdown 与图片素材（save_all 不可用时的降级）。"""
    os.makedirs(outdir, exist_ok=True)
    md_path = os.path.join(outdir, "markdown.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text or "")
    img_dir = os.path.join(outdir, "images")
    os.makedirs(img_dir, exist_ok=True)
    saved = []
    for img in images or []:
        try:
            name = getattr(img, "filename", None) or getattr(img, "name", None) or getattr(img, "path", None)
            if not name:
                name = "img_%d.png" % len(saved)
            base = os.path.basename(name)
            save_fn = getattr(img, "save", None)
            if save_fn:
                save_fn(os.path.join(img_dir, base))
                saved.append(os.path.join("images", base))
        except Exception:
            continue
    return md_path, saved


def run_sdk(args, token):
    """主路径：官方 mineru-open-sdk。"""
    try:
        from mineru import MinerU
    except ImportError:
        raise RuntimeError("SDK 未安装：pip install mineru-open-sdk")

    if token:
        client = MinerU(token)
    else:
        client = MinerU()  # 无 token 时 SDK 仅支持 flash
    result = client.extract(
        args.input,
        model=args.model,
        ocr=args.ocr or None,
        pages=args.pages or None,
        timeout=args.timeout,
    )
    state = getattr(result, "state", "")
    if state not in ("done", "success"):
        raise RuntimeError("解析未完成或失败，state=%s" % state)

    outdir = args.output
    os.makedirs(outdir, exist_ok=True)
    saved_images = []
    if hasattr(result, "save_all"):
        try:
            result.save_all(outdir)
        except Exception:
            pass
    # 确认 markdown 落盘
    md_path = os.path.join(outdir, "markdown.md")
    if not os.path.exists(md_path):
        md_text = getattr(result, "markdown", "") or ""
        md_path, saved_images = save_markdown_and_images(outdir, md_text, getattr(result, "images", []) or [])
    # 汇总图片清单（save_all 产物路径）
    img_dir = os.path.join(outdir, "images")
    if os.path.isdir(img_dir):
        for fn in sorted(os.listdir(img_dir)):
            if fn.lower().endswith(IMG_EXTS):
                saved_images.append(os.path.join("images", fn))
    return state, md_path, saved_images


def run_requests(args, token):
    """降级路径：requests 直连 v4 API（file-urls/batch 签名上传 + 轮询 batch）。"""
    import requests

    if not token:
        raise RuntimeError("精准解析需要 token（--token / MINERU_TOKEN / 技能目录 .token）")

    headers = {"Authorization": "Bearer %s" % token, "Content-Type": "application/json"}
    payload = {
        "files": [{"name": os.path.basename(args.input), "data_id": uuid.uuid4().hex[:16]}],
        "model_version": args.model,
    }
    if args.ocr:
        payload["is_ocr"] = True
    if args.pages:
        payload["page_ranges"] = args.pages
    resp = requests.post(API_BASE + "/api/v4/file-urls/batch", headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError("申请上传链接失败: %s" % body.get("msg"))
    batch_id = body["data"]["batch_id"]
    file_url = body["data"]["file_urls"][0]

    with open(args.input, "rb") as f:
        up = requests.put(file_url, data=f, timeout=600)
    if up.status_code not in (200, 201):
        raise RuntimeError("文件上传失败，HTTP %d" % up.status_code)

    deadline = time.time() + args.timeout
    task_id = None
    while time.time() < deadline:
        time.sleep(5)
        q = requests.get(API_BASE + "/api/v4/extract-results/batch/%s" % batch_id, headers=headers, timeout=60)
        q.raise_for_status()
        qb = q.json()
        items = (qb.get("data") or {}).get("extract_result", []) or []
        if not items:
            continue
        item = items[0]
        task_id = item.get("task_id") or task_id
        state = item.get("state", "pending")
        if state == "done":
            zip_url = item.get("full_zip_url")
            if not zip_url:
                raise RuntimeError("任务完成但无 full_zip_url")
            return download_zip(zip_url, args.output, task_id, headers)
        if state == "failed":
            raise RuntimeError("解析失败: %s" % (item.get("err_msg") or ""))
    raise RuntimeError("轮询超时（--timeout %d）" % args.timeout)


def download_zip(zip_url, outdir, task_id, headers=None):
    import zipfile

    import requests
    r = requests.get(zip_url, timeout=600)
    r.raise_for_status()
    os.makedirs(outdir, exist_ok=True)
    zip_path = os.path.join(outdir, "mineru_result.zip")
    with open(zip_path, "wb") as f:
        f.write(r.content)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(outdir)
    os.remove(zip_path)
    md_path = None
    for cand in ("full.md", "markdown.md"):
        p = os.path.join(outdir, cand)
        if os.path.exists(p):
            md_path = p
            break
    saved_images = []
    img_dir = os.path.join(outdir, "images")
    if os.path.isdir(img_dir):
        for fn in sorted(os.listdir(img_dir)):
            if fn.lower().endswith(IMG_EXTS):
                saved_images.append(os.path.join("images", fn))
    return "done", md_path, saved_images


def run_flash(args):
    """Agent 轻量接口：免 token、<=10MB、<=20页，仅 Markdown（无图片）。"""
    import requests

    data = {"file_name": os.path.basename(args.input), "language": "ch"}
    if args.pages:
        data["page_range"] = args.pages
    resp = requests.post(API_BASE + "/api/v1/agent/parse/file", json=data, timeout=60)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError("flash 提交失败: %s" % body.get("msg"))
    task_id = body["data"]["task_id"]
    file_url = body["data"]["file_url"]
    with open(args.input, "rb") as f:
        up = requests.put(file_url, data=f, timeout=600)
    if up.status_code not in (200, 201):
        raise RuntimeError("flash 上传失败，HTTP %d" % up.status_code)

    deadline = time.time() + args.timeout
    markdown = None
    while time.time() < deadline:
        time.sleep(3)
        q = requests.get(API_BASE + "/api/v1/agent/parse/%s" % task_id, timeout=60)
        q.raise_for_status()
        qb = q.json()
        data = qb.get("data", {}) or {}
        state = data.get("state", "pending")
        if state in ("done", "success"):
            markdown = data.get("markdown_url") or data.get("full_content")
            break
        if state == "failed":
            raise RuntimeError("flash 解析失败: %s" % (data.get("err_msg") or qb.get("msg", "")))
    if not markdown:
        raise RuntimeError("flash 轮询超时（--timeout %d）" % args.timeout)

    os.makedirs(args.output, exist_ok=True)
    if markdown.startswith("http"):
        md_text = requests.get(markdown, timeout=120).text
    else:
        md_text = markdown
    md_path = os.path.join(args.output, "markdown.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)
    return "done", md_path, []


def main():
    ap = argparse.ArgumentParser(description="MinerU 文档解析：PDF→Markdown+图片")
    ap.add_argument("input", help="本地文件路径（PDF/doc/docx/ppt/pptx/图片/html）")
    ap.add_argument("--output", "-o", default=None, help="输出目录（默认：输入旁 <名称>_mineru/）")
    ap.add_argument("--token", default=None, help="MinerU token（默认读 MINERU_TOKEN 或技能目录 .token）")
    ap.add_argument("--model", default="vlm", choices=["vlm", "pipeline"], help="解析模型，默认 vlm（推荐）")
    ap.add_argument("--ocr", action="store_true", help="开启 OCR（扫描版/图片型 PDF）")
    ap.add_argument("--pages", default=None, help="页码范围，如 1-10 或 2,4-6")
    ap.add_argument("--timeout", type=int, default=600, help="总等待秒数，默认 600")
    ap.add_argument("--flash", action="store_true", help="Agent 轻量接口：免 token、<=10MB、<=20页、仅文本无图片")
    ap.add_argument("--no-sdk", action="store_true", help="强制走 requests 直连 v4 API（测试/降级用）")
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        print(json.dumps({"ok": False, "error": "输入文件不存在: %s" % args.input}, ensure_ascii=False))
        sys.exit(1)

    if args.output is None:
        base, _ = os.path.splitext(os.path.abspath(args.input))
        args.output = base + "_mineru"

    token = resolve_token(args.token)
    started = time.time()
    try:
        if args.flash:
            state, md_path, images = run_flash(args)
        elif args.no_sdk or token is None:
            state, md_path, images = run_requests(args, token)
        else:
            try:
                state, md_path, images = run_sdk(args, token)
            except RuntimeError:
                raise
            except Exception as e:
                print(json.dumps({"ok": False, "error": "SDK 路径失败: %s，改用 requests" % e}, ensure_ascii=False))
                state, md_path, images = run_requests(args, token)
        print(json.dumps({
            "ok": True,
            "task_state": state,
            "output_dir": args.output,
            "markdown_path": md_path,
            "images": images,
            "images_count": len(images),
            "duration_sec": int(time.time() - started),
        }, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "duration_sec": int(time.time() - started),
        }, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
