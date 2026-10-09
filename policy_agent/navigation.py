"""Policy navigation, authority checks and explicit pagination discovery."""
from urllib.parse import urljoin, urlsplit, urlunsplit
import re
from bs4 import BeautifulSoup
from .parse import absolute_links, host_allowed, normalize_url, DETAIL_PATH

AUTHORITY = {
    "DEE": r"生态环境|环境保护", "DOF": r"财政", "DIIT": r"工业(?:和|与)信息化|工信|经济(?:和|与)信息化|经济和信息|工业经济信息网",
    "DRC": r"发展和改革|发展改革|发改", "EA": r"能源", "EB": r"能源",
    "GO": r"人民政府|政府办公|政务网", "PG": r"人民政府|政府门户|政务网",
    "EIT": r"工业(?:和|与)信息化|工信|经济(?:和|与)信息化|经济和信息|工业经济信息网",
}
PROVINCES = {"GD": "广东", "JS": "江苏", "ZJ": "浙江", "SD": "山东", "AH": "安徽", "BJ": "北京", "CQ": "重庆", "FJ": "福建", "GS": "甘肃", "GX": "广西", "GZ": "贵州", "HEB": "河北", "HEN": "河南", "HI": "海南", "HLJ": "黑龙江", "HUB": "湖北", "HUN": "湖南", "JL": "吉林", "JX": "江西", "LN": "辽宁", "NM": "内蒙古", "NX": "宁夏", "QH": "青海", "SC": "四川", "SH": "上海", "SN": "陕西", "SX": "山西", "TJ": "天津", "XJ": "新疆", "XZ": "西藏", "YN": "云南"}


def same_page(left, right):
    def identity(url):
        parsed = urlsplit(normalize_url(url))
        return (parsed.hostname, parsed.port if parsed.port not in {80, 443} else None, parsed.path, parsed.query)
    return identity(left) == identity(right)


def authority_pattern(source):
    return AUTHORITY.get(source.code.split()[-1], "") if source.level == "Provincial" else ""


def authority_matches(source, html, url):
    pattern = authority_pattern(source)
    if not pattern:
        return True
    soup = BeautifulSoup(html or "", "html.parser")
    site_values = [node.get("content", "") for node in soup.find_all("meta")
                   if node.get("name", "").lower() in {"sitename", "publisher", "dc.publisher", "site_name"}
                   and node.get("content", "").strip()]
    values = site_values or [soup.title.get_text() if soup.title else ""]
    province = PROVINCES.get(source.code.split()[0])
    identity = " ".join(values)
    if province and re.search(r"国家(?:发展|能源|工业)|中华人民共和国|工业和信息化部|生态环境部|财政部|住房和城乡建设部|中国政府网|国务院", identity):
        return False
    if province and any(other in identity for other in PROVINCES.values()) and province not in identity:
        return False
    if source.code.split()[-1] in {"EA", "EB"}:
        values.extend(node.get("content", "") for node in soup.find_all("meta")
                      if node.get("name", "").lower() == "columnname")
        if same_page(url, source.website):
            values.extend(item["text"] for item in energy_entries(source, html, url))
    # Energy bureaus hosted by DRCs must use an energy-specific entry/document.
    return bool(re.search(pattern, " ".join(values)))


def department_links(source, html, base_url):
    pattern = authority_pattern(source)
    if not pattern or source.code.split()[-1] in {"GO", "PG"}:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    links = absolute_links(html, base_url)
    links.extend({"url": urljoin(base_url, node.get("value", "")), "text": node.get_text(strip=True)}
                 for node in soup.find_all("option") if node.get("value", "").startswith(("http://", "https://")))
    found = []
    for item in links:
        host = urlsplit(item["url"]).hostname or ""
        if (len(item["text"]) < 40 and not re.search(r"国家|中华人民共和国", item["text"]) and re.search(pattern, item["text"]) and re.search(r"(?:厅|委员会|委|局)(?:官网|门户网站|网站)?$", item["text"]) and host.endswith(".gov.cn")
                and host != urlsplit(base_url).hostname and not DETAIL_PATH.search(urlsplit(item["url"]).path)):
            found.append(item["url"])
    return list(dict.fromkeys(found))[:4]


def pagination_links(html, base_url, allowed_hosts=()):
    host = urlsplit(base_url).hostname or ""
    links = []
    for item in absolute_links(html, base_url):
        if re.fullmatch(r"(?:下一页|下页|后页|Next|Next Page|[>›»]+)", item["text"], re.I):
            if host_allowed(item["url"], host, allowed_hosts) and normalize_url(item["url"]) != normalize_url(base_url):
                links.append(item["url"])
    # TRS pagination often has no anchors; its createPageHTML embeds the total.
    match = re.search(r"createPageHTML\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]", html or "", re.I)
    if match:
        total, current, stem, extension = match.groups()
        if int(current) + 1 < int(total):
            links.append(urljoin(base_url, f"{stem}_{int(current) + 1}.{extension}"))
    return list(dict.fromkeys(links))


def energy_entries(source, html, base_url):
    if source.code.split()[-1] not in {"EA", "EB"}:
        return []
    host = urlsplit(base_url).hostname or ""
    province = re.escape(PROVINCES.get(source.code.split()[0], ""))
    prefix = rf"(?:(?:{province})(?:省|市|自治区|壮族自治区|回族自治区|维吾尔自治区)?|省|自治区)?"
    pattern = prefix + r"能源(?:局|政策|管理|工作|发展|处|运行|资源价格|和工业生产资料|政策法规|通知公告)?"
    return [item for item in absolute_links(html, base_url)
            if re.fullmatch(pattern, item["text"])
            and host_allowed(item["url"], host, source.allowed_hosts)
            and not DETAIL_PATH.search(urlsplit(item["url"]).path)
            and not same_page(item["url"], base_url)]


def secure_alternative(url):
    parsed = urlsplit(url)
    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, "")) if parsed.scheme == "http" else url
