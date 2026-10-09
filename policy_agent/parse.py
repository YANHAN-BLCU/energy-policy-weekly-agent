"""Policy-detail discovery and conservative, evidence-based body validation."""
from datetime import date
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qs, unquote
import re
from bs4 import BeautifulSoup

POLICY_WORDS = re.compile(r"政策|法规|规章|规范性文件|通知|公告|办法|意见|规划|方案|措施|文件|规则|条例|指导|行动计划|目录|清单|公示|通报|批复|细则|标准|规定|决定|命令|法$|policy|regulation|notice", re.I)
EXCLUDE_WORDS = re.compile(r"解读|图解|图读|人事|任免|招聘|遴选|公务员|拟试用|薪酬|工资披露|会议|机关党建|登录|注册|新闻报道|媒体报道|日报》|青年报》|领导班子|领导分工|宣传片|宣传视频|政策粤动力|访谈|新闻发布会|吹风会|答记者问|笔试|职称|评前公示|公示人员名单", re.I)
ENTRY_WORDS = re.compile(r"规范性文件|政策文件|政策法规|政策发布|法律法规|通知公告|文件库|政府信息公开|政务公开|法规文件|政府文件|部门文件|法规规章|政策及解读|最新文件|信息公开|文件通知|公示公告|公告公示|法定主动公开")
DATE_PATTERNS = [re.compile(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?"), re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")]
NUMBER_RE = re.compile(r"[\u4e00-\u9fa5A-Za-z]{1,24}(?:〔|\[)20\d{2}(?:〕|\])[\u4e00-\u9fa5A-Za-z0-9（）()\-]{0,32}")
DETAIL_PATH = re.compile(r"post_\d+|content[_/]\d+|/t20\d{6}_|/t\d{5,}\.s?html?$|/art_(?:[a-f0-9]+|\d+_\d+)\.|/c\d+/content\.|/20\d{6}/[^/]+/(?:c\.html|[^/]+\.s?html?)|/20\d{6}/[^/]+\.s?html?$|/info/\d+/\d+\.htm|/\d{7,}\.s?html|/20\d{2}/\d{1,2}/\d{1,2}/[^/]+\.s?htm|/[a-f0-9]{24,}/(?:content|c)\.shtml|/20\d{4}/(?:[A-Za-z0-9_-]+/)?[A-Za-z0-9_-]+\.s?html?$|/\d{16,}/index\.shtml$", re.I)
INDEX_PATH = re.compile(r"/(?:index(?:_\d+)?|list|olist)\.(?:htm[l]?|shtml)$|/col/col\d+/?$", re.I)
BODY_SELECTORS = (
    ".TRS_Editor", ".TRS_UEDITOR", "#UCAP-CONTENT", "#zoom", "#zoomcon", "#con_con",
    "#content1", "#ContentText", "#detailContent", "#news-details", ".article-content", ".editor-content", ".editorContent", ".pages_content", ".content_body",
    "#Zoom", ".zoom", "#j-show-body", ".tys-main-zt-show", "#NewsContent", "#news_content", "#mainCon", "#BodyLabel", "#neirongText", "ucapcontent", ".conBox", ".gsj_htmlcon_bot", ".details_content", ".acticle-content",
    ".dlist_con", ".show-detail", ".gknbxq_detail", ".con_txt", ".bt-content", ".article_con", ".articleCont", ".article_content", "#detailCont2", ".main-txt", ".printArea.j-fontContent", ".j-fontContent.newscontnet", ".detail_messge", ".zc_article_con", ".gzk-article-con", ".view.TRS_UEDITOR", "#js_content", ".zsy_comain", "article", ".content", "main",
)
GENERIC_TITLE = re.compile(r"^(?:.*(?:厅|局|委员会|政府|银行)[ _-]*)?(?:首页|政策文件|政策法规|法律法规|通知公告|行政规范性文件|政府信息公开|政务公开|政策发布|文件库|栏目)$")
BLOCK_TITLE = re.compile(r"403|404|502|access.denied|forbidden|安全验证|访问验证|验证码|网站维护|系统维护|错误页面", re.I)


def clean(value):
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


