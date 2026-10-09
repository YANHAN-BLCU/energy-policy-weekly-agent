"""MI-controlled vocabulary and evidence-bound issuing agency translations."""
from functools import lru_cache
from pathlib import Path
import json
import re


@lru_cache(maxsize=1)
def dictionary():
    path = Path(__file__).parent / "data" / "mi_dictionary.json"
    if not path.is_file():
        raise ValueError("缺少本地字典：先运行 scripts/init_local_data.py 导入本地数据，或使用 --demo 测试")
    return json.loads(path.read_text(encoding="utf-8"))


def agency_by_code(code):
    code = dictionary().get("code_aliases", {}).get(code, code)
    entries = dictionary()["agencies"] + dictionary()["issuer_units"]
    matches = [entry for entry in entries if entry["code"] == code]
    if len(matches) != 1:
        raise ValueError(f"Issuing agency is absent or ambiguous in MI dictionary: {code}")
    return matches[0]


def split_labels(value):
    return list(dict.fromkeys(part.strip() for part in re.split(r"\s*/\s*|[;；、]", value) if part.strip()))


def validate_classification(industry, tags):
    industries, labels = split_labels(industry), split_labels(tags)
    pairs = dictionary()["policy_tags"]
    categories = {pair["category"] for pair in pairs}
    allowed = {pair["tag"] for pair in pairs}
    if not industries or not labels or set(industries) - categories or set(labels) - allowed:
        raise ValueError("Supported_Industry / Policy_Tags must use exact MI dictionary labels")
    for label in labels:
        if not any(pair["category"] in industries and pair["tag"] == label for pair in pairs):
            raise ValueError(f"Policy tag does not match Supported_Industry: {label}")
    for category in industries:
        if not any(pair["category"] == category and pair["tag"] in labels for pair in pairs):
            raise ValueError(f"Supported_Industry has no matching policy tag: {category}")
    return " / ".join(industries), " / ".join(labels)


def validate_issuers(record, issuers):
    if not isinstance(issuers, list) or not issuers:
        raise ValueError("issuing_agencies requires at least one issuer with original evidence")
    found = []
    text = record["body_text"]
    for item in issuers:
        if not isinstance(item, dict):
            raise ValueError("Invalid issuing_agencies entry")
        agency = agency_by_code(item.get("code", ""))
        quote = item.get("evidence_quote")
        if not isinstance(quote, str) or not quote.strip() or quote not in text:
            raise ValueError("Issuer evidence_quote must occur verbatim in the verified body")
        names = [agency["chinese_name"]]
        aliases = {agency["code"]: agency.get("aliases", [])}
        if not any(name in quote for name in names + aliases.get(agency["code"], [])):
            raise ValueError("Issuer evidence does not identify the selected MI agency")
        if agency["code"] not in {unit["code"] for unit in dictionary()["issuer_units"]}:
            positions = [m.start() for m in re.finditer(re.escape(quote), text)]
            office_names = [name + suffix for name in names + aliases.get(agency["code"], [])
                            for suffix in ("办公厅", "综合司")]
            spans = [(m.start(), m.end()) for full in office_names for m in re.finditer(re.escape(full), text)]
            if positions and all(any(start <= pos and pos + len(quote) <= end for start, end in spans) for pos in positions):
                raise ValueError("Issuer is an office; its exact unit must be present in the MI dictionary")
        # A cropped quotation must not collapse an explicitly named office into its parent.
        for unit in dictionary()["issuer_units"]:
            full = unit["chinese_name"]
            if unit["code"] == agency["code"] or not any(name in full for name in names):
                continue
            positions = [m.start() for m in re.finditer(re.escape(quote), text)]
            unit_spans = [(m.start(), m.end()) for m in re.finditer(re.escape(full), text)]
            if positions and all(any(start <= pos and pos + len(quote) <= end for start, end in unit_spans) for pos in positions):
                raise ValueError("Issuer evidence names an office: use its exact MI unit translation")
        if agency["code"] in [entry["code"] for entry in found]:
            raise ValueError("Duplicate issuing agency")
        found.append({**agency, "evidence_quote": quote})
    return found


def export_labels(record):
    industry, tags = validate_classification(record.get("supported_industry", ""), record.get("policy_tags", ""))
    issuers = validate_issuers(record, record.get("issuing_agencies"))
    return {"industry": industry, "tags": tags,
            "agency_codes": " / ".join(item["code"] for item in issuers),
            "agency_names": ", ".join(item["name"] for item in issuers)}
