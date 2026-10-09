import unittest
from policy_agent.parse import select_policy_links, extract_detail, normalize_url

LIST_HTML = '<html><a href="/policy/2026/notice.html">关于新能源项目的通知</a><a href="/news/2026/a.html">普通新闻</a><a href="/policy/2026/explain.html">政策解读</a></html>'
DETAIL_HTML = '<html><article><h1>关于新能源项目的通知</h1><p>发布日期：2026年10月1日</p><p>发文编号：示例〔2026〕1号</p><p>本通知支持新能源项目建设，推动节能减排。</p></article></html>'

class ParserTests(unittest.TestCase):
    def test_policy_link_selection(self):
        html=LIST_HTML
        links=select_policy_links(html,"https://example.com/index.html",10)
        self.assertEqual(len(links),1)
        self.assertTrue(links[0]["text"].startswith("关于新能源"))
    def test_detail_extraction(self):
        html=DETAIL_HTML
        out=extract_detail(html,"https://example.com/policy/2026/notice.html")
        self.assertEqual(out["title"],"关于新能源项目的通知")
        self.assertEqual(out["issue_date"],"2026-10-01")
        self.assertIn("2026",out["policy_number"])
        self.assertIn("节能减排",out["body_text"])
    def test_url_normalization(self):
        self.assertEqual(normalize_url("HTTPS://Example.COM/a/?b=1#fragment"),"https://example.com/a?b=1")

if __name__=="__main__": unittest.main()
