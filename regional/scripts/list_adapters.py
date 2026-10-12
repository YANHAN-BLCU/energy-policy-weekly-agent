"""列表接口适配器：为 JS 动态渲染站点提供纯静态取数（不用浏览器）。

覆盖三类：
- xinhua_json : 新华网 Xhwpage 组件，数据源为固定命名的 JSON（NEA 国家能源局）
- jpaas_unit  : JPAAS 政务平台 front/page/build/unit 接口（SAC、MOHURD）

接口参数都写在列表页 HTML 里，不执行 JS 也能提取。
"""
import ast
import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
DATE_RE = re.compile(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?")


def _get(url, referer="", timeout=20, params=None):
    headers = {"User-Agent": DEFAULT_UA, "Accept": "text/html,application/json,*/*;q=0.8"}
    if referer:
        headers["Referer"] = referer
    r = requests.get(url, headers=headers, timeout=timeout, params=params)
    r.encoding = r.apparent_encoding or r.encoding
    return r


def _clean(text):
    text = re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()
    # 部分数据源的标题字段内嵌 HTML 片段，去掉标签只留文字
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
    return text


def _norm_date(value):
    value = _clean(str(value))
    m = DATE_RE.search(value)
    if not m:
        return ""
    try:
        from datetime import date
        return date(*(int(g) for g in m.groups())).isoformat()
    except ValueError:
        return ""


# ---------- 新华网 Xhwpage（NEA）----------

def xinhua_json(list_url, max_items=100):
    """从列表页取 datasource id，请求 ds_<id>.json 拿记录。"""
    page = _get(list_url)
    soup = BeautifulSoup(page.text, "html.parser")
    node = soup.select_one("[data^='datasource:']") or soup.select_one("[datasource]")
    if node is None:
        return [], "XINHUA_NO_DATASOURCE"
    attr = node.get("data") or ""
    match = re.search(r"datasource:([0-9a-f]+)", attr)
    if not match:
        return [], "XINHUA_BAD_DATASOURCE"
    ds_id = match.group(1)
    base = list_url.rsplit("/", 1)[0] + "/"
    data_url = base + "ds_" + ds_id + ".json"
    resp = _get(data_url, referer=list_url)
    try:
        payload = resp.json()
    except ValueError:
        return [], "XINHUA_JSON_INVALID"
    rows = payload.get("datasource") or []
    items = []
    for row in rows[:max_items]:
        title = _clean(row.get("title") or "")
        href = row.get("publishUrl") or row.get("url") or ""
        if not title or not href:
            continue
        url = urljoin(base, href)
        issued = _norm_date(row.get("publishTime") or row.get("publishDate") or row.get("pubTime") or "")
        items.append({"url": url, "title": title, "date": issued,
                      "summary": _clean(row.get("description") or row.get("keywords") or "")[:500]})
    return items, ""


# ---------- JPAAS unit 接口（SAC / MOHURD）----------

def jpaas_unit(list_url, max_items=100):
    """从列表页 script[url][querydata] 取接口参数，请求 unit 接口拿 HTML 片段。"""
    page = _get(list_url)
    soup = BeautifulSoup(page.text, "html.parser")
    script = soup.select_one("script[url][querydata]")
    if script is None:
        return [], "JPAAS_NO_UNIT_SCRIPT"
    url = script.get("url", "")
    if "front/page/build/unit" not in url:
        return [], "JPAAS_UNEXPECTED_URL"
    try:
        params = ast.literal_eval(script["querydata"]) if script.has_attr("querydata") \
            else ast.literal_eval(script["queryData"])
    except (ValueError, SyntaxError):
        return [], "JPAAS_BAD_QUERYDATA"
    endpoint = urljoin(list_url, url)
    # 该接口对 pageSize 有上限（实测 >20 会 success:false），固定用 20 分页拉取
    items, seen = [], set()
    page_size = 20
    max_pages = max(1, min((max_items + page_size - 1) // page_size, 5))
    for page_no in range(1, max_pages + 1):
        query = dict(params)
        query["paramJson"] = json.dumps({"pageNo": page_no, "pageSize": page_size, "search": ""},
                                        ensure_ascii=False)
        resp = _get(endpoint, referer=list_url, params=query)
        try:
            payload = resp.json()
        except ValueError:
            return items, "JPAAS_JSON_INVALID"
        data = payload.get("data")
        fragment = ""
        if isinstance(data, dict):
            fragment = data.get("html") or ""
            if not fragment and isinstance(data.get("list"), list):
                for row in data["list"]:
                    title = _clean(row.get("title") or "")
                    href = row.get("url") or row.get("link") or ""
                    if title and href and href not in seen:
                        seen.add(href)
                        items.append({"url": urljoin(list_url, href), "title": title,
                                      "date": _norm_date(row.get("publishTime") or row.get("date") or ""),
                                      "summary": _clean(row.get("description") or "")[:500]})
                return items[:max_items], ""
        elif isinstance(data, str):
            fragment = data
        if not fragment:
            break
        page_items = _links_from_fragment(fragment, list_url, max_items)
        new = [it for it in page_items if it["url"] not in seen]
        if not new:
            break
        for it in new:
            seen.add(it["url"])
            items.append(it)
        if len(items) >= max_items:
            break
    if not items:
        return [], "JPAAS_EMPTY_HTML"
    return items[:max_items], ""


def _links_from_fragment(fragment, base_url, max_items):
    soup = BeautifulSoup(fragment, "html.parser")
    items, seen = [], set()
    for anchor in soup.find_all("a", href=True):
        title = _clean(anchor.get("title") or anchor.get_text(" ", strip=True))
        href = anchor["href"].strip()
        if len(title) < 6 or not href or href.lower().startswith(("javascript:", "#", "mailto:")):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        issued = ""
        for parent in anchor.parents:
            if parent.name not in {"li", "tr", "dd", "p", "div", "td"}:
                continue
            row_text = _clean(parent.get_text(" ", strip=True))
            issued = _norm_date(row_text.replace(title, "", 1))
            if issued:
                break
        issued = issued or _norm_date(url)
        items.append({"url": url, "title": title, "date": issued, "summary": ""})
        if len(items) >= max_items:
            break
    return items


ADAPTERS = {"xinhua_json": xinhua_json, "jpaas_unit": jpaas_unit}


def fetch_list(source, max_items=100):
    """按来源配置的 adapter 取列表；无 adapter 时返回 None 表示走通用 HTML 解析。"""
    adapter = (source.get("adapter") or "").strip()
    fn = ADAPTERS.get(adapter)
    if fn is None:
        return None
    list_url = source.get("list_url") or source.get("website")
    items, error = fn(list_url, max_items)
    return {"items": items, "error": error, "adapter": adapter, "list_url": list_url}
