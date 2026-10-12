---
name: policy-weekly-static
description: 轻量静态国家级能源政策周报采集技能。纯 requests + BeautifulSoup 抓取政府网站列表与详情（不启用浏览器、不执行 JavaScript、不抓动态接口、不下载任何附件），按关键词筛选能源政策，列表或详情不足时交宿主 AI 用搜索工具复查，每周仅调用一次宿主 AI 生成摘要与分类，最终产出一个国家级 Excel 周报（首表 + Issues 附表）。当用户要求生成国家级能源政策周报、采集国务院/国家能源局/发改委等国家级政策、或运行每周政策情报任务时使用。
---

# 轻量静态国家级政策周报

纯静态采集：只用 `requests` + `BeautifulSoup` 读网页 HTML 文字，**不启用浏览器、不执行 JavaScript、不抓动态接口、不下载 PDF/Word/Excel/图片/附件**。链路简单、依赖少、可离线审计。

职责边界：本技能负责**采集、筛选、成表**；宿主 AI 只负责一处——为已通过验收的记录生成摘要与分类，以及必要时对少量条目做搜索复查。

## 链路

```
① 列表采集（标题/日期/摘要/链接）
② 关键词筛选（能源政策）
③ 详情抓取（可见 HTML 文字 + 正文验收）
④ 宿主 AI 复查（仅列表/详情不足、主题待确认的少量条目；限次搜索）
⑤ 宿主 AI 生成一次（摘要/行业/标签/影响分析）
⑥ 成表（国家级一个 Excel：首表 + Issues）
```

## 首次使用

依赖极简，无需构建环境。若缺少依赖：

```text
pip install requests beautifulsoup4 openpyxl
```

工作目录可用环境变量 `POLICY_STATIC_WORKDIR` 指定（技能目录只读时用）；未设时默认落在技能目录下的 `runs/`。

## 第①~③步：采集 + 筛选 + 抓详情

```text
python3 "<技能目录>/scripts/run_weekly_static.py" --days 7
```

参数：`--days 7`（日期窗口）、`--only CODE1,CODE2`（仅指定来源）、`--max-per-source 30`、`--out-dir <目录>`。

固定来源：`config/sources_national.json`（20 个国家级站点：国务院、国家能源局、国家发改委、工信部、生态环境部、财政部等）。

**列表取数分两种方式**（技能自动按来源的 `adapter` 字段选择）：

| 方式 | 适用 | 来源示例 |
| --- | --- | --- |
| 通用 HTML 解析 | 列表页 HTML 直接含链接 | 国务院、发改委、生态环境部等 |
| 接口适配（纯静态，不用浏览器） | 列表页是 JS 动态渲染 | NEA（新华网 JSON 数据源）、SAC / MOHURD（JPAAS unit 接口） |

> 动态渲染站点并非无解：其数据接口参数就写在列表页 HTML 里（`datasource` 标识 / `querydata` 属性），技能直接读取并请求接口即可拿到结构化列表，无需浏览器、无需执行 JS。适配逻辑见 `scripts/list_adapters.py`。

返回 JSON 含 `run_dir`，后续阶段都以它为准。产出：

| 文件 | 内容 |
| --- | --- |
| `candidates.json` | 列表候选，每条含标题/摘要/日期/链接/关键词判定 |
| `analysis_request.json` | **正文已验收**的记录（交宿主 AI 生成摘要） |
| `review_needed.json` | 需宿主 AI 搜索复查的条目 |
| `failed_details.json` | 详情抓取失败/文字不足 |
| `evidence/` | 列表页与详情页原始 HTML |
| `run.json` | 本次运行元信息 |

## 第④步：宿主 AI 搜索复查（限次）

读 `<run_dir>/review_needed.json`，对其中条目做**限定次数的**搜索复查（建议每期不超过 10 次查询）：

- `LIST_FAILED`：列表页抓取失败 → 搜索该机构本周政策。
- `DETAIL_FAILED` / `BODY_INSUFFICIENT`：详情页抓不到正文 → 搜索该政策标题，找官方 HTML 页面。
- `TOPIC_UNCONFIRMED`：关键词无法确认主题 → 搜索该条标题，确认是否能源政策。

复查原则：**优先官方 HTML 页面**；找到了可用的官方页面就把该条补入记录；找不到就保留在 Issues，写明原因。**不要**为了凑数把搜索结果当正文，也不要扩大到无关站点。

## 第⑤步：宿主 AI 生成摘要与分类（每周仅一次）

读 `<run_dir>/analysis_request.json`，为**每条**记录生成，写入 `<run_dir>/analysis.json`：

```json
{
  "run_id": "<analysis_request.json 中的 run_id>",
  "records": [
    {
      "index": 0,
      "policy_id": "P-0001",
      "supported_industry": "Carbon",
      "policy_tags": "Energy & Carbon Saving",
      "issuing_agencies": [{"code": "NEA", "evidence_quote": "国家能源局"}],
      "policy_abstract": "基于原文的客观摘要。",
      "impact_analysis": "明确要求及可能影响，推断需注明。"
    }
  ]
}
```

字段规则（依据 `data/mi_dictionary.json`）：
- `index`：对应 `analysis_request.json` 中 records 的**顺序下标**（从 0 开始），用于回填。
- `supported_industry`：字典行业大类（category），英文原词。
- `policy_tags`：字典标签（tag），英文原词，与行业须有有效配对，多值用 ` / ` 分隔。
- `issuing_agencies`：按原文顺序取字典 code，附正文中**逐字存在**的 `evidence_quote`；不把收文单位、转载站当发布者；字典未覆盖或证据不足时不猜。
- `policy_abstract` / `impact_analysis`：中文；区分明确条款与推断。
- 全部记录须覆盖，每个字段非空。正文缺失是采集失败，禁止用失败说明填充摘要。

## 第⑥步：成表

```text
python3 "<技能目录>/scripts/build_workbook.py" "<run_dir>"
```

产出 `<run_dir>/Police_<yymmdd>_Test_National.xlsx`：
- **首表** `Police_<yymmdd>_Test`：按发布日期倒序，字段为
  Policy_ID / Policy_Name / Policy_Number / Issue_Date / Issuing_Agency / Issuing_Agency_Name /
  Supported_Industry / Policy_Tags / Policy_Abstract / Impact_Analysis / Full_Text_Link /
  Source_List_URL / **Attachment_Links** / Collected_At / Collector_Method / Collection_Status /
  AI_Status / Evidence_Path
  （Full_Text_Link 与 Source_List_URL 为 Excel 原生超链接；Attachment_Links 单附件时亦为超链接）
- **Attachment_Links 列**：详情页正文中出现的可下载附件链接（.pdf/.doc/.docx/.xls/.xlsx/.wps/.zip 等），**只标注不下载**；多个用 ` ; ` 分隔，无附件为空。
- **Issues 附表**：正文失败、详情文字不足、主题待确认、来源异常等。

生成后返回文件下载链接。

## 边界

- 不启用浏览器、不执行 JS；动态站通过其**公开数据接口**直取（参数在页面 HTML 里），仍属纯静态。
- 接口适配失败或列表为空时，记来源异常并交搜索复查，不臆断为「该站本周无政策」。
- 不下载任何附件/图片；**发现可下载附件时在首表 `Attachment_Links` 列标注链接**（只标注不下载），正文中的附件提示另记为「可能遗漏」。
- 采集失败 ≠ 该机构本周无政策；未通过验收的记录一律进 Issues，不得当作「无政策」。
- 附件、栏目页、验证码页不作为正文。
