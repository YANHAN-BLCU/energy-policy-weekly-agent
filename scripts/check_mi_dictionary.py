"""Check portable MI assets, optional read-only reference and saved weekly workbook."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_agent.mi_checks import check_dictionary_assets, check_reference, check_workbook


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, help="Read-only original MI workbook; optional after migration")
    parser.add_argument("--workbook", type=Path, help="Saved Policy_Weekly.xlsx inside application directory")
    args = parser.parse_args()
    try:
        report = {"passed": True, **check_dictionary_assets(verify_manifest=True), "reference_checked": False,
                  "reference_status": "原表未提供，仅核验迁移资产；不代表重新核对了原 MI"}
        if args.reference:
            report.update(check_reference(args.reference))
            report["reference_status"] = "已逐条对照原表字典及图片"
        if args.workbook:
            report.update(check_workbook(args.workbook))
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
