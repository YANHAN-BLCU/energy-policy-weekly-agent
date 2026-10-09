"""Validate host-model output while keeping collected policy facts immutable."""
from .export import policy_id
from .paths import local_path
from .taxonomy import validate_classification, validate_issuers
import hashlib

FIELDS = ("supported_industry", "policy_tags", "abstract", "impact_analysis")


def apply_analysis(records, analysis, run_id):
    for row in records:
        if not row.get("body_valid") or not row.get("body_text", "").strip() or row.get("review_status") == "Failed":
            raise ValueError("Cannot finalize policies without a verified body")
        if hashlib.sha256(row["body_text"].encode("utf-8")).hexdigest() != row.get("body_sha256"):
            raise ValueError("Collected body checksum changed before analysis")
        path = local_path(row.get("evidence_path", ""), "正文证据", must_exist=True)
        if not path.is_file() or not path.stat().st_size:
            raise ValueError("Body evidence must be a nonempty file")
        for evidence in row.get("body_sources", []):
            path = local_path(evidence.get("evidence_path", ""), "正文组成证据", must_exist=True)
            if not path.is_file() or not path.stat().st_size:
                raise ValueError("Every body component needs nonempty evidence")
        for evidence in row.get("processing_evidence", []):
            path = local_path(evidence, "正文解析证据", must_exist=True)
            if not path.is_file() or not path.stat().st_size:
                raise ValueError("Every OCR or document processing result needs nonempty evidence")
    if analysis.get("run_id") != run_id:
        raise ValueError("Analysis run_id does not match")
    items = analysis.get("records")
    if not isinstance(items, list):
        raise ValueError("Analysis records must be a list")
    expected = {policy_id(row) for row in records}
    by_id = {}
    for item in items:
        key = item.get("policy_id")
        if key not in expected or key in by_id:
            raise ValueError("Unknown or duplicate policy_id in analysis")
        for name in FIELDS:
            value = item.get(name)
            if not isinstance(value, str) or not value.strip() or len(value) > 4000:
                raise ValueError(f"Invalid analysis field: {name}")
        by_id[key] = item
    if set(by_id) != expected:
        raise ValueError("Host analysis must cover every collected record")
    enriched = []
    for record in records:
        item = by_id[policy_id(record)]
        row = dict(record)
        row.update({name: item[name].strip() for name in FIELDS})
        row["supported_industry"], row["policy_tags"] = validate_classification(row["supported_industry"], row["policy_tags"])
        row["issuing_agencies"] = validate_issuers(record, item.get("issuing_agencies"))
        row["ai_status"] = "Host AI analyzed"
        enriched.append(row)
    return enriched
