---
name: policy-weekly-regional
description: 轻量静态省市级能源政策周报采集技能。纯 requests + BeautifulSoup 抓取省/市级政府网站列表与详情（不启用浏览器、不执行 JavaScript、不抓动态接口、不下载任何附件），内置 229 个省市级机构来源（215 条静态直取 + 14 条网关阻断换 UA 重试），按关键词筛选能源政策，列表或详情不足时交宿主 AI 搜索复查，每周仅调用一次宿主 AI 生成摘要与分类，最终产出一个省市级 Excel 周报（首表 + Issues 附表）。当用户要求生成省市级能源政策周报、采集各省市发改委/能源局/工信厅/生态环境厅等地方政策、或运行每周地方政策情报任务时使用。
---

# 轻量静态省市级政策周报

纯静态采集：只用 `requests` + `BeautifulSoup` 读网页 HTML 文字，**不启用浏览器、不执行 JavaScript、不抓动态接口、不下载 PDF/Word/Excel/图片/附件**。与国家级技能（`policy-weekly-static`）共用同一套静态引擎，差异只在来源配置与按 `class` 分流的请求策略。

职责边界：本技能负责**采集、筛选、成表**；宿主 AI 只负责两处——为已通过验收的记录生成摘要与分类，以及必要时对少量条目做搜索复查。

## 来源与分类

来源配置 `config/sources_regional.json`，229 条省市级机构，按抓取方案分为两类：

| class | 含义 | 数量 | 请求策略 |
| --- | --- | ---: | --- |
| `A` | 静态直取 | 216 | 默认 UA 直接 HTTP GET |
| `E` | 静态排除（JS 动态防护，HTTP 412/473） | 13 | **不进静态队列**（`enabled=false`），固定走宿主 AI 搜索直采 |

> **E 类实测结论（2026-10-12）**：甘肃（7）、湖北（5）、青海财政厅（1）返回的 412/473 由 **JS 动态防护**（如瑞数 `$_ts` 挑战）产生——换 UA、Referer、Cookie、完整浏览器头**全部无效**，纯静态无法绕过。这 13 条**不进静态采集队列**，由 `config/search_sources.json` 单列，**固定走宿主 AI 搜索直采**。云南生态环境厅实测首页 HTTP 200 可达（原审计误判 444），已归入 A 类，其政策栏目入口待定位。

## 链路

```
① 列表采集（标题/日期/摘要/链接）——仅 A 类静态直取（E 类不进队列）
② 关键词筛选（能源政策）
③ 详情抓取（可见 HTML 文字 + 正文验收）
④ 宿主 AI 搜索（E 类 13 条 JS 防护站点固定走搜索 + 少量列表/详情不足条目；限次）
⑤ 宿主 AI 生成一次（摘要/行业/标签/影响分析）
⑥ 成表（省市级一个 Excel：首表 + Issues）
```

## 首次使用

依赖极简，无需构建环境。若缺少依赖：

```text
pip install requests beautifulsoup4 openpyxl
```

工作目录可用环境变量 `POLICY_STATIC_WORKDIR` 指定（技能目录只读时用）；未设时默认落在技能目录下的 `runs/`。

## 第①~③步：采集 + 筛选 + 抓详情

```text
python3 "<技能目录>/scripts/run_weekly_regional.py" --days 7
```

参数：`--days 7`（日期窗口）、`--only CODE1,CODE2`（仅指定来源，如 `GD DRC`）、`--province 广东`（**定向查询单个省份/大区**）、`--class A,E`（仅指定分类）、`--max-per-source 30`、`--out-dir <目录>`。

### 定向查询单个省份（用户说"查某省情报"时）

用户提出查询某个省份时，**只跑该省的相关站点，不做全量**：

```text
python3 "<技能目录>/scripts/run_weekly_regional.py" --days 7 --province 广东
```

`--province` 支持**省名 / 简称 / 代码前缀 / 大区**四种写法，自动匹配该省全部机构：

| 输入示例 | 匹配 |
| --- | --- |
| `广东` / `粤` / `GD` | 广东全部 9 个机构 |
| `内蒙古` / `内蒙古自治区` / `NM` | 内蒙古全部 7 个机构 |
| `华东` | East China 大区全部 55 个机构 |

