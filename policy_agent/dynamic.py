"""Read observed JPAAS unit APIs without evaluating page scripts."""
import ast
import html
import json
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
import requests
from .http import FetchResult, DEFAULT_UA
from .parse import absolute_links, host_allowed, parse_date


def literal_list_redirect(page, allowed_hosts=()):
    soup = BeautifulSoup(page.text or '', 'html.parser')
    for script in soup.find_all('script'):
        match = re.fullmatch(r"\s*(?:window\.)?location\.href\s*=\s*(['\"])([^'\"]+)\1\s*;?\s*", script.get_text())
        if match:
            target = urljoin(page.final_url, match[2])
            if target.startswith(('http://', 'https://')) and host_allowed(target, urlsplit(page.final_url).hostname or '', allowed_hosts) and target != page.final_url:
                return target
    return ''


def hydrate_datastore(page, allowed_hosts=()):
    """Unwrap public JPage CDATA list records and observed next-group links."""
    from xml.etree import ElementTree
    soup = BeautifulSoup(page.text or '', 'html.parser')
    stores = [node.get_text().strip() for node in soup.find_all('script') if node.get_text().strip().startswith('<datastore>')]
    if page.text.lstrip().startswith('<datastore>'):
        stores.append(page.text.strip())
    fragments = []
    for store in stores[:6]:
        if len(store) > 5_000_000 or re.search(r'<!DOCTYPE|<!ENTITY', store, re.I):
            raise ValueError('DATASTORE_INVALID_XML')
        root = ElementTree.fromstring(store)
        if root.tag != 'datastore':
            raise ValueError('DATASTORE_INVALID_SCHEMA')
        fragments.extend(record.text or '' for record in root.findall('./recordset/record'))
        for group in root.findall('./nextgroup'):
            markup = BeautifulSoup(group.text or '', 'html.parser')
            for anchor in markup.find_all('a', href=True):
                url = urljoin(page.final_url, anchor['href'])
                if host_allowed(url, urlsplit(page.final_url).hostname or '', allowed_hosts) and '/module/web/jpage/dataproxy.jsp' in urlsplit(url).path:
                    fragments.append('<a href="' + html.escape(url, quote=True) + '">下一页</a>')
    if not fragments:
        return page
    text = page.text + '\n<section>' + '\n'.join(fragments) + '</section>'
    return FetchResult(page.url, page.final_url, page.status, 'text/html', text, text.encode('utf-8'), page.elapsed_ms, page.error)


def hydrate_literal_article(page):
    """Read a literal Vue article field; never evaluate its JavaScript."""
    match = re.search(r"el\s*:\s*['\"]#news-details['\"][\s\S]{0,300}?content\s*:\s*`((?:\\.|[^`])*)`", page.text or "")
    if not match or "${" in match[1]:
        return page
    soup = BeautifulSoup(page.text, "html.parser")
    node = soup.select_one("#news-details")
    if node is None:
        return page
    fragment = match[1].replace("\\`", "`").replace("\\\\", "\\")
    node.clear()
    node.append(BeautifulSoup(fragment, "html.parser"))
    text = str(soup)
    return FetchResult(page.url, page.final_url, page.status, page.content_type, text, text.encode("utf-8"), page.elapsed_ms, page.error)


def shanghai_policy_pages(page, timeout=15, page_limit=1, since=None):
    """Use the government policy API observed on Shanghai's official platform."""
    parts = urlsplit(page.final_url)
    if parts.hostname != "www.shanghai.gov.cn" or not parts.path.startswith("/zhengce/"):
        return page, [], True
    endpoint = "https://www.shanghai.gov.cn/gwk/policy/page"
    fragments, results, complete = [], [], False
    for number in range(1, page_limit + 1):
        query = {"siteIdList": ["0001"], "siteType": 0, "pageNo": number, "pageSize": 5}
        response = requests.post(endpoint, json=query, headers={"User-Agent": DEFAULT_UA, "Referer": page.final_url}, timeout=timeout)
        record = FetchResult(endpoint, response.url, response.status_code, response.headers.get("Content-Type", ""), response.text, response.content, 0)
        results.append(record)
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if payload.get("code") == 0 else None
        if not isinstance(data, dict) or not isinstance(data.get("records"), list):
            raise ValueError("SHANGHAI_POLICY_API_INVALID_SCHEMA")
        records = data["records"]
        dates = []
        for item in records:
            attrs = item.get("attrs") or {}
            url = urljoin(endpoint, attrs.get("zwPDFUrl", ""))
            title = item.get("title", "")
            issued = parse_date(item.get("publishDate", ""))
            if not title or not host_allowed(url, "www.shanghai.gov.cn") or "/gwk/resource/file?" not in url or ".pdf" not in url.lower():
                raise ValueError("SHANGHAI_POLICY_API_DOCUMENT_MISSING")
            if issued:
                dates.append(issued)
            fragments.append('<li><a href="' + html.escape(url, quote=True) + '">' + html.escape(title) + '</a><span>' + issued + '</span></li>')
        if (not records or number >= int(data.get("totalPage", number + 1)) or
                (since and len(dates) == len(records) and all(value < since.isoformat() for value in dates))):
            complete = True
            break
    text = page.text + "\n<ul>" + "\n".join(fragments) + "</ul>"
    return FetchResult(page.url, page.final_url, page.status, "text/html", text, text.encode("utf-8"), page.elapsed_ms), results, complete


def unit_pages(page, timeout=15, page_limit=1, since=None):
    soup = BeautifulSoup(page.text or "", "html.parser")
    scripts = [node for node in soup.select("script[url][querydata]")
               if "/front/page/build/unit" in node.get("url", "")]
    results, fragments, complete = [], [], True
    for script in scripts[:6]:
        params = ast.literal_eval(script["querydata"] if script.has_attr("querydata") else script["queryData"])
        if not isinstance(params, dict):
            continue
        endpoint = urljoin(page.final_url, script["url"])
        if not host_allowed(endpoint, urlsplit(page.final_url).hostname or ""):
            continue
        for number in range(1, page_limit + 1):
            query = dict(params)
            query["paramJson"] = json.dumps({"pageNo": number, "pageSize": 100, "search": ""}, ensure_ascii=False)
            response = requests.get(endpoint, params=query, headers={"User-Agent": DEFAULT_UA, "Referer": page.final_url}, timeout=timeout)
            record = FetchResult(endpoint, response.url, response.status_code, response.headers.get("Content-Type", ""),
                                 response.text, response.content, 0, "" if response.status_code == 200 else "UNIT_API_HTTP_FAILED")
            results.append(record)
            response.raise_for_status()
            payload = response.json()
            fragment = payload.get("data", {}).get("html", "") if isinstance(payload.get("data"), dict) else ""
            if not isinstance(fragment, str) or not fragment.strip():
                raise ValueError("UNIT_API_EMPTY_HTML")
            fragments.append(fragment)
            links = absolute_links(fragment, page.final_url)
            dates = [item["date"] for item in links if item.get("date")]
            if len(links) < 100 or (since and dates and all(value < since.isoformat() for value in dates)):
                break
            if number == page_limit:
                complete = False
    if fragments:
        text = str(soup) + "\n" + "\n".join(fragments)
        return FetchResult(page.url, page.final_url, page.status, "text/html", text, text.encode("utf-8"), page.elapsed_ms), results, complete
    return page, [], True