def normalize_url(url):
    parts = urlsplit(url.strip())
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def parse_date(value):
    for pattern in DATE_PATTERNS:
        for match in pattern.finditer(value or ""):
            try:
                return date(*(int(part) for part in match.groups())).isoformat()
            except ValueError:
                continue
    return ""


def absolute_links(html, base_url):
    soup = BeautifulSoup(html or "", "html.parser")
    items, seen = [], {}
    for anchor in soup.find_all("a"):
        href = (anchor.get("href") or "").strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:")):
            continue
        url = urljoin(base_url, href)
        if not url.lower().startswith(("http://", "https://")):
            continue
        title = clean(anchor.get("title") or anchor.get_text(" ", strip=True))
        if not title:
            continue
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
        item = {"url": url, "text": title, "date": issued}
        # Only the same single-article list row may supply a summary; never use
        # surrounding navigation or a publisher's name as topic evidence.
        row = anchor.find_parent(["li", "tr", "dd"])
        if row and len({urljoin(base_url, a.get("href", "")) for a in row.find_all("a")}) == 1:
            row_text = clean(row.get_text(" ", strip=True))
            if len(row_text) <= len(title) + 550:
                summary = clean(row_text.replace(clean(anchor.get_text(" ", strip=True)), "", 1))
                if summary:
                    item["summary"] = summary[:500]
        score = (bool(anchor.get("title")), bool(POLICY_WORDS.search(title)), len(title))
        if url in seen:
            index, previous_score = seen[url]
            if score > previous_score:
                item["date"] = item["date"] or items[index].get("date", "")
                items[index] = item
                seen[url] = (index, score)
        else:
            seen[url] = (len(items), score)
            items.append(item)
    return items


def attachment_links(html, base_url, source_host, allowed_hosts=()):
    """Read document anchors and embedded PDF viewers, including download APIs."""
    soup = BeautifulSoup(html or "", "html.parser")
    items, seen = [], set()
    for node in soup.select("a[href],a[onclick],iframe[src],iframe[fileurl],embed[src],object[data]"):
        href = node.get("fileurl") or node.get("href") or node.get("src") or node.get("data") or ""
        download = re.fullmatch(r"\s*downloadFj\(\s*(['\"])([^'\"]*)\1\s*,\s*(['\"])([^'\"]+)\3\s*\)\s*;?\s*", node.get("onclick", ""))
        if download and (not href or href.lower().startswith("javascript:")):
            href = download[4]
        if href.lower().startswith(("javascript:", "data:", "mailto:")):
            continue
        url = urljoin(base_url, href)
        query = parse_qs(urlsplit(url).query)
        if "file" in query and "viewer" in urlsplit(url).path.lower():
            url = urljoin(base_url, query["file"][0])
        if not url.lower().startswith(("http://", "https://")) or not host_allowed(url, source_host, allowed_hosts):
            continue
        label = clean(node.get("title") or node.get_text(" ", strip=True))
        fingerprint = unquote(url).lower()
        if not re.search(r"\.(?:pdf|docx?|wps|xlsx?|zip)(?:$|[?&#])", fingerprint) and not re.search(r"(?:document/download|downfile|download\?)", fingerprint):
            continue
        if url not in seen:
            seen.add(url)
            items.append({"url": url, "text": label or "政策附件", "date": ""})
    return items


def body_image_links(html, base_url, source_host, allowed_hosts=(), selectors=()):
    soup = BeautifulSoup(html or "", "html.parser")
    for selector in tuple(selectors) + BODY_SELECTORS:
        if selector in {"main", ".content", ".zsy_comain"}:
            continue
        node = soup.select_one(selector)
        if node is None:
            continue
        _, _, clone = _visible(node)
        images, seen = [], set()
        for image in clone.find_all("img"):
            parent = image.find_parent("a")
            if parent and re.search(r"\.(?:pdf|docx?|wps|xlsx?|zip)(?:$|[?&#])|downfile|document/download", parent.get("href", ""), re.I):
                continue
            href = image.get("data-original") or image.get("data-src") or image.get("src") or ""
            if not href or href.startswith("data:") or re.search(r"logo|qrcode|weixin|icon|button", href, re.I):
                continue
            width = re.search(r"\d+", str(image.get("width", "")))
            if width and int(width[0]) < 200:
                continue
            url = urljoin(base_url, href)
            if url not in seen and host_allowed(url, source_host, allowed_hosts):
                images.append(url)
                seen.add(url)
        if images:
            return images
    return []