匹配后：静态队列只跑该省的 A 类站点；`search_sources.json` 也只保留该省的 E 类站点（如查甘肃 → 静态 0 条、搜索 7 条）。产出 Excel 命名为 `Police_<yymmdd>_Test_<省名>.xlsx`（如 `Police_261012_Test_广东.xlsx`）；不指定省份时命名 `..._Test_Regional.xlsx`。

> 省份映射表见 `scripts/provinces.py`（31 个省级行政区 × 省名/简称/代码前缀/大区）。

返回 JSON 含 `run_dir`，后续阶段都以它为准。产出：

| 文件 | 内容 |
| --- | --- |
| `candidates.json` | 列表候选，每条含标题/摘要/日期/链接/关键词判定 |
| `analysis_request.json` | **正文已验收**的记录（交宿主 AI 生成摘要） |
| `review_needed.json` | 需宿主 AI 搜索复查的条目 |
| `search_sources.json` | **静态排除站点（E 类）搜索直采清单**，交宿主 AI 逐条搜索 |
| `failed_details.json` | 详情抓取失败/文字不足 |
| `evidence/` | 列表页与详情页原始 HTML |
| `run.json` | 本次运行元信息（含 `source_status` 每站状态） |

## 第④步：宿主 AI 搜索（限次）

分两部分：

**（一）静态排除站点（E 类，固定走搜索）**：读 `<run_dir>/search_sources.json`，对其中每条机构用 `search_query` 做一次搜索，找该机构本周发布的能源政策官方页面。这部分是**固定动作**，不占用"复查"限次额度。

**（二）条目复查**：读 `<run_dir>/review_needed.json`，对其中条目做**限定次数的**搜索复查（建议每期不超过 10 次查询）：

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
      "issuing_agencies": [{"code": "GD DRC", "evidence_quote": "广东省发展和改革委员会"}],
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
- `issuing_agencies`：按原文顺序取字典 code（省市级机构 code 形如 `GD DRC`、`JS DRC`），附正文中**逐字存在**的 `evidence_quote`；不把收文单位、转载站当发布者；字典未覆盖或证据不足时不猜。
- `policy_abstract` / `impact_analysis`：中文；区分明确条款与推断。
- 全部记录须覆盖，每个字段非空。正文缺失是采集失败，禁止用失败说明填充摘要。

## 第⑥步：成表

```text
python3 "<技能目录>/scripts/build_workbook.py" "<run_dir>"
```

产出 `<run_dir>/Police_<yymmdd>_Test_<省名|Regional>.xlsx`：
- **首表** `Police_<yymmdd>_Test`：按发布日期倒序，字段为
  Policy_ID / Policy_Name / Policy_Number / Issue_Date / Issuing_Agency / Issuing_Agency_Name /
  Supported_Industry / Policy_Tags / Policy_Abstract / Impact_Analysis / Full_Text_Link /
  Source_List_URL / **Attachment_Links** / Collected_At / Collector_Method / Collection_Status /
  AI_Status / Evidence_Path
  （Full_Text_Link 与 Source_List_URL 为 Excel 原生超链接；Attachment_Links 单附件时亦为超链接）
- **Attachment_Links 列**：详情页正文中出现的可下载附件链接（.pdf/.doc/.docx/.xls/.xlsx/.wps/.zip 等），**只标注不下载**；多个用 ` ; ` 分隔，无附件为空。
- **Issues 附表**：正文失败、详情文字不足、主题待确认、网关阻断等。

生成后返回文件下载链接。

## 边界

- 不启用浏览器、不执行 JS；E 类 JS 动态防护站点不进静态队列，固定走搜索直采。
- 列表被阻断或为空时，记来源异常并交搜索复查，不臆断为「该站本周无政策」。
- 不下载任何附件/图片；**发现可下载附件时在首表 `Attachment_Links` 列标注链接**（只标注不下载），正文中的附件提示另记为「可能遗漏」。
- 采集失败 ≠ 该机构本周无政策；未通过验收的记录一律进 Issues，不得当作「无政策」。
- 附件、栏目页、验证码页不作为正文。
