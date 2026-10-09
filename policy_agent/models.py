from dataclasses import dataclass, field
from typing import Any, Dict, List
from datetime import date

@dataclass
class Source:
    code: str
    name: str
    website: str
    list_url: str
    adapter: str = "auto"
    enabled: bool = True
    level: str = ""
    region: str = ""
    type: str = ""
    chinese_name: str = ""
    verification: str = ""
    body_acceptance: str = ""
    max_items: int = 10
    policy_detail_pattern: str = ""
    allowed_hosts: List[str] = field(default_factory=list)
    body_selectors: List[str] = field(default_factory=list)
    entry_urls: List[str] = field(default_factory=list)
    pagination_pages: int = 20
    note: str = ""

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "Source":
        values = {k: value[k] for k in cls.__dataclass_fields__ if k in value}
        values["body_selectors"] = [item.strip() for item in values.get("body_selectors", []) if isinstance(item, str) and item.strip()]
        for key in ("website", "list_url"):
            if key in values:
                values[key] = values[key].replace("{year}", str(date.today().year))
        values["entry_urls"] = [url.replace("{year}", str(date.today().year)) for url in values.get("entry_urls", [])]
        return cls(**values)

@dataclass
class PolicyRecord:
    agency: str
    agency_name: str
    list_url: str
    detail_url: str
    title: str = ""
    issue_date: str = ""
    policy_number: str = ""
    body_text: str = ""
    abstract: str = ""
    supported_industry: str = ""
    policy_tags: str = ""
    impact_analysis: str = ""
    http_status: Any = ""
    collector_method: str = ""
    review_status: str = "Failed"
    ai_status: str = "Not run"
    evidence_path: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()