def requires_policy_attachment(parsed):
    """A short covering notice does not provide the enclosed policy's full text."""
    body, title = parsed.get("body_text", ""), parsed.get("title", "")
    if re.search(r"(?:第一[条章]|一、.*二、)", body):
        return False
    return bool(re.search(r"印发|转发|征求.*意见", title) and
                re.search(r"现将|现印发|见附件|附件\s*[:：]|形成.*征求意见稿|起草了", body))


def host_allowed(url, source_host, allowed_hosts=()):
    host = (urlsplit(url).hostname or "").lower()
    if host == source_host.lower():
        return True
    return any(host == domain.lower() or host.endswith("." + domain.lower()) for domain in allowed_hosts)


def is_policy_link(item, source_host, allow_external=False, detail_pattern="", allowed_hosts=()):
    url, title = item["url"], item.get("text", "")
    if not allow_external and not host_allowed(url, source_host, allowed_hosts):
        return False
    if len(title) < 6 or EXCLUDE_WORDS.search(title) or GENERIC_TITLE.fullmatch(title):
        return False
    path = urlsplit(url).path
    if re.search(r"/(?:zcjd|spjd|tpjd|tjjd|video|zctj)/", path, re.I):
        return False
    if (INDEX_PATH.search(path) and not DETAIL_PATH.search(path)) or path in {"", "/"}:
        return False
    configured_detail = bool(detail_pattern and "pending" not in detail_pattern.lower() and re.search(detail_pattern, url, re.I))
    official_document_api = bool(re.search(r"/gwk/resource/file\?", url) and re.search(r"\.pdf(?:$|[?&#])", unquote(url), re.I))
    if not configured_detail and not DETAIL_PATH.search(path) and not path.lower().endswith((".pdf", ".docx")) and not official_document_api:
        if not re.search(r"/20\d{2}/", path):
            return False
    return bool(POLICY_WORDS.search(title))


def select_policy_links(html, base_url, max_items=10, allow_external=False, detail_pattern="", allowed_hosts=()):
    host = urlsplit(base_url).hostname or ""
    links = [item for item in absolute_links(html, base_url)
             if is_policy_link(item, host, allow_external, detail_pattern, allowed_hosts)]
    links.sort(key=lambda item: (item.get("date", ""), item["text"]), reverse=True)
    return links[:max_items]


def discover_entries(html, base_url, allowed_hosts=()):
    host = urlsplit(base_url).hostname or ""
    entries = [item for item in absolute_links(html, base_url)
               if (ENTRY_WORDS.search(item["text"]) or (re.fullmatch(r"20\d{2}年?", item["text"]) and date.today().year - 1 <= int(item["text"].rstrip("年")) <= date.today().year)) and not EXCLUDE_WORDS.search(item["text"])
               and not re.search(r"年报|年度报告|公开指南|公开制度|公开依申请", item["text"])
               and host_allowed(item["url"], host, allowed_hosts) and not DETAIL_PATH.search(item["url"])]
    entries.sort(key=lambda item: ("规范性" not in item["text"], "政策" not in item["text"], len(item["text"])))
    return entries


def _metadata(soup):
    return {(node.get("name") or node.get("property") or "").lower(): clean(node.get("content", ""))
            for node in soup.find_all("meta")}


def _visible(node):
    clone = BeautifulSoup(str(node), "html.parser")
    for unwanted in clone.select("script,style,noscript,nav,header,footer,aside,form,button,.header,.footer,[role=navigation],.breadcrumb,.current-location,.details-title,.share,.copyright,.time_dy"):
        unwanted.decompose()
    text = clean(clone.get_text(" ", strip=True))
    link_text = sum(len(clean(anchor.get_text(" ", strip=True))) for anchor in clone.find_all("a"))
    return text, link_text / max(len(text), 1), clone


