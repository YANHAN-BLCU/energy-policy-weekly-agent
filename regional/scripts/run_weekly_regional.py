"""轻量静态省市级周报主编排：列表采集 → 关键词筛选 → 详情抓取 → 生成省市级 Excel。

与国家级（policy-weekly-static）共用同一套静态引擎（collect_static.py / list_adapters.py），
差异仅在来源配置与按 class 分流的请求策略：
  class A（静态直取）：默认 UA 直接请求。
  class E（静态排除）：JS 动态防护（412/473），不进静态队列，单列 search_sources.json 交 AI 搜索。

支持定向查询：--province 只跑指定省份/大区的相关站点（不跑全量）。

用法：
    python3 scripts/run_weekly_regional.py [--days 7] [--out-dir <dir>] [--only CODE1,CODE2]
                                           [--province 广东] [--class A,E] [--max-per-source 30]

产物（运行目录下）：
    run.json / candidates.json / review_needed.json / failed_details.json
    analysis_request.json / search_sources.json
    Police_<yymmdd>_Test_<省名|Regional>.xlsx   仅当提供 analysis.json 时生成
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import collect_static as CS
from collect_static import fetch, list_candidates, extract_detail, keyword_decision, normalize_url
from list_adapters import fetch_list
from provinces import resolve_province

CONFIG = ROOT / "config" / "sources_regional.json"

# C 类网关阻断用备选 UA / 请求头，仍走纯 requests，不启用浏览器
UA_POOL = [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"),
]


def fetch_with_fallback(url, source, timeout=15):
    """class C（JS 动态防护）：换 UA / 补请求头重试。

    实测（2026-10-12）：甘肃/湖北/青海等站返回 412/473 由 JS 动态防护（如瑞数
    $_ts 挑战）产生，换 UA / Referer / Cookie 均无效，纯静态无法绕过。此处仍做
    一次轻量换 UA 尝试（成本低、个别站点可能有效），失败即返回，由上层记
    GATEWAY_BLOCKED 交宿主 AI 搜索复查。
    """
    last = fetch(url, timeout=timeout)
    if not last.get("error") or last.get("status") not in (None, 403, 412, 444, 473):
        return last
    for ua in UA_POOL:
        try:
            import requests
            resp = requests.get(url, timeout=timeout, allow_redirects=True, headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": source.get("website", ""),
                "Connection": "keep-alive",
            })
            ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if resp.status_code in (403, 412, 444, 473) or ctype not in CS.TEXT_TYPES:
                last = {"url": url, "final_url": resp.url, "status": resp.status_code,
                        "text": "", "content": b"", "content_type": ctype,
                        "error": f"HTTP_{resp.status_code}"}
                continue
            enc = resp.encoding or resp.apparent_encoding or "utf-8"
            text = resp.content.decode(enc, errors="replace")
            return {"url": url, "final_url": resp.url, "status": resp.status_code, "text": text,
                    "content": resp.content, "content_type": ctype, "error": ""}
        except Exception as exc:  # noqa: BLE001
            last = {"url": url, "final_url": url, "status": None, "text": "", "content": b"",
                    "content_type": "", "error": str(exc)[:200]}
    return last


def fetch_for(url, source, timeout=15):
    if source.get("class") == "C":
        return fetch_with_fallback(url, source, timeout=timeout)
    return fetch(url, timeout=timeout)


def load_all_sources():
    """读全部来源（含 enabled=false 的 E 类），用于省份匹配与搜索清单。"""
    return json.loads(CONFIG.read_text(encoding="utf-8")).get("sources", [])


def match_province(sources, province_text):
    """按省份/大区过滤来源（含 E 类）。返回 (匹配来源, 解析结果)。"""
    r = resolve_province(province_text)
    if not r:
        return [], r
    out = []
    for s in sources:
        pref = s.get("code", "").split()[0]
        if pref in r["codes"] or (r["regions"] and s.get("region") in r["regions"]):
            out.append(s)
    return out, r


def load_sources(only=None, classes=None, province=None):
    """静态采集队列：仅 enabled=true；再按 class / only / province 过滤。"""
    rows = load_all_sources()
    sources = [s for s in rows if s.get("enabled", True)]
    if classes:
        sources = [s for s in sources if s.get("class") in classes]
    if only:
        sources = [s for s in sources if s.get("code") in only]
    if province:
        matched, _ = match_province(sources, province)
        sources = matched
    return sources


def run(days=7, out_dir=None, only=None, classes=None, province=None, max_per_source=30):
    today = date.today()
    cutoff = today - timedelta(days=max(1, days) - 1)
    out_root = Path(out_dir).resolve() if out_dir else ROOT / "runs"
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = out_root / f"static_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence").mkdir(exist_ok=True)

    # 省份标签：用于产出文件名与元信息
    province_label = ""
    if province:
        r = resolve_province(province)
        province_label = (r or {}).get("label", province) if r else province

    candidates, review_needed, source_status = [], [], []
    seen_urls = {}

    sources = load_sources(only, classes, province)
    for source in sources:
        code = source.get("code", "")
        list_url = source.get("list_url") or source.get("website")
        adapter_result = fetch_list(source, max_per_source)
        if adapter_result is not None and not adapter_result.get("error") and adapter_result.get("items"):
            links = adapter_result["items"]
            adapter = adapter_result["adapter"]
            source_status.append({"agency": code, "class": source.get("class", ""), "status": "Listed",
                                  "list_url": list_url, "adapter": adapter, "candidates": len(links)})
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

        page = fetch_for(list_url, source)
        if page["error"] or not page["text"]:
            err = page["error"] or "EMPTY_LIST_PAGE"
            kind = "GATEWAY_BLOCKED" if source.get("class") == "C" else "LIST_FAILED"
            source_status.append({"agency": code, "class": source.get("class", ""), "status": "Failed",
                                  "list_url": list_url, "error": err})
            review_needed.append({"agency": code, "list_url": list_url, "kind": kind,
                                  "reason": f"列表页抓取失败：{err}"
                                            + ("（已换 UA 重试仍被网关阻断）" if kind == "GATEWAY_BLOCKED" else "")})
            continue
        (run_dir / "evidence" / f"{code.replace(' ', '_')}_list.html").write_bytes(page["content"])
        links = list_candidates(page["text"], page["final_url"], source, max_per_source)
        source_status.append({"agency": code, "class": source.get("class", ""), "status": "Listed",
                              "list_url": list_url, "candidates": len(links)})
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

    # 详情抓取：只抓 Collect，按来源 class 选择请求策略
    by_code = {s.get("code"): s for s in sources}
    records, failed = [], []
    for cand in candidates:
        if cand["decision"] != "Collect":
            continue
        source = by_code.get(cand["agency"], {})
        page = fetch_for(cand["detail_url"], source)
        if page["error"] or not page["text"]:
            failed.append({**cand, "error": page["error"] or "DETAIL_EMPTY"})
            review_needed.append({"agency": cand["agency"], "title": cand["title"],
                                  "detail_url": cand["detail_url"], "kind": "DETAIL_FAILED",
                                  "reason": page["error"] or "DETAIL_EMPTY"})
            continue
        key = cand["detail_url"].replace("/", "_").replace(":", "")[:120]
        (run_dir / "evidence" / (key + ".html")).write_bytes(page["content"])
        parsed = extract_detail(page["text"], page["final_url"], cand["title"], [])
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

    for cand in candidates:
        if cand["decision"] == "Review":
            review_needed.append({"agency": cand["agency"], "title": cand["title"],
                                  "detail_url": cand["detail_url"], "kind": "TOPIC_UNCONFIRMED",
                                  "reason": cand["reason"]})

    meta = {"run_id": run_id, "level": "Regional", "generated_at": datetime.now().isoformat(),
            "window_start": cutoff.isoformat(), "window_end": today.isoformat(),
            "province": province_label, "scope": "province" if province else "all",
            "source_count": len(sources), "candidate_count": len(candidates),
            "verified_body_records": len(records), "failed_detail_records": len(failed),
            "review_needed": len(review_needed), "source_status": source_status}
    (run_dir / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "candidates.json").write_text(json.dumps({"run_id": run_id, "candidates": candidates},
                                                        ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "review_needed.json").write_text(json.dumps({"run_id": run_id, "items": review_needed},
                                                           ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "failed_details.json").write_text(json.dumps({"run_id": run_id, "records": failed},
                                                            ensure_ascii=False, indent=2), encoding="utf-8")
    request = {"run_id": run_id, "level": "Regional", "province": province_label,
               "dictionary": json.loads((ROOT / "data" / "mi_dictionary.json").read_text(encoding="utf-8")),
               "records": [{k: r.get(k, "") for k in
                            ("agency", "agency_name", "title", "issue_date", "policy_number",
                             "body_text", "detail_url", "list_url", "evidence_path")} for r in records]}
    # 附件链接随记录一并写入（供成表标注）
    for rec, src in zip(request["records"], records):
        rec["attachments"] = src.get("attachments", [])
    (run_dir / "analysis_request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2),
                                                   encoding="utf-8")

    # 静态排除站点（E 类）：不进静态队列，单独输出搜索直采清单交宿主 AI
    # 单省查询时，搜索清单同样只保留该省的 E 类站点
    search_cfg = ROOT / "config" / "search_sources.json"
    search_sources = json.loads(search_cfg.read_text(encoding="utf-8")).get("sources", []) if search_cfg.exists() else []
    if province:
        search_sources, _ = match_province(search_sources, province)
    (run_dir / "search_sources.json").write_text(
        json.dumps({"run_id": run_id, "province": province_label, "count": len(search_sources),
                    "sources": search_sources}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"run_dir": str(run_dir), "run_id": run_id, "province": province_label,
                      "source_count": len(sources), "candidate_count": len(candidates),
                      "verified_body_records": len(records), "failed": len(failed),
                      "review_needed": len(review_needed),
                      "search_only_sources": len(search_sources)}, ensure_ascii=False))
    return run_dir


def main():
    parser = argparse.ArgumentParser(description="轻量静态省市级周报采集")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--only", default="")
    parser.add_argument("--province", default="", help="定向查询：省名/简称/代码前缀/大区，如 广东/粤/GD/华东")
    parser.add_argument("--class", dest="classes", default="")
    parser.add_argument("--max-per-source", type=int, default=30)
    args = parser.parse_args()
    only = {c.strip() for c in args.only.split(",") if c.strip()} or None
    classes = {c.strip().upper() for c in args.classes.split(",") if c.strip()} or None
    run(days=args.days, out_dir=args.out_dir or None, only=only, classes=classes,
        province=args.province or None, max_per_source=args.max_per_source)


if __name__ == "__main__":
    raise SystemExit(main())
