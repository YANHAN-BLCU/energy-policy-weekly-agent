"""Cheap energy-policy admission using list metadata only, before detail I/O."""
import re
import hashlib
from pathlib import Path

from .parse import EXCLUDE_WORDS, POLICY_WORDS, clean

ENERGY_TERMS = re.compile(
    r"能源|电力|电网|电价|电费|电站|电厂|发电|供电|用电|用能|输电|配电|售电|水电|火电|核电|"
    r"光伏|光热|风电|风能|太阳能|生物质|地热|氢能|氢气|储能|蓄能|充电|换电|"
    r"石油|原油|成品油|天然气|燃气|液化气|煤炭|煤矿|煤电|煤层气|煤化工|"
    r"油气|油田|炼油|管输|油品|燃料|供热|热电|节能|能耗|能效|节电|绿电|绿证|煤基|降碳|低碳|零碳|"
    r"碳排放|碳交易|碳市场|碳达峰|碳中和|碳配额|碳减排|温室气体|甲烷|"
    r"energy|electricity|renewable|hydrogen|petroleum|natural gas|carbon emissions", re.I)
NON_POLICY = re.compile(
    r"任职|免职|任命|聘任|干部|人员名单|继续教育|表彰|评选|讲话|发言|致辞|"
    r"召开|举行|出席|会见|座谈|调研|考察|工作动态|新闻稿|会议纪要|"
    r"部门预算|部门决算|政府采购|机关经费|信息公开工作年度报告", re.I)
OTHER_TOPIC = re.compile(r"义务教育|招生|学前教育|医疗保障|医保|养老保险|低保|婚姻|粮食收购|种子管理")
PUBLISHER = re.compile(r"(?:国家|[\u4e00-\u9fff]{2,8}(?:省|市|自治区))?能源(?:局|厅|委员会)")


def scope_signature():
    rules = Path(__file__).read_bytes() + EXCLUDE_WORDS.pattern.encode('utf-8') + POLICY_WORDS.pattern.encode('utf-8')
    return hashlib.sha256(rules).hexdigest()


def energy_policy_candidate(item):
    """Return an auditable decision; never inspect body, source name or navigation."""
    title = clean(item.get("text", ""))
    title = PUBLISHER.sub("", title)
    summary = PUBLISHER.sub("", clean(item.get("summary", ""))[:500])
    # Exclusions in the title take precedence over energy words, including speeches
    # that mention an actual policy. A document is not a policy just by mentioning one.
    excluded = EXCLUDE_WORDS.search(title) or NON_POLICY.search(title)
    if excluded:
        return {"decision": "Exclude", "reason": "NON_POLICY_ITEM", "matched": excluded[0]}
    if not POLICY_WORDS.search(title):
        return {"decision": "Exclude", "reason": "NO_POLICY_DOCUMENT_SIGNAL", "matched": ""}
    energy = ENERGY_TERMS.search(title) or ENERGY_TERMS.search(summary)
    if energy:
        return {"decision": "Collect", "reason": "ENERGY_POLICY_CANDIDATE", "matched": energy[0]}
    other = OTHER_TOPIC.search(title)
    return {"decision": "Exclude" if other else "Needs review",
            "reason": "OTHER_POLICY_TOPIC" if other else "ENERGY_TOPIC_UNCONFIRMED",
            "matched": other[0] if other else ""}
