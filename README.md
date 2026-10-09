---
name: energy-policy-weekly-agent
description: 供 Codex、Workbuddy 等宿主使用的每周能源政策采集代码和技能包；公开仓库仅包含程序、文档与虚构示例。
---

# 每周能源政策 Agent

代码负责获取网页、解析正文和附件、保全证据及生成 Excel；宿主 AI 负责摘要、标签、行业分类和影响分析。工作流限定为每周一次最近七天能源政策采集、分类、总结和表单邮件交付。

公开仓库不包含真实来源清单、机构译名字典、原始参考表、政策数据、运行日志、邮箱信息或运行环境。`examples/` 的全部数据均为虚构；示例来源停用，不会访问真实网站。实际使用需要在本地导入已有来源配置与核对过的字典，不需要配置 AI、API key、SMTP 或时区。

## 安装和迁移

需要已有 Python 3.10+。以下命令在仓库目录执行；Windows PowerShell 示例：

```powershell
python -I -B -X utf8 bootstrap.py --browser
& ./.venv/Scripts/python.exe -I -B -X utf8 scripts/init_local_data.py --demo
& ./.venv/Scripts/python.exe -I -B -X utf8 scripts/check_mi_dictionary.py
& ./.venv/Scripts/python.exe run_weekly.py --setup --email "reader@example.com" --weekday MON --time "06:20"
```

`--demo` 只验证安装；替换为用户的真实邮箱前不能用于邮件交付。macOS/Linux 将解释器路径替换为 `.venv/bin/python`。依赖、Chromium、模型缓存、配置和所有运行产物限制在仓库目录内；不进行全局安装，不修改系统 PATH。

生产使用时，将第二条命令改为导入本地私有数据：

```text
<包内 Python> -I -B -X utf8 scripts/init_local_data.py --sources <本地来源JSON> --dictionary <本地核对字典JSON>
<包内 Python> -I -B -X utf8 scripts/check_mi_dictionary.py --reference <本地参考工作簿>
```

这些路径只读导入；写入的 `config/sources.json`、`policy_agent/data/mi_dictionary.json`、`docs/MI_DICTIONARY.md` 和 `PACKAGE_MANIFEST.json` 均被 Git 忽略。已有数据不会被默认覆盖。来源和字典结构见 [LOCAL_DATA.md](docs/LOCAL_DATA.md)。原表含图片时须人工核对，不会让程序猜译机构。

宿主读取根目录 [SKILL.md](SKILL.md)，首次收集接收邮箱、每周星期和 HH:MM 时间，使用自身已连接的定时任务与附件邮件能力。宿主能力未连接时不能宣称自动化安装完成。迁移后在新目录重建 `.venv` 并更新任务路径，不复制旧机器环境。

## 每周流程

1. `run_weekly.py --stage collect`：先按标题与同条摘要筛选能源政策，人事任免、会议、发言等排除；主题不明不获取正文。只对放行候选获取正文和必要附件。栏目页、验证码、空正文和缺失核心附件均是采集失败。
2. 宿主读取运行目录的 `analysis_request.json`，仅依据已验收正文写 `analysis.json`。分类使用本地字典的精确配对；机构附逐字发文证据。
3. `run_weekly.py --stage finalize --run-dir <运行目录>`：生成 Excel，重新读取核对机构译名、标签与真实超链接；不一致阻止交付。
4. 宿主按 `delivery_request.json` 发送唯一 Excel 附件，写真实 `receipt.json`，再执行 `--stage receipt --run-dir <运行目录> --receipt-file <回执>`。只有成功回执推进跨周去重。

详细协议见 [HOST_PROTOCOL.md](docs/HOST_PROTOCOL.md)。AI、定时和发送动作由宿主执行，本 Python 程序不能独立完成这些动作。已实现通用采集、动态页面与附件处理；具体站点仍需本地逐站验收，不承诺全部网站覆盖。失败不会被写成成功政策，也不代表该站本周没有政策。

## 验证与公开提交检查

先初始化虚构示例，再运行：

```text
<包内 Python> -I -B -X utf8 scripts/run_tests.py
<包内 Python> -I -B -X utf8 scripts/check_public_tree.py
```

测试使用虚构 HTML/附件、模拟采集和邮件回执，不发送邮件。提交检查扫描全部 Git 跟踪文件，禁止追踪本地数据、配置、文档附件、运行产物与常见凭证；不要强制添加被忽略的文件。公开包只承载实现，实际业务数据始终留在本地。
