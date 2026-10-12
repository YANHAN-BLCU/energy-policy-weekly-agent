"""轻量静态采集：纯 requests + BeautifulSoup，无浏览器、无 JS、无动态接口。

只做三件事：
1. 读列表页 → 取标题 / 日期 / 摘要 / 链接
2. 关键词筛选能源政策候选
3. 抓详情页可见 HTML 文字 → 正文验收

不下载 PDF/Word/Excel/图片/附件；列表或详情不足时记入 needs_review，交宿主 AI 搜索复查。
"""
import hashlib
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote

import requests
from bs4 import BeautifulSoup

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
TEXT_TYPES = {"text/html", "application/xhtml+xml", "application/xml", "text/plain", "text/xml"}
BLOCKED_SUFFIX = re.compile(
    r"\.(?:pdf|docx?|wps|xlsx?|pptx?|zip|rar|7z|png|jpe?g|gif|webp|bmp|tiff?|svg|mp[34]|wav)(?:$|[?#/&=])", re.I)
POLICY_WORDS = re.compile(
    r"政策|法规|规章|规范性文件|通知|公告|办法|意见|规划|方案|措施|文件|规则|条例|指导|"
    r"行动计划|目录|清单|公示|通报|批复|细则|标准|规定|决定|命令|法$", re.I)
ENERGY_WORDS = re.compile(
    r"能源|电力|电网|电价|电费|电站|电厂|发电|供电|用电|用能|输电|配电|售电|水电|火电|核电|"
    r"光伏|光热|风电|风能|太阳能|生物质|地热|氢能|氢气|储能|蓄能|充电|换电|"
    r"石油|原油|成品油|天然气|燃气|液化气|煤炭|煤矿|煤电|煤层气|煤化工|"
    r"油气|油田|炼油|管输|油品|燃料|供热|热电|节能|能耗|能效|节电|绿电|绿证|煤基|降碳|低碳|零碳|"
    r"碳排放|碳交易|碳市场|碳达峰|碳中和|碳配额|碳减排|温室气体|甲烷", re.I)
NON_POLICY = re.compile(
    r"任职|免职|任命|聘任|干部|人员名单|继续教育|表彰|评选|讲话|发言|致辞|"
    r"召开|举行|出席|会见|座谈|调研|考察|工作动态|新闻稿|会议纪要|"
    r"部门预算|部门决算|政府采购|机关经费|信息公开工作年度报告", re.I)
EXCLUDE_WORDS = re.compile(
    r"解读|图解|图读|人事|任免|招聘|遴选|公务员|拟试用|薪酬|工资披露|会议|机关党建|登录|注册|"
    r"新闻报道|媒体报道|日报》|青年报》|领导班子|领导分工|宣传片|宣传视频|访谈|新闻发布会|吹风会|"
    r"答记者问|笔试|职称|评前公示|公示人员名单", re.I)
