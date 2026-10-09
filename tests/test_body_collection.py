from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile
import unittest

from policy_agent.collect import WeeklyCollector
from policy_agent.http import FetchResult
from policy_agent.models import Source
from policy_agent.parse import extract_detail, select_policy_links, attachment_links
from policy_agent.paths import PACKAGE_ROOT

TEXT = "为加强节能项目管理，现对项目申报条件、执行程序、主管单位职责和监督要求作出规定。" * 8
TITLE = "关于印发节能项目管理办法的通知"
ARTICLE = f'<html><head><meta name="ArticleTitle" content="{TITLE}"><meta name="PubDate" content="2026-10-06"></head><body><h1>微信分享扫一扫</h1><div class="TRS_Editor"><p>{TEXT}</p></div></body></html>'
URL = "https://example.com/20261006/t20261006_1.html"


def page(html, url=URL, status=200, content_type="text/html"):
    data = html.encode("utf-8") if isinstance(html, str) else html
    return FetchResult(url, url, status, content_type, data.decode("utf-8", errors="replace"), data, 1)


class BodyCollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix=".test-runtime-body-", dir=PACKAGE_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.source = Source("TEST", "Test", "https://example.com", "https://example.com/index.html")
        self.raw = Path(self.tmp.name) / "evidence"

    def test_column_and_empty_shell_are_not_bodies(self):
        html = '<html><body><h1>政策法规</h1><div class="content">' + ''.join(
            f'<p><a href="/20261006/t20261006_{i}.html">关于节能项目管理的通知 {i}</a>2026-10-06</p>' for i in range(10)) + '</div></body></html>'
        self.assertFalse(extract_detail(html, "https://example.com/index.html")["body_valid"])
        self.assertFalse(extract_detail('<html><body><div id="app"></div></body></html>', URL, TITLE)["body_valid"])

    def test_scanned_image_cannot_be_replaced_by_navigation_or_footer_text(self):
        html = f'<meta name="ArticleTitle" content="{TITLE}"><meta name="PubDate" content="2026-10-06"><div class="content"><div class="TRS_UEDITOR"><img src="policy.jpg"></div><div class="footer">' + TEXT + '</div></div>'
        parsed = extract_detail(html, URL, TITLE)
        self.assertFalse(parsed["body_valid"])
        self.assertEqual(parsed["body_text"], "")
        self.assertEqual(parsed["validation_error"], "IMAGE_BODY_OCR_REQUIRED")

    def test_title_metadata_and_real_body_override_share_navigation(self):
        parsed = extract_detail(ARTICLE, URL)
        self.assertTrue(parsed["body_valid"])
        self.assertEqual(parsed["title"], TITLE)
        self.assertEqual(parsed["body_text"], TEXT)
        self.assertNotIn("微信", parsed["body_text"])

    def test_captcha_with_status_200_is_failed(self):
        fake = '<html><head><title>安全验证</title></head><body><article>' + TEXT + '</article></body></html>'
        collector = WeeklyCollector(self.raw)
        with patch("policy_agent.collect.fetch", return_value=page(fake)):
            row = collector._detail(self.source, {"url": URL, "text": TITLE}, self.source.list_url)
        self.assertEqual(row["review_status"], "Failed")
        self.assertFalse(row["body_valid"])
        self.assertEqual(row["body_text"], "")

    def test_rendered_detail_is_retried_for_static_sources(self):
        collector = WeeklyCollector(self.raw, use_browser=True)
        with patch("policy_agent.collect.fetch", return_value=page('<html><body><div id="app"></div></body></html>')), patch(
                "policy_agent.collect.browser_fetch", return_value=page(ARTICLE)) as browser:
            row = collector._detail(self.source, {"url": URL, "text": TITLE}, self.source.list_url)
        browser.assert_called_once_with(URL)
        self.assertEqual(row["review_status"], "Collected")
        self.assertEqual(row["collector_method"], "browser")
        self.assertEqual(len(row["attempts"]), 2)
        self.assertTrue(Path(row["evidence_path"]).exists())

    def test_attachment_only_page_requires_actual_document_text(self):
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="urn:test"><w:body><w:p><w:r><w:t>' + TEXT + '</w:t></w:r></w:p></w:body></w:document>')
        stub = '<html><body><a href="/attachment.docx">下载政策文件</a></body></html>'
        document = page(buffer.getvalue(), "https://example.com/attachment.docx", content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        collector = WeeklyCollector(self.raw)
        with patch("policy_agent.collect.fetch", side_effect=[page(stub), document]):
            row = collector._detail(self.source, {"url": URL, "text": TITLE}, self.source.list_url)
        self.assertEqual(row["review_status"], "Collected")
        self.assertEqual(row["collector_method"], "attachment")
        self.assertIn(TEXT, row["body_text"])
        self.assertEqual(row["detail_url"], URL)

    def test_short_covering_notice_without_policy_attachment_fails(self):
        html = f'<meta name="ArticleTitle" content="{TITLE}"><article>现将节能项目管理办法印发给你们，请认真贯彻实施。主管部门2026年10月6日。附件：节能项目管理办法。</article>'
        collector = WeeklyCollector(self.raw)
        for content in (html, html.replace('</article>', TEXT * 5 + '</article>')):
            with self.subTest(long_cover=len(content) > 1200), patch("policy_agent.collect.fetch", return_value=page(content)):
                row = collector._detail(self.source, {"url": URL, "text": TITLE}, self.source.list_url)
            self.assertEqual(row["review_status"], "Failed")
            self.assertIn("POLICY_ATTACHMENT_LINK_MISSING", row["error"])
            self.assertEqual(row["body_text"], "")

    def test_embedded_viewer_and_download_api_are_attachments(self):
        html = '<iframe src="/pdfjs/viewer.html?file=%2Ffiles%2Fpolicy.pdf"></iframe><a href="/document/download?id=1">标准全文</a><a href="https://other.com/policy.pdf">外站</a>'
        links = attachment_links(html, URL, "example.com")
        self.assertEqual([item["url"] for item in links], ["https://example.com/files/policy.pdf", "https://example.com/document/download?id=1"])

    def test_download_api_docx_magic_and_failed_attachment_are_not_silently_ignored(self):
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", '<w:document xmlns:w="urn:test"><w:body><w:t>' + TEXT + '</w:t></w:body></w:document>')
        stub = f'<meta name="ArticleTitle" content="{TITLE}"><article>现将管理办法印发给你们，请结合实际认真执行，附件为具体管理办法全文。<a href="/document/download?id=1">办法</a></article>'
        collector = WeeklyCollector(self.raw)
        with patch("policy_agent.collect.fetch", side_effect=[page(stub), page(buffer.getvalue(), "https://example.com/document/download?id=1", content_type="application/octet-stream")]):
            row = collector._detail(self.source, {"url": URL, "text": TITLE}, self.source.list_url)
        self.assertTrue(row["body_valid"])
        self.assertIn(TEXT, row["body_text"])
        with patch("policy_agent.collect.fetch", side_effect=[page(stub), page("missing", "https://example.com/document/download?id=1", status=404)]):
            failed = collector._detail(self.source, {"url": URL, "text": TITLE}, self.source.list_url)
        self.assertFalse(failed["body_valid"])
        self.assertIn("POLICY_ATTACHMENT_INCOMPLETE", failed["error"])

    def test_homepage_is_traversed_but_never_a_collected_policy(self):
        homepage = '<html><body><a href="/policy/index.html">政策文件</a></body></html>'
        listing = f'<html><body><a href="{URL}">{TITLE}</a></body></html>'
        collector = WeeklyCollector(self.raw)
        with patch("policy_agent.collect.fetch", side_effect=[page(homepage, self.source.list_url),
                   page(listing, "https://example.com/policy/index.html"), page(ARTICLE)]):
            rows, status = collector.collect_source(self.source)
        self.assertEqual(status["pages_visited"], 2)
        self.assertEqual(status["body_success"], 1)
        self.assertEqual(rows[0]["detail_url"], URL)

    def test_mof_official_subdomains_are_explicitly_allowed(self):
        html = '<a href="https://jrs.mof.gov.cn/202609/t20260929_1.htm">关于示例住房贴息管理办法的通知</a>'
        self.assertEqual(select_policy_links(html, "https://www.mof.gov.cn/list.html"), [])
        self.assertEqual(len(select_policy_links(html, "https://www.mof.gov.cn/list.html", allowed_hosts=["mof.gov.cn"])), 1)


if __name__ == "__main__":
    unittest.main()
