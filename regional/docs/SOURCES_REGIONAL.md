# 省市级来源配置说明（sources_regional.json）

本文件由 `Police_Site_Classify_20261012` 分类表生成，是省市级周报技能的唯一来源清单。

## 结构

| 字段 | 含义 |
| --- | --- |
| `code` | 机构代码（与 MI 字典一致，如 `GD DRC`） |
| `name` / `chinese_name` | 机构中英文名 |
| `level` | 固定 `Regional` |
| `region` | 大区（East China 等） |
| `class` | 抓取分类：`A` 静态直取 / `C` 网关阻断 |
| `website` | 官网入口 |
| `list_url` | 列表采集入口（优先政策入口栏目，非文章页） |
| `adapter` | 固定 `auto`（走通用 HTML 解析） |
| `max_items` | 单站最多取候选数 |
| `entry_urls` | 入口 URL 候选集 |
| `sample_article` | 审计发现的政策样本文章（仅线索，非列表入口） |
| `fallback` | 仅 C 类：`ua_rotate`（换 UA 重试） |

## 分类口径

- **A 静态直取（215 条）**：默认 UA 直接 HTTP GET 即可。
- **C 网关阻断（14 条）**：默认 UA 被 412/444 拦截，需换 UA / 补请求头重试；仍失败记 `GATEWAY_BLOCKED`，交宿主 AI 搜索复查。

## 人工订正记录（2026-10-12）

| 机构 | 订正 |
| --- | --- |
| SD DIIT / SD GO / SD EIT / SD PG | `https` → `http`（山东站点仅 http 可达） |
| QH DRC | 补全 `http://fgw.qinghai.gov.cn/` |
| HEB EA | 补全 `http://hbdrc.hebei.gov.cn/` |
| HI DIIT / HI GO / HI PG | 补政策入口 `https://www.hainan.gov.cn/hainan/zfwj/szfzcwj.shtml` |

## 覆盖

229 条省市级机构（31 个省级行政区），全部已收录于 MI 字典（249 机构）。