DATE_PATTERNS = [re.compile(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?"),
                 re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")]
BODY_SELECTORS = (
    ".TRS_Editor", ".TRS_UEDITOR", "#UCAP-CONTENT", "#zoom", "#zoomcon", "#con_con",
    "#content1", "#ContentText", "#detailContent", "#news-details", ".article-content",
    ".editor-content", ".editorContent", ".pages_content", ".content_body", "#Zoom", ".zoom",
    ".tys-main-zt-show", "#NewsContent", "#news_content", "#mainCon", "#BodyLabel",
    "#neirongText", "ucapcontent", ".conBox", ".gsj_htmlcon_bot", ".details_content",
    ".dticle-content", ".dlist_con", ".show-detail", ".gknbxq_detail", ".con_txt", ".bt-content",
    ".article_con", ".articleCont", ".article_content", "#detailCont2", ".main-txt",
    ".j-fontContent", ".detail_messge", ".zc_article_con", ".view.TRS_UEDITOR", "#js_content",
    ".zsy_comain", "article", ".content", "main",
)
GENERIC_TITLE = re.compile(
    r"^(?:.*(?:厅|局|委员会|政府|银行)[ _-]*)?(?:首页|政策文件|政策法规|法律法规|通知公告|"
    r"行政规范性文件|政府信息公开|政务公开|政策发布|文件库|栏目)$")
BLOCK_TITLE = re.compile(r"403|404|502|access.denied|forbidden|安全验证|访问验证|验证码|网站维护|系统维护|错误页面", re.I)
NUMBER_RE = re.compile(r"[\u4e00-\u9fa5A-Za-z]{1,24}(?:〔|\[)20\d{2}(?:〕|\])[\u4e00-\u9fa5A-Za-z0-9（）()\-]{0,32}")


def clean(value):
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


def normalize_url(url):
    parts = urlsplit((url or "").strip())
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def parse_date(value):
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(value or ""):
            try:
                return date(*(int(p) for p in match.groups())).isoformat()
            except ValueError:
                continue
    return ""


def is_document_link(url):
    return bool(BLOCKED_SUFFIX.search(unquote(unquote(url or "")).lower()))


def fetch(url, timeout=15, retries=1):
    """只取网页文字；遇到附件/非网页内容返回 error 标记，不下载。"""
    if is_document_link(url):
        return {"url": url, "final_url": url, "status": None, "text": "", "content": b"",
                "content_type": "", "error": "FILE_DOWNLOAD_SKIPPED"}
    last = ""
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, timeout=timeout, allow_redirects=True,
                                headers={"User-Agent": DEFAULT_UA,
                                         "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
            raw = resp.content
            ctype = resp.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if is_document_link(resp.url) or ctype not in TEXT_TYPES:
                return {"url": url, "final_url": resp.url, "status": resp.status_code, "text": "",
                        "content": b"", "content_type": ctype, "error": "NON_WEB_CONTENT_SKIPPED"}
            if raw.lstrip().startswith((b"%PDF-", b"PK\x03\x04", b"\xd0\xcf\x11\xe0")):
                return {"url": url, "final_url": resp.url, "status": resp.status_code, "text": "",
                        "content": b"", "content_type": ctype, "error": "NON_WEB_CONTENT_SKIPPED"}
            enc = resp.encoding or resp.apparent_encoding or "utf-8"
            if str(enc).lower() in {"iso-8859-1", "latin-1"}:
                enc = resp.apparent_encoding or "utf-8"
            try:
                text = raw.decode(enc, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            err = "" if 200 <= resp.status_code < 300 else f"HTTP_{resp.status_code}"
            return {"url": url, "final_url": resp.url, "status": resp.status_code, "text": text,
                    "content": raw, "content_type": ctype, "error": err}
        except Exception as exc:
            last = str(exc)[:200]
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    return {"url": url, "final_url": url, "status": None, "text": "", "content": b"",
            "content_type": "", "error": last or "FETCH_FAILED"}


def list_candidates(html, base_url, source, limit):
    """从列表页抽取候选：标题 / 日期 / 摘要 / 链接。"""
    soup = BeautifulSoup(html or "", "html.parser")
    base_host = urlsplit(base_url).hostname or ""
    items, seen = [], {}
    for anchor in soup.find_all("a"):
        href = (anchor.get("href") or "").strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = urljoin(base_url, href)
        if not url.lower().startswith(("http://", "https://")):
            continue
        host = urlsplit(url).hostname or ""
        if host != base_host:
            continue
        title = clean(anchor.get("title") or anchor.get_text(" ", strip=True))
        if len(title) < 6 or EXCLUDE_WORDS.search(title):
            continue
        if not POLICY_WORDS.search(title):
            continue
        # 日期：优先同行（li/tr/dd/p），再退到 URL
        issued = ""
        for parent in anchor.parents:
            if parent.name not in {"li", "tr", "dd", "p", "div", "td"}:
                continue
            row_text = clean(parent.get_text(" ", strip=True))
            if len(row_text) <= max(200, len(title) + 100) and len(parent.find_all("a")) <= 3:
                issued = parse_date(row_text.replace(clean(anchor.get_text(" ", strip=True)), "", 1))
                if issued:
                    break
            if len(row_text) > 1000:
                break
        issued = issued or parse_date(url)
        # 摘要：仅同一列表条目内、该链接独占行时取
        summary = ""
        row = anchor.find_parent(["li", "tr", "dd"])
        if row and len({urljoin(base_url, a.get("href", "")) for a in row.find_all("a")}) == 1:
            row_text = clean(row.get_text(" ", strip=True))
            if len(row_text) <= len(title) + 550:
                summary = clean(row_text.replace(clean(anchor.get_text(" ", strip=True)), "", 1))[:500]
        item = {"url": url, "title": title, "date": issued, "summary": summary}
        if url in seen:
            idx, prev = seen[url]
            if item["date"] and not items[idx].get("date"):
                items[idx] = item
        else:
            seen[url] = (len(items), item)
            items.append(item)
    items.sort(key=lambda x: (x.get("date", ""), x["title"]), reverse=True)
    return items[:limit]


def extract_attachments(html, base_url):
    """从详情页 HTML 提取可下载附件链接（.pdf/.doc/.docx/.xls/.xlsx/.wps/.zip 等）。

    只识别与登记，不下载。返回去重后的绝对 URL 列表（保持页面出现顺序）。
    """
    soup = BeautifulSoup(html or "", "html.parser")
    found, seen = [], set()
    for anchor in soup.find_all("a"):
        href = (anchor.get("href") or "").strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = urljoin(base_url, href)
        if not url.lower().startswith(("http://", "https://")):
            continue
        if not is_document_link(url):
            continue
        key = normalize_url(url)
        if key in seen:
            continue
        seen.add(key)
        # 附件名：优先链接文字，退到 URL 末段
        name = clean(anchor.get_text(" ", strip=True))
        if not name or len(name) > 120:
            name = unquote(url.rsplit("/", 1)[-1])[:120]
        found.append({"url": url, "name": name})
    return found


def extract_detail(html, url, anchor_title="", body_selectors=()):
    """解析详情页可见正文，做验收。"""
    soup = BeautifulSoup(html or "", "html.parser")
    meta = {(n.get("name") or n.get("property") or "").lower(): clean(n.get("content", ""))
            for n in soup.find_all("meta")}
    page_title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    title = next((meta.get(k) for k in ("articletitle", "dc.title", "og:title") if meta.get(k)), "")
    title_evidence = bool(title)
    if not title:
        heading = soup.select_one("h1,.article-title,.con_title,.title,.details_title,h2")
        title = clean(heading.get_text(" ", strip=True)) if heading else ""
        if re.search(r"^首页|欢迎.*(?:访问|浏览)|微信分享|扫一扫|网站导航", title):
            title = ""
        title_evidence = bool(title and not GENERIC_TITLE.fullmatch(title))
    if not title or GENERIC_TITLE.fullmatch(title):
        title = clean(anchor_title) or page_title

    issued = next((parse_date(meta.get(k, "")) for k in
                   ("pubdate", "publishdate", "articlepublishdate", "pubtime", "dc.date", "dc.date.issued")
                   if parse_date(meta.get(k, ""))), "")

    def visible(node):
        clone = BeautifulSoup(str(node), "html.parser")
        for bad in clone.select("script,style,noscript,nav,header,footer,aside,form,button,"
                                ".header,.footer,[role=navigation],.breadcrumb,.share,.copyright"):
            bad.decompose()
        text = clean(clone.get_text(" ", strip=True))
        link_text = sum(len(clean(a.get_text(" ", strip=True))) for a in clone.find_all("a"))
        return text, link_text / max(len(text), 1)

    body, selector = "", ""
    for sel in tuple(body_selectors) + BODY_SELECTORS:
        for node in soup.select(sel):
            text, density = visible(node)
            if density > 0.40 or len(text) < 40:
                continue
            threshold = 40 if title_evidence and sel not in {"main", ".content"} else 120
            if len(text) >= threshold and len(text) > len(body):
                body, selector = text, sel
    error = ""
    if BLOCK_TITLE.search(page_title) or (len(html or "") < 5000 and
                                          re.search(r"请完成验证|您的访问.*受限|请求被拦截", soup.get_text(), re.I)):
        error = "BLOCKED_PAGE"
    elif not body:
        error = "INSUFFICIENT_WEB_TEXT"
    elif GENERIC_TITLE.fullmatch(title):
        error = "COLUMN_PAGE"
    if error:
        body = ""
    if not issued:
        labeled = re.search(r"(?:发布日期|发布时间|发布日|成文日期)\s*[:：]?\s*(20\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?)",
                            soup.get_text(" ", strip=True))
        issued = parse_date(labeled.group(1)) if labeled else parse_date(url)
    number = clean((NUMBER_RE.search(body) or [""])[0])
    attachments = extract_attachments(html, url)
    return {"title": title, "issue_date": issued, "policy_number": number, "body_text": body,
            "body_selector": selector, "body_valid": bool(body) and not error,
            "validation_error": error, "attachments": attachments}


def keyword_decision(title, summary):
    """关键词筛选：返回 Collect / Exclude / Review（Review 交 AI 搜索复查）。"""
    t = clean(title)
    if NON_POLICY.search(t) or EXCLUDE_WORDS.search(t):
        return "Exclude", "NON_POLICY_ITEM"
    if not POLICY_WORDS.search(t):
        return "Exclude", "NO_POLICY_DOCUMENT_SIGNAL"
    if ENERGY_WORDS.search(t):
        return "Collect", "ENERGY_KEYWORD"
    if ENERGY_WORDS.search(clean(summary)[:500]):
        return "Collect", "ENERGY_KEYWORD_IN_SUMMARY"
    return "Review", "ENERGY_TOPIC_UNCONFIRMED"
