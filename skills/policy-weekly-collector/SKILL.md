---
name: policy-weekly-collector
description: 每周一次在正文获取前筛选能源政策，抓取合格候选正文并保全证据，由宿主 AI 分类总结，生成 MI 类 XLSX 并通过宿主邮件工具交付。仅用于每周能源政策工作流。
---

# Policy Weekly Collector

读取包根目录 [SKILL.md](../../SKILL.md) 作为完整执行规范。本入口适合能发现嵌套技能目录的宿主；不要求用户配置模型、模型 API、邮件密码或时区。所有依赖、缓存、浏览器、配置和产物必须位于包目录；先用 `bootstrap.py` 创建并使用包内 `.venv`，不使用全局安装。

公开包不带真实业务数据；先按根目录技能规范导入本地来源与字典。安装、迁移和表单检查时读取生成的 [MI_DICTIONARY.md](../../docs/MI_DICTIONARY.md)。检查时必须核对与表是否一致：包括机构中英文及联合发文、行业标签配对、字典表和实际超链接；原 MI 可用时运行 check_mi_dictionary.py --reference 对照原表，无原表时只报告打包字典核验结果。不一致不能发送表单。

严格保持以下顺序：

1. 首次安装先执行 `bootstrap.py --browser`，只收集邮箱、每周星期和 HH:MM 触发时间，使用宿主的每周调度和已连接附件邮件工具。
2. 执行 `run_weekly.py --stage collect`，先由代码用列表标题及同条摘要筛选能源政策，排除人事任免、会议、发言等非政策内容；主题不明确的候选保存到 `scope_filtered.json`。这一筛选不获取详情正文或附件、不调用 AI。只对放行候选取得正文及核心附件、保存证据、过滤可靠日期的最近 7 天记录；只有正文验收通过才写入 `analysis_request.json`，失败单独保存到 `failed_details.json`。
3. 宿主 AI 只依据该请求中的原文分析，按 [HOST_PROTOCOL.md](../../docs/HOST_PROTOCOL.md) 写 `analysis.json`；行业和标签选 MI 英文字典原词，发文机关选择 MI 代码并逐条给出正文发文证据，不能以转载站点代替签署者。不得修改代码事实字段。
4. 执行 `run_weekly.py --stage finalize --run-dir <运行目录>` 生成工作簿和 `delivery_request.json`。
5. 用宿主邮件工具发送该请求中的唯一 XLSX 附件，保存真实 `receipt.json`，再执行 receipt 阶段。只有 `sent` 回执推进 URL 去重。

正文缺失、栏目页、验证码、扫描图片未识别、核心附件缺失均为采集失败，不能进入成功政策表或 AI 摘要。正文完整而日期不可靠时才标记日期待复核；邮件连接不可用时标记待发送。失败不推进 URL 去重，下周可重试。不得把没有回执的文件描述为已发送，也不得扩大到历史全量建库或其他通知任务。
