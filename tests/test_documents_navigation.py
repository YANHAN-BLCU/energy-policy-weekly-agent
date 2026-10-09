from datetime import date
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch, Mock
from zipfile import ZipFile
import json
import struct
import unittest
from PIL import Image
from openpyxl import Workbook

from policy_agent.collect import document_text, WeeklyCollector
from policy_agent.dynamic import unit_pages, shanghai_policy_pages, hydrate_literal_article
from policy_agent.http import FetchResult
from policy_agent.legacy_doc import word_stream_text
from policy_agent.models import Source
from policy_agent.navigation import authority_matches, department_links, pagination_links, same_page, energy_entries
from policy_agent.ocr import recognize
from policy_agent.parse import select_policy_links, body_image_links, parse_date, absolute_links
from policy_agent.paths import PACKAGE_ROOT

TEXT = "为加强节能项目管理，规定申报条件、主管单位职责、执行程序和监督要求。" * 4
TITLE = "关于节能项目管理办法的通知"


def response(content, url="https://example.gov.cn/20261006/t20261006_1.html", kind="text/html"):
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return FetchResult(url, url, 200, kind, raw.decode("utf-8", errors="replace"), raw, 0)


def word_fixture(text):
    word = bytearray(2048)
    struct.pack_into("<HH", word, 0, 0xA5EC, 0xC1)
    struct.pack_into("<H", word, 32, 14)
    struct.pack_into("<H", word, 62, 22)
    struct.pack_into("<I", word, 64 + 3 * 4, len(text))
    raw = text.encode("utf-16-le")
    word[512:512 + len(raw)] = raw
    plc = struct.pack("<IIHIH", 0, len(text), 0, 512, 0)
    table = b"\x02" + struct.pack("<I", len(plc)) + plc
    struct.pack_into("<II", word, 154 + 33 * 8, 0, len(table))
    return word, table


class DocumentsNavigationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(prefix=".test-runtime-document-", dir=PACKAGE_ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_word_piece_table_preserves_end_and_rejects_incomplete_or_encrypted_text(self):
        word, table = word_fixture("第一条正文\r第二条要求\r最后一条施行日期。")
        text, meta = word_stream_text(word, table)
        self.assertIn("最后一条施行日期。", text)
        self.assertEqual(meta["pieces"], 1)
        with self.assertRaisesRegex(ValueError, "TRUNCATED_WORD_PIECE_TABLE"):
            bad = table[:1] + struct.pack("<I", 28) + table[5:]
            word_stream_text(word, bad)
        struct.pack_into("<H", word, 10, 0x100)
        with self.assertRaisesRegex(ValueError, "ENCRYPTED"):
            word_stream_text(word, table)

    def test_pdf_scan_processes_every_page_and_short_final_page(self):
        images = [Image.new("RGB", (100, 150), "white") for _ in range(2)]
        pdf = BytesIO()
        images[0].save(pdf, format="PDF", save_all=True, append_images=images[1:])
        def ocr(image, output, min_characters):
            text = TEXT if "0001" in str(image) else "本办法自2026年10月6日起施行。"
            output.write_text(json.dumps({"valid": True, "text": text}), encoding="utf-8")
            return {"valid": True, "text": text, "mean_confidence": .99}
        with patch("policy_agent.ocr.recognize", side_effect=ocr) as reader:
            text, kind = document_text(response(pdf.getvalue(), kind="application/pdf"), self.root)
        self.assertEqual(reader.call_count, 2)
        self.assertIn("日起施行", text)
        self.assertEqual(kind, ".pdf")
        pages = json.loads((self.root / "pages.json").read_text(encoding="utf-8"))
        self.assertEqual(pages["page_count"], 2)
        with patch("policy_agent.ocr.recognize", return_value={"valid": False, "error": "OCR_EMPTY_OR_LOW_CONFIDENCE"}):
            with self.assertRaisesRegex(ValueError, "PDF_PAGE_OCR_FAILED"):
                document_text(response(pdf.getvalue(), kind="application/pdf"), self.root)

    def test_zip_parses_all_document_members_and_rejects_bad_member(self):
        docx = BytesIO()
        with ZipFile(docx, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="test"><w:t>' + TEXT + '</w:t></w:document>')
        workbook = Workbook()
        workbook.active.append(["政策清单", TEXT])
        xlsx = BytesIO(); workbook.save(xlsx)
        for broken in (False, True):
            data = BytesIO()
            with ZipFile(data, "w") as z:
                z.writestr("办法.docx", docx.getvalue())
                z.writestr("清单.xlsx", b"bad" if broken else xlsx.getvalue())
            if broken:
                with self.assertRaises(ValueError):
                    document_text(response(data.getvalue(), url="https://example.gov.cn/policy.zip"), self.root)
            else:
                text, kind = document_text(response(data.getvalue(), url="https://example.gov.cn/policy.zip"), self.root)
                self.assertIn("政策清单", text)
                self.assertEqual(kind, ".zip")

    def test_ocr_preserves_short_text_but_rejects_low_confidence(self):
        image = self.root / "page.png"; Image.new("RGB", (100, 100), "white").save(image)
        box = SimpleNamespace(tolist=lambda: [[0, 0], [90, 0], [90, 10], [0, 10]])
        fake = SimpleNamespace(txts=["最后一条施行日期。"], scores=[.99], boxes=[box])
        with patch("policy_agent.ocr.engine", return_value=lambda path: fake):
            short = recognize(image, self.root / "ocr.json", min_characters=1)
            self.assertTrue(short["valid"])
            self.assertFalse(recognize(image, self.root / "standalone.json")["valid"])
        fake.scores = [.60]
        with patch("policy_agent.ocr.engine", return_value=lambda path: fake):
            self.assertFalse(recognize(image, self.root / "low.json", min_characters=1)["valid"])

    def test_long_image_tiles_keep_final_text(self):
        image = self.root / "long.png"; Image.new("RGB", (100, 3399), "white").save(image)
        box = SimpleNamespace(tolist=lambda: [[0, 1730], [90, 1730], [90, 1750], [0, 1750]])
        fake = SimpleNamespace(txts=["最后一条施行日期。"], scores=[.99], boxes=[box])
        with patch("policy_agent.ocr.engine", return_value=lambda path: fake):
            result = recognize(image, self.root / "ocr.json", min_characters=1)
        self.assertEqual(len(result["tiles"]), 2)
        self.assertEqual(result["tiles"][-1]["bottom"], 3399)
        self.assertEqual(len(result["lines"]), 1)
        self.assertGreater(result["lines"][0]["box"][0][1], 3000)

    def test_modern_column_prefixed_detail_is_not_a_column_page(self):
        url = "/col/col12345678/art/2026/art_abcdef0123456789abcdef0123456789.html"
        links = select_policy_links(f'<a href="{url}">{TITLE}</a>', "https://example.gov.cn/index.html", detail_pattern=r"/old/\d+\.html")
        self.assertEqual(len(links), 1)
        self.assertEqual(select_policy_links('<a href="/col/col12345678/index.html">政策文件</a>', "https://example.gov.cn/"), [])

    def test_unit_api_hydrates_observed_script_without_eval_or_cross_host_call(self):
        html = '<script url="/api/front/page/build/unit" queryData="{\'pageId\':\'1\'}"></script>'
        fragment = '<a href="/col/col123/art/2026/art_ab123.html">' + TITLE + '</a>'
        remote = Mock(status_code=200, url="https://example.gov.cn/api/front/page/build/unit?pageId=1", headers={"Content-Type": "application/json"}, text="{}", content=b"{}")
        remote.json.return_value = {"data": {"html": fragment}}
        with patch("policy_agent.dynamic.requests.get", return_value=remote) as get:
            hydrated, evidence, complete = unit_pages(response(html))
        self.assertIn(fragment, hydrated.text)
        self.assertEqual(len(select_policy_links(hydrated.text, hydrated.final_url)), 1)
        self.assertEqual(get.call_args.kwargs["params"]["pageId"], "1")
        self.assertTrue(complete)
        with patch("policy_agent.dynamic.requests.get") as get:
            unit_pages(response(html.replace('/api/front', 'https://other.gov.cn/api/front')))
            get.assert_not_called()

    def test_authority_rejects_article_topic_and_wrong_province(self):
        source = Source("JS DIIT", "江苏工信厅", "https://gxt.jiangsu.gov.cn/", "", level="Provincial")
        topic = '<title>江苏省人民政府</title><meta name="SiteName" content="江苏省人民政府"><meta name="ArticleTitle" content="工业和信息化政策通知">'
        self.assertFalse(authority_matches(source, topic, source.website))
        self.assertFalse(authority_matches(source, '<meta name="SiteName" content="中华人民共和国工业和信息化部">', 'https://www.miit.gov.cn/'))
        self.assertFalse(authority_matches(source, '<meta name="SiteName" content="浙江省工业和信息化厅">', source.website))
        self.assertTrue(authority_matches(source, '<meta name="SiteName" content="江苏省工业和信息化厅">', source.website))
        links = department_links(source, '<a href="https://gxt.jiangsu.gov.cn/">省工业和信息化厅</a><a href="https://other.gov.cn/20261006/t20261006_1.html">工业和信息化通知</a>', 'https://www.jiangsu.gov.cn/')
        self.assertEqual(links, [source.website])
        self.assertTrue(same_page('http://gxt.jiangsu.gov.cn/', 'https://gxt.jiangsu.gov.cn:443/'))

    def test_shanghai_dated_hash_links_and_official_policy_api(self):
        url = '/fgw_ny/20260922/0123456789abcdef0123456789abcdef.html'
        links = select_policy_links(f'<a href="{url}">{TITLE}</a>', 'https://fgw.sh.gov.cn/fgw_zcwjfl/index.html')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['date'], '2026-09-22')
        page = response('<title>上海市人民政府</title>', 'https://www.shanghai.gov.cn/zhengce/list')
        remote = Mock(status_code=200, url='https://www.shanghai.gov.cn/gwk/policy/page', headers={'Content-Type': 'application/json'}, text='{}', content=b'{}')
        remote.json.return_value = {'code': 0, 'data': {'totalPage': 2, 'records': [{'title': TITLE, 'publishDate': '2026-09-01 10:00:00', 'attrs': {'zwPDFUrl': '/gwk/resource/file?pathname=2/0001/document.pdf&filename=document.pdf'}}]}}
        with patch('policy_agent.dynamic.requests.post', return_value=remote) as post:
            hydrated, evidence, complete = shanghai_policy_pages(page, page_limit=5, since=date(2026, 9, 30))
        self.assertTrue(complete)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(len(select_policy_links(hydrated.text, page.final_url)), 1)
        self.assertEqual(post.call_args.kwargs['json']['siteIdList'], ['0001'])
        remote.json.return_value['data']['records'][0]['attrs']['zwPDFUrl'] = 'https://other.example/document.pdf'
        with patch('policy_agent.dynamic.requests.post', return_value=remote):
            with self.assertRaisesRegex(ValueError, 'DOCUMENT_MISSING'):
                shanghai_policy_pages(page)
        with patch('policy_agent.dynamic.requests.post') as post:
            shanghai_policy_pages(response('text', 'https://other.gov.cn/zhengce/list'))
            post.assert_not_called()

    def test_pdf_download_icon_is_not_body_ocr(self):
        html = '<article><a href="/policy.pdf"><img src="/W0202601001.gif"></a><img src="/scan.jpg"></article>'
        self.assertEqual(body_image_links(html, 'https://example.gov.cn/detail.html', 'example.gov.cn'), ['https://example.gov.cn/scan.jpg'])

    def test_energy_entry_discovery_is_official_and_not_an_article(self):
        source = Source('GD EA', '广东能源局', 'https://drc.gd.gov.cn/', '', level='Provincial')
        markup = '<a href="/energy/index.html">能源政策</a><a href="https://other.gov.cn/">能源局</a><a href="/20261006/content_1234.html">能源局</a>'
        self.assertEqual([item['url'] for item in energy_entries(source, markup, source.website)], ['https://drc.gd.gov.cn/energy/index.html'])
        source.code = 'GD DRC'
        self.assertEqual(energy_entries(source, markup, source.website), [])

    def test_unlabelled_entry_requires_same_host_home_identity(self):
        source = Source('FJ PG', '福建政府', 'https://example.gov.cn/', 'https://example.gov.cn/policy/index.html', level='Provincial')
        listing = f'<title>福建省政策文件库</title><li><a href="/20261006/t20261006_1.html">{TITLE}</a>2026-10-06</li>'
        collector = WeeklyCollector(self.root / 'evidence')
        def get(url, *args):
            return response('<meta name="SiteName" content="福建省人民政府">' if url == source.website else listing, url)
        row = {'review_status': 'Collected', 'body_valid': True}
        with patch('policy_agent.collect.fetch', side_effect=get), patch.object(collector, '_detail', return_value=row):
            records, status = collector.collect_source(source, 1)
        self.assertTrue(status['entry_verified'])
        self.assertTrue(Path(status['discovery'][0]['authority_evidence']).is_file())
        conflict = listing.replace('<title>', '<meta name="SiteName" content="国家发展和改革委员会"><title>')
        with patch('policy_agent.collect.fetch', return_value=response(conflict, source.list_url)), patch.object(collector, '_detail', return_value=dict(row)):
            records, status = collector.collect_source(source, 1)
        self.assertFalse(status['entry_verified'])
        self.assertFalse(records[0]['body_valid'])

    def test_binary_browser_retry_preserves_http_failure(self):
        source = Source('TEST', 'Test', 'https://example.gov.cn/', '')
        collector = WeeklyCollector(self.root / 'evidence', use_browser=True)
        failed = FetchResult('https://example.gov.cn/file.pdf', 'https://example.gov.cn/file.pdf', None, '', '', b'', 0, 'TLS_ERROR')
        binary = response(b'%PDF-file', failed.url, 'application/pdf')
        attempts = []
        with patch('policy_agent.collect.fetch', return_value=failed), patch('policy_agent.collect.browser_binary_fetch', return_value=binary) as retry:
            result = collector._asset(source, failed.url, 'https://example.gov.cn/detail.html', attempts)
        self.assertEqual(result.content, b'%PDF-file')
        self.assertEqual(attempts[0]['error'], 'TLS_ERROR')
        self.assertEqual(attempts[1]['method'], 'browser_asset')
        self.assertTrue(Path(attempts[1]['evidence_path']).is_file())
        self.assertEqual(retry.call_args.args[1], 'https://example.gov.cn/detail.html')

    def test_spreadsheet_formulas_without_cached_values_fail(self):
        data = BytesIO()
        book = Workbook(); book.active['A1'] = TEXT; book.active['B1'] = '=1+1'
        book.save(data); book.close()
        with self.assertRaisesRegex(ValueError, 'SPREADSHEET_FORMULA_VALUE_MISSING'):
            document_text(response(data.getvalue()))

    def test_vue_literal_article_is_read_without_executing_interpolation(self):
        content = '<div id="news-details"></div><script>new Vue({el: "#news-details", data: {content: `<p>' + TEXT + '</p><img src="/scan.png">`}})</script>'
        original = response(content)
        hydrated = hydrate_literal_article(original)
        self.assertNotEqual(hydrated.text, original.text)
        self.assertEqual(body_image_links(hydrated.text, original.final_url, 'example.gov.cn'), ['https://example.gov.cn/scan.png'])
        self.assertEqual(hydrate_literal_article(response(content.replace(TEXT, '${fetch("https://other.example")}'))).text, content.replace(TEXT, '${fetch("https://other.example")}'))

    def test_numeric_content_ids_do_not_supply_publication_dates(self):
        self.assertEqual(parse_date('content_9876543210123456789.html'), '')
        self.assertEqual(parse_date('/20261006/t20261006_1.html'), '2026-10-06')
        html = '<div><a href="/content_9876543210123456789.html"></a><a href="/content_9876543210123456789.html" title="' + TITLE + '">' + TITLE + '</a><span>2026-09-30</span></div>'
        links = absolute_links(html, 'https://example.gov.cn/')
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['date'], '2026-09-30')

    def test_docx_embedded_body_image_is_not_silently_omitted(self):
        data = BytesIO()
        image = BytesIO(); Image.new('RGB', (100, 100), 'white').save(image, format='PNG')
        with ZipFile(data, 'w') as z:
            z.writestr('word/document.xml', '<w:document xmlns:w="test" xmlns:r="rel"><w:t>' + TEXT + '</w:t><w:blip r:embed="rId1"/></w:document>')
            z.writestr('word/_rels/document.xml.rels', '<Relationships><Relationship Id="rId1" Target="media/image1.png"/></Relationships>')
            z.writestr('word/media/image1.png', image.getvalue())
        with patch('policy_agent.ocr.recognize', return_value={'valid': False, 'error': 'OCR_EMPTY_OR_LOW_CONFIDENCE'}):
            with self.assertRaisesRegex(ValueError, 'DOCX_IMAGE_OCR_INCOMPLETE'):
                document_text(response(data.getvalue()), self.root)
        with patch('policy_agent.ocr.recognize', return_value={'valid': True, 'text': '附件图中的具体政策要求。'}):
            text, suffix = document_text(response(data.getvalue()), self.root)
        self.assertIn('附件图中的具体政策要求', text)

    def test_no_new_requires_prior_body_acceptance_and_complete_date_coverage(self):
        source = Source('TEST', 'Test', 'https://example.gov.cn/', 'https://example.gov.cn/policy/index.html', body_acceptance='Passed')
        listing = f'<li><a href="/20260901/t20260901_1.html">{TITLE}</a>2026-09-01</li><a href="/unrelated/index.html">政务公开</a>'
        collector = WeeklyCollector(self.root / 'evidence')
        with patch('policy_agent.collect.fetch', return_value=response(listing, source.list_url)):
            records, status = collector.collect_source(source, 3, since=date(2026, 9, 30), until=date(2026, 10, 6))
        self.assertEqual(status['status'], 'NoNew')
        self.assertEqual(status['body_success'], 0)
        source.body_acceptance = ''
        with patch('policy_agent.collect.fetch', return_value=response(listing, source.list_url)):
            records, status = collector.collect_source(source, 3, since=date(2026, 9, 30), until=date(2026, 10, 6))
        self.assertEqual(status['status'], 'Failed')

    def test_old_entry_does_not_suppress_another_entries_pagination(self):
        source = Source('TEST', 'Test', 'https://example.gov.cn/', 'https://example.gov.cn/old/index.html', entry_urls=['https://example.gov.cn/old/index.html', 'https://example.gov.cn/new/index.html'])
        old = f'<li><a href="/20260901/t20260901_1.html">{TITLE}</a>2026-09-01</li>'
        new = f'<li><a href="/20261006/t20261006_1.html">{TITLE}</a>2026-10-06</li><a href="index_1.html">下一页</a>'
        collector = WeeklyCollector(self.root / 'evidence')
        def get(url, *args):
            return response(old if '/old/' in url or 'index_1' in url else new, url)
        with patch('policy_agent.collect.fetch', side_effect=get), patch.object(collector, '_detail', return_value={'review_status':'Collected','body_valid':True}):
            records, status = collector.collect_source(source, 5, since=date(2026, 9, 30), until=date(2026, 10, 6))
        self.assertEqual(status['pagination_pages'], 1)
        self.assertEqual(status['pages_visited'], 3)
        self.assertEqual(status['body_success'], 1)

    def test_explicit_pagination_and_weekly_limit_remain_visible(self):
        self.assertEqual(pagination_links("createPageHTML(3,0,'index','html')", 'https://example.gov.cn/policy/index.html'), ['https://example.gov.cn/policy/index_1.html'])
        listing = ''.join(f'<li><a href="/20261006/t20261006_{i}.html">{TITLE}{i}</a>2026-10-06</li>' for i in range(4))
        source = Source("TEST", "Test", "https://example.gov.cn/", "https://example.gov.cn/policy/index.html")
        collector = WeeklyCollector(self.root / "evidence")
        row = {"review_status": "Collected", "body_valid": True}
        with patch("policy_agent.collect.fetch", return_value=response(listing, source.list_url)), patch.object(collector, "_detail", return_value=row):
            records, status = collector.collect_source(source, 3, since=date(2026, 9, 29), until=date(2026, 10, 6))
        self.assertEqual(status["coverage"], "incomplete")
        self.assertEqual(status["status"], "Partial")


if __name__ == "__main__":
    unittest.main()