def extract_detail(html, url, anchor_text="", body_selectors=()):
    soup = BeautifulSoup(html or "", "html.parser")
    meta = _metadata(soup)
    page_title = clean(soup.title.get_text(" ", strip=True) if soup.title else "")
    title = next((meta.get(key) for key in ("articletitle", "dc.title", "og:title") if meta.get(key)), "")
    title_evidence = bool(title)
    if not title:
        heading = soup.select_one("h1,.article-title,.con_title,.title,.details_title,h2")
        title = clean(heading.get_text(" ", strip=True)) if heading else ""
        if re.search(r"^首页|欢迎.*(?:访问|浏览)|微信分享|扫一扫|网站导航", title):
            title = ""
        title_evidence = bool(title and not GENERIC_TITLE.fullmatch(title))
    if not title or GENERIC_TITLE.fullmatch(title):
        title = clean(anchor_text) or page_title
    issued = next((parse_date(meta.get(key, "")) for key in
                   ("pubdate", "publishdate", "articlepublishdate", "pubtime", "dc.date", "dc.date.issued")
                   if parse_date(meta.get(key, ""))), "")
    candidates, article_images, dedicated_text_length = [], False, 0
    for selector in tuple(body_selectors) + BODY_SELECTORS:
        for node in soup.select(selector):
            text, density, clone = _visible(node)
            if selector not in {"main", ".content", ".zsy_comain"}:
                dedicated_text_length = max(dedicated_text_length, len(text))
                article_images = article_images or bool(clone.find("img"))
            # Link-list containers cannot become article bodies merely because they are long.
            if density > 0.40 or len(text) < 40:
                continue
            threshold = 40 if title_evidence and selector not in {"main", ".content"} else 120
            if len(text) >= threshold:
                candidates.append((len(text) * (1 - density), selector, text, clone))
    body, selector, paragraph_prose = "", "", 0
    image_only = article_images and dedicated_text_length < 40
    if candidates and not image_only:
        # Prefer dedicated article content over wrappers containing navigation/related links.
        dedicated = [entry for entry in candidates if entry[1] not in {"main", ".content"}]
        _, selector, body, chosen = max(dedicated or candidates, key=lambda entry: entry[0])
        for paragraph in chosen.find_all("p"):
            text = clean(paragraph.get_text(" ", strip=True))
            links = sum(len(clean(anchor.get_text(" ", strip=True))) for anchor in paragraph.find_all("a"))
            if len(text) - links >= 30:
                paragraph_prose += len(text) - links
    error = ""
    if BLOCK_TITLE.search(page_title) or (len(html or "") < 5000 and re.search(r"请完成验证|您的访问.*受限|请求被拦截|verify you are human", soup.get_text(), re.I)):
        error = "BLOCKED_PAGE"
    elif image_only:
        error = "IMAGE_BODY_OCR_REQUIRED"
    elif not body:
        error = "NO_ARTICLE_BODY"
    elif GENERIC_TITLE.fullmatch(title):
        error = "COLUMN_PAGE"
    elif selector in {"main", ".content", "metadata-confirmed body"} and len(select_policy_links(html, url, 30)) >= 4 and paragraph_prose < len(body) * 0.60:
        error = "COLUMN_PAGE"
    if error:
        body = ""
    if not issued:
        labeled_date = re.search(r"(?:发布日期|发布时间|发布日|成文日期)\s*[:：]?\s*(20\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?)", soup.get_text(" ", strip=True))
        issued = parse_date(labeled_date.group(1)) if labeled_date else parse_date(url)
    number = clean((NUMBER_RE.search(body) or [""])[0])
    return {"title": title, "issue_date": issued, "policy_number": number,
            "body_text": body, "abstract": body.replace(title, "", 1).strip()[:1000],
            "body_selector": selector, "body_valid": bool(body) and not error,
            "validation_error": error}


def extract_text_detail(text, url, anchor_text=""):
    body = clean(text)
    valid = len(body) >= 80 and len(re.findall(r"[\u4e00-\u9fffA-Za-z]", body)) >= 40
    return {"title": clean(anchor_text), "issue_date": parse_date(body) or parse_date(url),
            "policy_number": clean((NUMBER_RE.search(body) or [""])[0]),
            "body_text": body if valid else "", "abstract": body[:1000] if valid else "",
            "body_selector": "document text", "body_valid": valid,
            "validation_error": "" if valid else "DOCUMENT_TEXT_EMPTY_OR_INCOMPLETE"}
