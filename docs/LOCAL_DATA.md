---
name: local-policy-data
description: 本地来源配置、机构与标签字典的导入格式和原表一致性检查要求。
---

# 本地数据

公开包只包含虚构的结构示例。真实数据由用户保存在本地，经 `scripts/init_local_data.py --sources <JSON> --dictionary <JSON>` 只读导入；脚本不会覆盖已有本地资产。导入前校验必填结构、唯一代码、分类配对和固定输出字段，再生成文档及本地 SHA256 清单。

来源文件以 `sources` 列表为根，每项至少有 `code`、`name`、`website`、`list_url`；来源代码须有机构映射。可选 `enabled`、`adapter`、`allowed_hosts`、`body_selectors`、`entry_urls` 和 `pagination_pages` 等字段见 `policy_agent/models.py`。列表入口及跨域附件地址须逐站核验；启用来源并不代表正文验收通过。

字典字段完整结构见 `examples/mi_dictionary.example.json`。`agencies` 与 `issuer_units` 各项含 `code`、英文 `name`、`chinese_name`；可选 `aliases` 仅用于识别正文，英文译名仍以 name 为准。`code_aliases` 可将历史代码映射到现有代码，不能覆盖现有代码或指向未知机关。`policy_tags` 每项含 `category`、`tag`、`reference_cell`，保留原表大小写及分类归属。输出字段 `export_fields` 名称与顺序固定。

参考表需有 `Agency abb.` 和 `Policy Tags` 工作表；机构代码、中英文及行顺序保留，标签只去除首尾空白。有 Issuing Agency 嵌入图片时，人工核对机关层级、英译与联合发文顺序，填写 `issuer_units`、`issuing_agency_examples` 及 `issuing_agency_images` 的部件名和 SHA256。图片变化必须重新人工复核；程序不会从空单元格推断图片里的译名。`reference_sha256` 为完整文件摘要，`reference_file` 仅供本地核对。

每次安装、迁移、更新字典及定稿检查时，必须核对与用户原表是否一致。执行 `scripts/check_mi_dictionary.py --reference <原表>` 逐条对照，而不能只比较词条数量；未提供原表时报告仅核验本地快照。生成表再用 `--workbook <包内表单>` 核对机构英译、行业标签配对、字典表以及真实超链接。不一致阻止定稿与邮件交付。

导入生成的真实来源、字典、独立 Markdown 字典和清单均为本地私有资产；不要添加到 Git、源码包或公开发布附件。导入脚本只承诺格式和一致性检查，内容翻译仍须核对用户参考表。
