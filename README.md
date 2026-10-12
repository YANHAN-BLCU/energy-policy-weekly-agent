# Energy policy weekly packages

本仓库包含两个独立的轻量静态能源政策采集包：

- `static/`：国家级来源，使用 `scripts/run_weekly_static.py`
- `regional/`：省市级来源，使用 `scripts/run_weekly_regional.py`

两个包均使用 `requests + BeautifulSoup`，不启用浏览器、不执行 JavaScript、不下载 PDF、Office、图片或其他附件。列表或详情文字不足时，将候选交给宿主 AI 使用搜索工具复查。

每个包都包含自己的 `SKILL.md`、来源配置、采集脚本、工作簿脚本和 MI 字典。
