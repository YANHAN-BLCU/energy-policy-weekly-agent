"""Code stages invoked by an agent host; no model or mail credentials required."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import argparse
import json
import sys
import uuid

from .analysis import apply_analysis
from .collect import WeeklyCollector
from .export import export_workbook, policy_id
from .host_delivery import make_request, validate_receipt
from .models import Source
from .mi_checks import check_dictionary_assets, check_workbook
from .taxonomy import dictionary
from .paths import local_path, PACKAGE_ROOT
from .setup_wizard import run as run_setup, valid_time, EMAIL_RE, DAY_NAMES


def read_json(path):
    return json.loads(local_path(path, "读取路径", must_exist=True).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    path = local_path(path, "写入路径")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = local_path(path.with_name(path.name + ".tmp"), "临时 JSON 路径")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_installation(path):
    path = local_path(path, "安装配置路径")
    if not path.exists():
        raise ValueError("首次安装未完成：请由宿主收集邮箱、星期和时间，并执行 --setup")
    config = read_json(path)
    if not config.get("initialized") or not EMAIL_RE.fullmatch(config.get("delivery_email", "")):
        raise ValueError("首次安装缺少有效收件邮箱")
    if config.get("weekday") not in DAY_NAMES or not valid_time(config.get("trigger_time", "")):
        raise ValueError("首次安装缺少有效星期或触发时间")
    return config


def collect(args, installation):
    check_dictionary_assets(verify_manifest=True)
    config_path = local_path(args.config, "来源配置路径", must_exist=True)
    sources = [Source.from_dict(row) for row in read_json(config_path).get("sources", [])]
    only = {code.strip() for code in args.only.split(",") if code.strip()}
    sources = [source for source in sources if not only or source.code in only]
    out_dir = local_path(args.out_dir, "输出目录") if args.out_dir else PACKAGE_ROOT / "runs"
    state_path = out_dir / "state" / "seen_urls.json"
    seen = set(read_json(state_path).get("seen_urls", [])) if state_path.exists() else set()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    run_dir = out_dir / run_id
    collector = WeeklyCollector(run_dir / "evidence", use_browser=True)
    today = date.today()
    cutoff = today - timedelta(days=6)
    collector.discovery_limit = 30
    rows, statuses = collector.collect(sources, args.max_per_source, since=cutoff, until=today)
    scope_filtered = [row for status in statuses for row in status.get("scope_filtered", [])]
    records = []
    failed_details = []
    date_review = []
    outside_window = 0
    for row in rows:
        if not row.get("body_valid") or not row.get("body_text", "").strip() or row.get("review_status") == "Failed":
            failed_details.append(row)
            continue
        if row.get("detail_url") in seen:
            continue
        try:
            issued = date.fromisoformat(row.get("issue_date", ""))
        except ValueError:
            issued = None
        if issued and (issued < cutoff or issued > today):
            outside_window += 1
            continue
        if not issued:
            row["review_status"] = "Needs review"
            row["error"] = (row.get("error", "") + "; publication date unverified").strip("; ")
            date_review.append(row)
            continue
        row["policy_id"] = policy_id(row)
        records.append(row)
    meta = {
        "run_id": run_id,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(sources),
        "delivery_email": installation["delivery_email"],
        "weekday": installation["weekday"],
        "trigger_time": installation["trigger_time"],
        "window_start": cutoff.isoformat(),
        "window_end": today.isoformat(),
        "candidate_records": len(rows),
        "verified_body_records": len(rows) - len(failed_details),
        "failed_detail_records": len(failed_details),
        "date_unverified_records": len(date_review),
        "scope_filtered_records": len(scope_filtered),
        "scope_review_records": sum(row["decision"] == "Needs review" for row in scope_filtered),
        "failed_sources": sum(item.get("status") in {"Failed", "Partial", "Disabled", "ScopeReview"} for item in statuses),
        "new_records": len(records),
        "outside_window": outside_window,
        "state_file": str(state_path),
        "phase": "awaiting_analysis",
        "delivery_status": "pending",
    }
    write_json(run_dir / "run.json", {"meta": meta, "records": records, "statuses": statuses})
    write_json(run_dir / "failed_details.json", {"run_id": run_id, "records": failed_details})
    write_json(run_dir / "date_review.json", {"run_id": run_id, "records": date_review})
    write_json(run_dir / "scope_filtered.json", {"run_id": run_id, "records": scope_filtered})
    write_json(run_dir / "analysis_request.json", {
        "run_id": run_id,
        "mi_dictionary": dictionary(),
        "records": [
            {key: row.get(key, "") for key in (
                "policy_id", "title", "issue_date", "policy_number", "agency", "agency_name",
                "body_text", "detail_url", "evidence_path", "processing_evidence", "body_sources", "review_status", "error"
            )} for row in records
        ],
    })
    return {"run_dir": str(run_dir), "run_id": run_id, "new_records": len(records), "phase": meta["phase"]}


def finalize(args):
    check_dictionary_assets(verify_manifest=True)
    run_dir = local_path(args.run_dir, "运行目录", must_exist=True)
    data = read_json(run_dir / "run.json")
    meta = data["meta"]
    if meta.get("phase") != "awaiting_analysis":
        raise ValueError("Run already finalized: use existing delivery_request.json; do not resend sent runs")
    analysis_path = local_path(args.analysis_file, "分析文件路径", must_exist=True) if args.analysis_file else run_dir / "analysis.json"
    enriched = apply_analysis(data["records"], read_json(analysis_path), meta["run_id"])
    meta.update({"phase": "awaiting_delivery", "delivery_status": "pending"})
    data["records"] = enriched
    workbook = run_dir / "Policy_Weekly.xlsx"
    export_workbook(enriched, data["statuses"], workbook, meta)
    check_workbook(workbook)
    request = make_request(workbook, meta["delivery_email"], meta["run_id"], len(enriched),
                           meta.get("failed_sources", 0), meta.get("date_unverified_records", 0))
    write_json(run_dir / "delivery_request.json", request)
    write_json(run_dir / "run.json", data)
    return {"output": str(workbook), "delivery_request": str(run_dir / "delivery_request.json"), "phase": meta["phase"]}


def receipt(args):
    run_dir = local_path(args.run_dir, "运行目录", must_exist=True)
    data = read_json(run_dir / "run.json")
    meta = data["meta"]
    if meta.get("phase") not in {"awaiting_delivery", "delivered"}:
        raise ValueError("Run must be finalized before recording delivery")
    request = read_json(run_dir / "delivery_request.json")
    receipt_path = local_path(args.receipt_file, "发送回执路径", must_exist=True)
    result = validate_receipt(request, read_json(receipt_path))
    if meta.get("phase") == "delivered":
        saved = read_json(run_dir / "delivery_receipt.json")
        if result != saved:
            raise ValueError("Delivered run cannot accept a different receipt")
    if result["status"] == "sent":
        state_path = local_path(meta["state_file"], "去重状态路径")
        state = read_json(state_path) if state_path.exists() else {"seen_urls": []}
        successful = {row["detail_url"] for row in data["records"] if row.get("review_status") == "Collected"}
        state["seen_urls"] = sorted(set(state.get("seen_urls", [])) | successful)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        write_json(state_path, state)
    write_json(run_dir / "delivery_receipt.json", result)
    meta.update({
        "phase": "delivered" if result["status"] == "sent" else "awaiting_delivery",
        "delivery_status": result["status"],
        "delivery_transport": result["transport"],
        "delivery_error": result["error"],
    })
    write_json(run_dir / "run.json", data)
    # Preserve exact attachment bytes after the mail connector has sent them.
    return {"run_id": meta["run_id"], "delivery_status": result["status"], "phase": meta["phase"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="每周政策采集应用：宿主 AI 总结与邮件交付，无模型配置")
    parser.add_argument("--setup", action="store_true", help="保存首次安装信息")
    parser.add_argument("--email", default="")
    parser.add_argument("--weekday", default="")
    parser.add_argument("--time", default="")
    parser.add_argument("--stage", choices=["collect", "finalize", "receipt"], default="collect")
    parser.add_argument("--installation", default=str(PACKAGE_ROOT / "config" / "installation.json"))
    parser.add_argument("--config", default=str(PACKAGE_ROOT / "config" / "sources.json"))
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--only", default="")
    parser.add_argument("--max-per-source", type=int, default=50)
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--analysis-file", default="")
    parser.add_argument("--receipt-file", default="")
    args = parser.parse_args(argv)
    try:
        if args.setup:
            config = run_setup(args.installation, email=args.email, weekday=args.weekday, trigger_time=args.time)
            print(json.dumps({"initialized": True, "delivery_email": config["delivery_email"]}, ensure_ascii=False))
            return 0
        if args.max_per_source < 1 or args.max_per_source > 500:
            raise ValueError("max-per-source must be between 1 and 500")
        if args.stage == "collect":
            result = collect(args, load_installation(args.installation))
        else:
            if not args.run_dir:
                raise ValueError("--run-dir is required")
            if args.stage == "receipt" and not args.receipt_file:
                raise ValueError("--receipt-file is required")
            result = finalize(args) if args.stage == "finalize" else receipt(args)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
