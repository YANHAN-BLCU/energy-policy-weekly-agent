import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch
from pathlib import Path
from policy_agent.collect import WeeklyCollector
from policy_agent.http import FetchResult
from policy_agent.paths import PACKAGE_ROOT
from policy_agent.dynamic import hydrate_datastore, literal_list_redirect
from policy_agent.models import Source
from policy_agent.navigation import energy_entries, authority_matches, pagination_links
from policy_agent.parse import attachment_links, select_policy_links
from policy_agent.scope import energy_policy_candidate


class FailureRepairTests(unittest.TestCase):
    def test_literal_download_button_and_host_boundary(self):
        html = '<a onclick="downloadFj(\'指南.doc\',\'./W020260101000000000001.doc\')">指南.doc</a>'
        url = 'https://sthjj.cq.gov.cn/policy/202609/t20260914_123.html'
        self.assertEqual(attachment_links(html, url, 'sthjj.cq.gov.cn')[0]['url'],
                         'https://sthjj.cq.gov.cn/policy/202609/W020260101000000000001.doc')
        external = html.replace('./W020260101000000000001.doc', 'https://untrusted.example/doc.doc')
        self.assertEqual(attachment_links(external, url, 'sthjj.cq.gov.cn'), [])
        injected = html.replace('downloadFj(', 'sendSecrets();downloadFj(')
        self.assertEqual(attachment_links(injected, url, 'sthjj.cq.gov.cn'), [])

    def test_local_energy_entry_does_not_follow_other_provinces(self):
        source = Source('GD EA', 'Energy', 'https://drc.gd.gov.cn/', 'https://drc.gd.gov.cn/', level='Provincial')
        html = '<a href="/snyj/index.html">广东省能源局</a><a href="https://www.nea.gov.cn/">国家能源局</a>'
        html += '<a href="/other/index.html">浙江省能源局</a>'
        self.assertEqual([item['url'] for item in energy_entries(source, html, source.website)], ['https://drc.gd.gov.cn/snyj/index.html'])
        self.assertTrue(authority_matches(source, '<meta name="SiteName" content="广东省发展和改革委员会"><meta name="ColumnName" content="省能源局">', 'https://drc.gd.gov.cn/snyj/index.html'))
        self.assertFalse(authority_matches(source, '<meta name="SiteName" content="广东省发展和改革委员会"><meta name="ColumnName" content="一般政策">', 'https://drc.gd.gov.cn/general/index.html'))
        base='<meta name="SiteName" content="广东省发展和改革委员会">'
        self.assertFalse(authority_matches(source,base+'<a href="https://www.nea.gov.cn/">国家能源局</a>',source.website))
        self.assertFalse(authority_matches(source,base+'<a href="/20261008/t20261008_1.html">转发国家能源局新能源政策的通知</a>',source.website))
        self.assertTrue(authority_matches(source,base+'<a href="/snyj/index.html">广东省能源局</a>',source.website))

    def test_energy_technical_terms_are_not_missed(self):
        for title in ('关于印发示例虚拟电厂管理办法的通知', '关于公布示例重点用能单位名单的通知', '关于印发示例低碳园区建设实施方案的通知', '示例煤基固废生态修复技术规范征求意见公告'):
            self.assertEqual(energy_policy_candidate({'text': title})['decision'], 'Collect')

    def test_empty_identity_metadata_falls_back_to_official_title(self):
        source = Source('HEB DRC', 'DRC', 'https://hbdrc.hebei.gov.cn/', 'https://hbdrc.hebei.gov.cn/', level='Provincial')
        self.assertTrue(authority_matches(source, '<title>河北省发展和改革委员会</title><meta name="SiteName" content="">', source.website))
        self.assertFalse(authority_matches(source, '<title>河北省发展和改革委员会</title><meta name="SiteName" content="国家发展和改革委员会">', source.website))

    def test_duplicate_date_link_cannot_hide_full_policy_title(self):
        html = '<li><a href="./202609/t20260901_123.html">2026-09-01</a>'
        html += '<a href="./202609/t20260901_123.html" title="河北省发展和改革委员会关于示例电力需求响应管理办法的通知">河北省发展和改革委员会关于示例...</a></li>'
        links = select_policy_links(html, 'https://hbdrc.hebei.gov.cn/xxgk_2232/zc/wzcwj/')
        self.assertEqual(len(links), 1)
        self.assertIn('电力需求响应', links[0]['text'])
        self.assertEqual(links[0]['date'], '2026-09-01')
        self.assertEqual(energy_policy_candidate(links[0])['decision'], 'Collect')

    def response(self, url, text='', status=200):
        return FetchResult(url, url, status, 'text/html', text, text.encode('utf-8'), 1, '' if status == 200 else 'HTTP_' + str(status))

    def test_energy_portal_proof_allows_only_energy_candidates(self):
        source = Source('HEN EA', '能源局', 'https://fgw.henan.gov.cn/', 'https://fgw.henan.gov.cn/policy/index.html', level='Provincial')
        home = '<meta name="SiteName" content="河南省发展和改革委员会"><meta name="ColumnName" content="河南省能源局">'
        listing = '<meta name="SiteName" content="河南省发展和改革委员会"><meta name="ColumnName" content="政策文件">'
        listing += '<li><a href="/20261008/t20261008_1.html">关于完善新能源发电价格机制的通知</a>2026-10-08</li>'
        listing += '<li><a href="/20261008/t20261008_2.html">关于完善医疗保障管理办法的通知</a>2026-10-08</li>'
        with TemporaryDirectory(dir=PACKAGE_ROOT) as tmp:
            collector = WeeklyCollector(tmp)
            def fetch(url, *args):
                return self.response(url, home if url == source.website else listing)
            with patch('policy_agent.collect.fetch', side_effect=fetch), patch.object(collector, '_detail', return_value={'body_valid':True, 'review_status':'Collected'}) as detail:
                rows, status = collector.collect_source(source, 3)
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]['body_valid'])
            self.assertEqual(detail.call_count, 1)
            self.assertTrue(status['discovery'][0]['energy_portal_inherited'])
            self.assertTrue(Path(status['discovery'][0]['authority_evidence']).is_file())
            self.assertEqual(status['scope_filtered_count'], 1)
            with patch('policy_agent.collect.fetch', side_effect=lambda url,*args:self.response(url, listing)), patch.object(collector,'_detail',return_value={'body_valid':True,'review_status':'Collected'}) as wrong_detail:
                rows, status = WeeklyCollector(tmp).collect_source(source,3)
            self.assertFalse(rows[0]['body_valid'])
            self.assertFalse(status['discovery'][0]['energy_portal_inherited'])
            wrong_detail.assert_not_called()

    def test_detail_http_error_uses_secure_official_equivalent(self):
        source = Source('TEST', 'Test', 'https://example.gov.cn/', 'https://example.gov.cn/policy/index.html')
        url='http://example.gov.cn/20261008/t20261008_1.html'
        title='节能项目管理规定'
        article='<meta name="ArticleTitle" content="'+title+'"><div class="TRS_Editor">'+'节能项目应按照规定执行审批程序，主管部门负责监督项目实施和核验节能效果。'*10+'</div>'
        with TemporaryDirectory(dir=PACKAGE_ROOT) as tmp:
            collector = WeeklyCollector(tmp)
            with patch('policy_agent.collect.fetch', side_effect=[self.response(url,status=412),self.response(url.replace('http:','https:'),article)]) as fetch:
                row = collector._detail(source, {'url':url,'text':title}, source.list_url)
            self.assertTrue(row['body_valid'])
            self.assertEqual(fetch.call_count, 2)
            self.assertTrue(row['detail_url'].startswith('https:'))
            self.assertEqual(row['attempts'][0]['http_status'],412)

    def test_static_datastore_exposes_titles_dates_and_observed_pagination(self):
        markup='<datastore><recordset><record><![CDATA[<li><a href="/art/2026/9/28/art_15201_1.html" title="关于印发节能改造管理办法的通知">节能改造通知</a><span>2026-09-28</span></li>]]></record></recordset>'
        markup+='<nextgroup><![CDATA[<a href="/module/web/jpage/dataproxy.jsp?page=1&amp;columnid=15201"></a>]]></nextgroup></datastore>'
        page=self.response('http://gxt.shandong.gov.cn/col/col15201/index.html','<script type="text/xml">'+markup+'</script>')
        hydrated=hydrate_datastore(page)
        links=select_policy_links(hydrated.text,hydrated.final_url)
        self.assertEqual(len(links),1)
        self.assertIn('管理办法',links[0]['text'])
        self.assertEqual(links[0]['date'],'2026-09-28')
        self.assertEqual(pagination_links(hydrated.text,hydrated.final_url),['http://gxt.shandong.gov.cn/module/web/jpage/dataproxy.jsp?page=1&columnid=15201'])
        malicious=page.text.replace('/module/web/jpage/dataproxy.jsp','https://evil.example/module/web/jpage/dataproxy.jsp')
        self.assertEqual(pagination_links(hydrate_datastore(self.response(page.url,malicious)).text,page.url),[])

    def test_list_redirect_is_literal_and_official(self):
        page=self.response('http://gxt.shandong.gov.cn/col/col15190/index.html','<script> location.href="/col/col15201/index.html"; </script>')
        self.assertEqual(literal_list_redirect(page),'http://gxt.shandong.gov.cn/col/col15201/index.html')
        self.assertEqual(literal_list_redirect(self.response(page.url,page.text.replace('/col/col15201/index.html','https://evil.example/'))),'')
        self.assertEqual(literal_list_redirect(self.response(page.url,'<script>sendSecrets();location.href="/col/col15201/index.html";</script>')),'')

    def test_browser_context_body_retains_evidence_and_stable_policy_url(self):
        source=Source('TEST','Test','https://example.gov.cn/','https://example.gov.cn/policy/index.html')
        url='https://example.gov.cn/20261008/t20261008_1.html'
        title='节能项目管理规定'
        html='<meta name="ArticleTitle" content="'+title+'"><div class="TRS_Editor">'+'节能项目应按照规定执行审批程序，主管部门负责监督项目实施和核验节能效果。'*10+'</div>'
        context=self.response(url+'?temporary=public-browser-session',html)
        context.text=''
        with TemporaryDirectory(dir=PACKAGE_ROOT) as tmp:
            collector=WeeklyCollector(tmp,use_browser=True)
            with patch('policy_agent.collect.fetch',return_value=self.response(url,status=412)), \
                 patch('policy_agent.collect.browser_fetch',return_value=self.response(url,status=400)), \
                 patch('policy_agent.collect.browser_binary_fetch',return_value=context) as warm:
                row=collector._detail(source,{'url':url,'text':title},source.list_url)
            self.assertTrue(row['body_valid'])
            self.assertEqual(row['detail_url'],url)
            self.assertIn('temporary=',row['response_url'])
            self.assertEqual(row['collector_method'],'browser_context')
            self.assertTrue(Path(row['evidence_path']).is_file())
            warm.assert_called_once_with(url,source.list_url)

    def test_browser_context_can_recover_a_blocked_policy_list(self):
        source=Source('TEST','Test','https://example.gov.cn/','https://example.gov.cn/policy/index.html')
        html='<li><a href="/20261008/t20261008_1.html">关于节能项目申报的通知</a>2026-10-08</li>'
        context=self.response(source.list_url+'?temporary=session',html)
        context.text=''
        with TemporaryDirectory(dir=PACKAGE_ROOT) as tmp:
            collector=WeeklyCollector(tmp,use_browser=True)
            with patch('policy_agent.collect.fetch',return_value=self.response(source.list_url,status=412)), \
                 patch('policy_agent.collect.browser_fetch',return_value=self.response(source.list_url,status=400)), \
                 patch('policy_agent.collect.browser_binary_fetch',return_value=context), \
                 patch.object(collector,'_detail',return_value={'body_valid':True,'review_status':'Collected'}) as detail:
                rows,status=collector.collect_source(source,1)
            self.assertEqual(len(rows),1)
            self.assertEqual(status['body_success'],1)
            self.assertEqual(status['discovery'][0]['method'],'browser_context')
            self.assertEqual(detail.call_args.args[2],source.list_url)
            self.assertTrue(Path(status['discovery'][0]['api_attempts'][0]['evidence_path']).is_file())
