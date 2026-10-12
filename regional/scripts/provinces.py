# -*- coding: utf-8 -*-
"""省份匹配表：省名 / 简称 / 代码前缀 / 大区 四向映射，供单省定向查询使用。"""
import json, os

PROVINCES = [
    # code_prefix, 全称, 简称, region
    ("BJ", "北京市", "京", "North China"),
    ("TJ", "天津市", "津", "North China"),
    ("HEB", "河北省", "冀", "North China"),
    ("SX", "山西省", "晋", "North China"),
    ("NM", "内蒙古自治区", "蒙", "North China"),
    ("LN", "辽宁省", "辽", "Northeast"),
    ("JL", "吉林省", "吉", "Northeast"),
    ("HLJ", "黑龙江省", "黑", "Northeast"),
    ("SH", "上海市", "沪", "East China"),
    ("JS", "江苏省", "苏", "East China"),
    ("ZJ", "浙江省", "浙", "East China"),
    ("AH", "安徽省", "皖", "East China"),
    ("FJ", "福建省", "闽", "East China"),
    ("JX", "江西省", "赣", "East China"),
    ("SD", "山东省", "鲁", "East China"),
    ("HEN", "河南省", "豫", "Central China"),
    ("HUB", "湖北省", "鄂", "Central China"),
    ("HUN", "湖南省", "湘", "Central China"),
    ("GD", "广东省", "粤", "South China"),
    ("GX", "广西壮族自治区", "桂", "South China"),
    ("HI", "海南省", "琼", "South China"),
    ("CQ", "重庆市", "渝", "Southwest"),
    ("SC", "四川省", "川", "Southwest"),
    ("GZ", "贵州省", "黔", "Southwest"),
    ("YN", "云南省", "滇", "Southwest"),
    ("XZ", "西藏自治区", "藏", "Southwest"),
    ("SN", "陕西省", "陕", "Northwest"),
    ("GS", "甘肃省", "甘", "Northwest"),
    ("QH", "青海省", "青", "Northwest"),
    ("NX", "宁夏回族自治区", "宁", "Northwest"),
    ("XJ", "新疆维吾尔自治区", "新", "Northwest"),
]

# 别名（常见简称/别称）
ALIASES = {
    "内蒙": "NM", "内蒙古": "NM",
    "广西": "GX", "广西壮族自治区": "GX",
    "西藏": "XZ", "宁夏": "NX", "新疆": "XJ",
    "黑龙江": "HLJ", "黑": "HLJ",
    "广东": "GD", "粤": "GD",
    "重庆": "CQ", "渝": "CQ",
    "云南": "YN", "滇": "YN",
    "贵州": "GZ", "黔": "GZ",
    "陕西": "SN", "陕": "SN",
    "甘肃": "GS", "甘": "GS",
    "青海": "QH", "青": "QH",
    "四川": "SC", "川": "SC",
    "河南": "HEN", "豫": "HEN",
    "湖北": "HUB", "鄂": "HUB",
    "湖南": "HUN", "湘": "HUN",
    "山东": "SD", "鲁": "SD",
    "江苏": "JS", "苏": "JS",
    "浙江": "ZJ", "浙": "ZJ",
    "安徽": "AH", "皖": "AH",
    "福建": "FJ", "闽": "FJ",
    "江西": "JX", "赣": "JX",
    "辽宁": "LN", "辽": "LN",
    "吉林": "JL", "吉": "JL",
    "河北": "HEB", "冀": "HEB",
    "山西": "SX", "晋": "SX",
    "北京": "BJ", "京": "BJ",
    "天津": "TJ", "津": "TJ",
    "上海": "SH", "沪": "SH",
    "海南": "HI", "琼": "HI",
}

REGION_ALIASES = {
    "华北": "North China", "华东": "East China", "华中": "Central China",
    "华南": "South China", "西南": "Southwest", "西北": "Northwest",
    "东北": "Northeast",
}


def resolve_province(text):
    """把用户输入（省名/简称/代码前缀/大区）解析为匹配集合。

    返回 dict: {"codes": set(前缀), "regions": set(大区), "label": 展示名}
    """
    t = (text or "").strip()
    if not t:
        return None
    codes, regions = set(), set()
    # 代码前缀（大小写不敏感）
    up = t.upper()
    for p, _full, _short, _reg in PROVINCES:
        if up == p:
            codes.add(p)
    # 大区
    for k, v in REGION_ALIASES.items():
        if k in t:
            regions.add(v)
    # 别名 / 全称 / 简称
    for k, p in ALIASES.items():
        if k in t:
            codes.add(p)
    for p, full, short, _reg in PROVINCES:
        if full in t or (short and short == t):
            codes.add(p)
    label = t
    return {"codes": codes, "regions": regions, "label": label}


def match_sources(sources, text):
    """按省份匹配来源列表。"""
    r = resolve_province(text)
    if not r:
        return [], r
    out = []
    for s in sources:
        pref = s.get("code", "").split()[0]
        if pref in r["codes"] or (r["regions"] and s.get("region") in r["regions"]):
            out.append(s)
    return out, r


if __name__ == "__main__":
    for q in ["广东", "粤", "GD", "华东", "内蒙古", "黑龙江", "新疆"]:
        r = resolve_province(q)
        print(f"{q:8s} -> codes={sorted(r['codes'])} regions={sorted(r['regions'])}")
