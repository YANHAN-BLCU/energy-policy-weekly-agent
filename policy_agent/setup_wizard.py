from pathlib import Path
import json, re
from .paths import local_path, PACKAGE_ROOT

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DAY_NAMES = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}


def ask(prompt, default="", required=False, validator=None):
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{prompt}{suffix}: ").strip()
        if not value:
            value = default
        if required and not value:
            print("此项必填。")
            continue
        if validator and value and not validator(value):
            print("格式不正确，请重新输入。")
            continue
        return value


def valid_time(value):
    return bool(re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", value))


def run(output_path=None, email="", weekday="", trigger_time=""):
    """Collect only user-facing installation values; operational defaults stay in the package."""
    package_root = PACKAGE_ROOT
    path = local_path(output_path or package_root / "config" / "installation.json", "安装配置路径")
    path.parent.mkdir(parents=True, exist_ok=True)
    print("首次安装初始化：每周政策消息任务")
    print("任务范围固定为：抓取最新政策、分类、总结、生成表单并发送到邮箱。")
    email = email or ask("接收任务结果的邮箱", required=True, validator=lambda x: bool(EMAIL_RE.fullmatch(x)))
    weekday = (weekday or ask(
        "每周星期（MON/TUE/WED/THU/FRI/SAT/SUN）",
        default="MON",
        required=True,
        validator=lambda x: x.upper() in DAY_NAMES,
    )).upper()
    trigger_time = trigger_time or ask(
        "任务触发时间（24小时制 HH:MM）",
        default="06:20",
        required=True,
        validator=valid_time,
    )
    if not EMAIL_RE.fullmatch(email) or weekday not in DAY_NAMES or not valid_time(trigger_time):
        raise ValueError("邮箱、星期或触发时间格式不正确")
    config = {
        "initialized": True,
        "delivery_email": email,
        "weekday": weekday,
        "trigger_time": trigger_time,
        "scope": "weekly latest policy messages and email delivery",
    }
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"初始化配置已保存：{path}")
    return config


if __name__ == "__main__":
    run()
