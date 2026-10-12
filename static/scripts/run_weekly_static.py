"""轻量静态周报主编排：列表采集 → 关键词筛选 → 详情抓取 → 生成国家级 Excel。

用法：
    python3 scripts/run_weekly_static.py [--days 7] [--out-dir <dir>] [--only CODE1,CODE2]

产物（运行目录下）：
    run.json              本次运行元信息
    candidates.json       列表候选（含筛选判定）
    review_needed.json    需宿主 AI 搜索复查的条目（列表无详情/详情文字不足）
    analysis_request.json 正文已验收记录（交宿主 AI 生成摘要/分类）
    Police_<yymmdd>_Test_National.xlsx   仅当提供 analysis.json 时生成
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_static import (fetch, list_candidates, extract_detail, keyword_decision,
                            normalize_url, clean)
from list_adapters import fetch_list


def load_sources(only=None):
    rows = json.loads((ROOT / "config" / "sources_national.json").read_text(encoding="utf-8")).get("sources", [])
    sources = [s for s in rows if s.get("enabled", True)]
    if only:
        sources = [s for s in sources if s.get("code") in only]
    return sources


def run(days=7, out_dir=None, only=None, max_per_source=30):
    today = date.today()
    cutoff = today - timedelta(days=max(1, days) - 1)
    out_root = Path(out_dir).resolve() if out_dir else ROOT / "runs"
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = out_root / f"static_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence").mkdir(exist_ok=True)

    candidates, review_needed, source_status = [], [], []
    seen_urls = {}

    for source in load_sources(only):
        code = source.get("code", "")
        list_url = source.get("list_url") or source.get("website")
        # 优先走接口适配器（JS 动态渲染站点）；无适配器时走通用 HTML 解析
        adapter_result = fetch_list(source, max_per_source)
        if adapter_result is not None:
            links = adapter_result["items"]
            adapter = adapter_result["adapter"]
            if adapter_result["error"] or not links:
                err = adapter_result["error"] or "ADAPTER_EMPTY"
                source_status.append({"agency": code, "status": "Failed", "list_url": list_url,
                                      "adapter": adapter, "error": err})
                review_needed.append({"agency": code, "list_url": list_url, "kind": "LIST_FAILED",
                                      "reason": f"接口适配失败：{err}"})
                continue
            source_status.append({"agency": code, "status": "Listed", "list_url": list_url,
                                  "adapter": adapter, "candidates": len(links)})
            for link in links:
                if link.get("date") and (link["date"] < cutoff.isoformat() or link["date"] > today.isoformat()):
                    continue
                decision, reason = keyword_decision(link["title"], link.get("summary", ""))
                key = normalize_url(link["url"])
                if key in seen_urls:
                    continue
                seen_urls[key] = True
                candidates.append({"agency": code, "agency_name": source.get("chinese_name", ""),
                                   "title": link["title"], "summary": link.get("summary", ""),
                                   "issue_date": link.get("date", ""), "detail_url": link["url"],
                                   "list_url": list_url, "decision": decision, "reason": reason})
            continue

        page = fetch(list_url)
        if page["error"] or not page["text"]:
            source_status.append({"agency": code, "status": "Failed", "list_url": list_url,
                                  "error": page["error"] or "EMPTY_LIST_PAGE"})
            review_needed.append({"agency": code, "list_url": list_url, "kind": "LIST_FAILED",
                                  "reason": page["error"] or "EMPTY_LIST_PAGE"})
            continue
        (run_dir / "evidence" / f"{code.replace(' ', '_')}_list.html").write_bytes(page["content"])
        links = list_candidates(page["text"], page["final_url"], source, max_per_source)
        source_status.append({"agency": code, "status": "Listed", "list_url": list_url,
                              "candidates": len(links)})
        for link in links:
            if link.get("date") and (link["date"] < cutoff.isoformat() or link["date"] > today.isoformat()):
                continue
            decision, reason = keyword_decision(link["title"], link.get("summary", ""))
            key = normalize_url(link["url"])
            if key in seen_urls:
                continue
            seen_urls[key] = True
            candidates.append({"agency": code, "agency_name": source.get("chinese_name", ""),
                               "title": link["title"], "summary": link.get("summary", ""),
                               "issue_date": link.get("date", ""), "detail_url": link["url"],
                               "list_url": page["final_url"], "decision": decision, "reason": reason})

    # 详情抓取：只抓 Collect
    records, failed = [], []
    for cand in candidates:
        if cand["decision"] != "Collect":
            continue
        page = fetch(cand["detail_url"])
        if page["error"] or not page["text"]:
            failed.append({**cand, "error": page["error"] or "DETAIL_EMPTY"})
            review_needed.append({"agency": cand["agency"], "title": cand["title"],
                                  "detail_url": cand["detail_url"], "kind": "DETAIL_FAILED",
                                  "reason": page["error"] or "DETAIL_EMPTY"})
            continue
        key = cand["detail_url"].replace("/", "_").replace(":", "")[:120]
        (run_dir / "evidence" / (key + ".html")).write_bytes(page["content"])
        parsed = extract_detail(page["text"], page["final_url"], cand["title"],
                                source.get("body_selectors", []) if False else [])
        if not parsed["body_valid"]:
            failed.append({**cand, "error": parsed["validation_error"]})
            review_needed.append({"agency": cand["agency"], "title": cand["title"],
                                  "detail_url": cand["detail_url"], "kind": "BODY_INSUFFICIENT",
                                  "reason": parsed["validation_error"]})
            continue
        records.append({**cand, "title": parsed["title"] or cand["title"],
                        "issue_date": parsed["issue_date"] or cand["issue_date"],
                        "policy_number": parsed["policy_number"], "body_text": parsed["body_text"],
                        "attachments": parsed.get("attachments", []),
                        "evidence_path": str(run_dir / "evidence" / (key + ".html"))})

    # 边界候选（关键词无法确认）也交 AI 复查
    for cand in candidates:
        if cand["decision"] == "Review":
            review_needed.append({"agency": cand["agency"], "title": cand["title"],
                                  "detail_url": cand["detail_url"], "kind": "TOPIC_UNCONFIRMED",
                                  "reason": cand["reason"]})

    meta = {"run_id": run_id, "level": "National", "generated_at": datetime.now().isoformat(),
            "window_start": cutoff.isoformat(), "window_end": today.isoformat(),
            "source_count": len(load_sources(only)), "candidate_count": len(candidates),
            "verified_body_records": len(records), "failed_detail_records": len(failed),
            "review_needed": len(review_needed)}
    (run_dir / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "candidates.json").write_text(json.dumps({"run_id": run_id, "candidates": candidates},
                                                        ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "review_needed.json").write_text(json.dumps({"run_id": run_id, "items": review_needed},
                                                           ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "failed_details.json").write_text(json.dumps({"run_id": run_id, "records": failed},
                                                            ensure_ascii=False, indent=2), encoding="utf-8")
    # analysis_request：正文已验收记录
    request = {"run_id": run_id, "level": "National",
               "dictionary": json.loads((ROOT / "data" / "mi_dictionary.json").read_text(encoding="utf-8")),
               "records": [{k: r.get(k, "") for k in
                            ("agency", "agency_name", "title", "issue_date", "policy_number",
                             "body_text", "detail_url", "list_url", "evidence_path")} for r in records]}
    # 附件链接随记录一并写入（供成表标注）
    for rec, src in zip(request["records"], records):
        rec["attachments"] = src.get("attachments", [])
    (run_dir / "analysis_request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")

    print(json.dumps({"run_dir": str(run_dir), "run_id": run_id, "candidate_count": len(candidates),
                      "verified_body_records": len(records), "failed": len(failed),
                      "review_needed": len(review_needed)}, ensure_ascii=False))
    return run_dir


def main():
    parser = argparse.ArgumentParser(description="轻量静态国家级周报采集")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--only", default="")
    parser.add_argument("--max-per-source", type=int, default=30)
    args = parser.parse_args()
    only = {c.strip() for c in args.only.split(",") if c.strip()} or None
    run(days=args.days, out_dir=args.out_dir or None, only=only, max_per_source=args.max_per_source)


if __name__ == "__main__":
    raise SystemExit(main())
