from datetime import date
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from policy_agent.collect import WeeklyCollector
from policy_agent.http import FetchResult
from policy_agent.models import Source
from policy_agent.parse import absolute_links
from policy_agent.paths import PACKAGE_ROOT
from policy_agent.scope import energy_policy_candidate


class EnergyScopeTests(unittest.TestCase):
    def test_energy_policy_forms_are_admitted(self):
        for title in ("关于调整天然气销售价格的通知", "关于印发储能项目管理办法的通知",
                      "电力市场交易实施细则", "关于碳排放配额分配方案的公告",
                      "新能源汽车充电设施建设规划", "光伏发电国家标准", "中华人民共和国能源法"):
            with self.subTest(title=title):
                self.assertEqual(energy_policy_candidate({"text": title})["decision"], "Collect")

    def test_energy_words_cannot_override_nonpolicy_exclusions(self):
        for title in ("关于能源局干部任免的通知", "能源局召开电力政策会议",
                      "关于印发能源论坛领导发言材料的通知", "新能源发展座谈会讲话",
                      "能源局部门预算公告", "电力行业专业人员继续教育通知",
                      "节能政策答记者问", "关于煤矿安全会议纪要的通知"):
            with self.subTest(title=title):
                self.assertEqual(energy_policy_candidate({"text": title})["decision"], "Exclude")

    def test_publisher_and_unavailable_body_do_not_supply_topic_evidence(self):
        for item in ({"text": "国家能源局关于信息系统管理办法的通知"},
                     {"text": "项目申报通知", "summary": "发布机构：国家能源局"},
                     {"text": "项目申报通知", "agency_name": "能源局", "column": "能源政策",
                      "body_text": "支持光伏发电项目"}):
            self.assertEqual(energy_policy_candidate(item)["decision"], "Needs review")

    def test_list_row_summary_can_supply_topic_evidence(self):
        links = absolute_links('<li><a href="/20261008/t20261008_1.html">项目申报通知</a>'
                               '<span>支持光伏发电和储能项目</span></li>', 'https://example.gov.cn/')
        self.assertEqual(energy_policy_candidate(links[0])["decision"], "Collect")

    def test_navigation_and_neighbor_titles_are_not_a_summary(self):
        html = '<div>能源政策<ul><li><a href="/20261008/t20261008_1.html">项目申报通知</a></li>'
        html += '<li><a href="/20261008/t20261008_2.html">光伏项目通知</a></li></ul></div>'
        links = absolute_links(html, 'https://example.gov.cn/')
        self.assertEqual(energy_policy_candidate(links[0])["decision"], "Needs review")

    def test_other_sector_policy_is_excluded(self):
        self.assertEqual(energy_policy_candidate({"text": "关于完善医疗保障管理办法的通知"})["decision"], "Exclude")

    def collector(self, path):
        source = Source('TEST', 'Test', 'https://example.gov.cn/', 'https://example.gov.cn/policy/index.html', body_acceptance='Passed')
        return WeeklyCollector(path), source

    def listing(self, source, titles):
        html = ''.join(f'<li><a href="/20261008/t20261008_{i}.html">{title}</a>2026-10-08</li>'
                       for i, title in enumerate(titles))
        raw = html.encode('utf-8')
        return FetchResult(source.list_url, source.list_url, 200, 'text/html', html, raw, 1)

    def test_excluded_and_uncertain_candidates_never_fetch_details_or_ocr(self):
        with TemporaryDirectory(dir=PACKAGE_ROOT) as tmp:
            collector, source = self.collector(tmp)
            listing = self.listing(source, ['关于完善医疗保障管理办法的通知', '关于项目管理办法的通知'])
            with patch('policy_agent.collect.fetch', return_value=listing) as fetch, \
                 patch.object(collector, '_detail') as detail, \
                 patch.object(collector, '_parse') as parse, \
                 patch('policy_agent.ocr.recognize') as ocr:
                rows, status = collector.collect_source(source, 1)
            self.assertEqual(rows, [])
            self.assertEqual(fetch.call_count, 1)
            detail.assert_not_called(); parse.assert_not_called(); ocr.assert_not_called()
            self.assertEqual(status['scope_filtered_count'], 2)
            self.assertEqual(status['scope_review_count'], 1)
            self.assertEqual(status['body_failed'], 0)
            self.assertEqual(status['status'], 'ScopeReview')
            self.assertTrue(all(not item['body_fetched'] for item in status['scope_filtered']))

    def test_filtering_precedes_candidate_limit(self):
        with TemporaryDirectory(dir=PACKAGE_ROOT) as tmp:
            collector, source = self.collector(tmp)
            listing = self.listing(source, ['关于完善医疗保障管理办法的通知', '关于储能项目管理办法的通知'])
            with patch('policy_agent.collect.fetch', return_value=listing), \
                 patch.object(collector, '_detail', return_value={'body_valid': True, 'review_status': 'Collected'}) as detail:
                rows, status = collector.collect_source(source, 1)
            self.assertEqual(len(rows), 1)
            self.assertIn('储能', detail.call_args.args[1]['text'])
            self.assertEqual(status['scope_filtered_count'], 1)

    def test_uncertain_candidate_cannot_be_hidden_by_old_date_boundary(self):
        with TemporaryDirectory(dir=PACKAGE_ROOT) as tmp:
            collector, source = self.collector(tmp)
            listing = self.listing(source, ['关于项目管理办法的通知'])
            listing.text += '<li><a href="/20260901/t20260901_1.html">关于储能项目管理办法的通知</a>2026-09-01</li>'
            listing.content = listing.text.encode('utf-8')
            with patch('policy_agent.collect.fetch', return_value=listing), patch.object(collector, '_detail') as detail:
                rows, status = collector.collect_source(source, 3, since=date(2026, 10, 2), until=date(2026, 10, 8))
            self.assertEqual(status['status'], 'ScopeReview')
            detail.assert_not_called()


if __name__ == '__main__':
    unittest.main()
