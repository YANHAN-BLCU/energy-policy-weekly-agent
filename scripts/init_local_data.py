"""Import private JSON data into ignored, directory-local application assets."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from policy_agent.export import HEADERS
from policy_agent.mi_checks import render_dictionary, check_dictionary_assets
from policy_agent.models import Source
from policy_agent.paths import local_path
from policy_agent.taxonomy import dictionary


def initialize(sources, vocabulary, *, root=ROOT):
    root = local_path(root, "本地资产目录")
    targets = ["config/sources.json", "policy_agent/data/mi_dictionary.json", "docs/MI_DICTIONARY.md", "PACKAGE_MANIFEST.json"]
    if any((root / name).exists() for name in targets):
        raise ValueError("本地资产已存在；请核对并备份后处理，不自动覆盖")
    required = {"agencies", "issuer_units", "policy_tags", "issuing_agency_examples", "issuing_agency_images",
                "export_fields", "reference_field_aliases", "reference_file", "reference_sha256"}
    if required - vocabulary.keys():
        raise ValueError("字典缺少字段：" + ", ".join(sorted(required - vocabulary.keys())))
    if [f["name"] for f in vocabulary["export_fields"]] != HEADERS:
        raise ValueError("字典输出字段或顺序不符合程序固定格式")
    agencies = vocabulary["agencies"] + vocabulary["issuer_units"]
    codes = [a["code"] for a in agencies]
    if not codes or len(codes) != len(set(codes)) or any(not a.get(k) for a in agencies for k in ("code", "name", "chinese_name")):
        raise ValueError("机构映射为空、代码重复或缺少译名")
    pairs = [(p["category"], p["tag"]) for p in vocabulary["policy_tags"]]
    if not pairs or len(pairs) != len(set(pairs)) or any(not c or not t for c, t in pairs):
        raise ValueError("分类标签为空或重复")
    by_code = {a["code"]: a for a in agencies}
    for example in vocabulary["issuing_agency_examples"]:
        if ", ".join(by_code[c]["name"] for c in example["codes"]) != example["english_name"]:
            raise ValueError("联合发文示例与机构字典不一致")
    aliases = vocabulary.get("code_aliases", {})
    if any(key in codes or value not in codes for key, value in aliases.items()):
        raise ValueError("代码别名存在冲突或指向未知机构")
    rows = sources.get("sources")
    if not isinstance(rows, list) or not rows:
        raise ValueError("来源 JSON 必须包含非空 sources 列表")
    from urllib.parse import urlsplit
    for row in rows:
        source = Source.from_dict(row)
        if source.code not in codes and source.code not in aliases:
            raise ValueError("来源代码缺少对应机构字典：" + source.code)
        for value in (source.website, source.list_url, *source.entry_urls):
            url = urlsplit(value)
            if url.scheme not in {"https", "http"} or not url.hostname:
                raise ValueError("来源地址必须为 HTTP(S) URL")
        if vocabulary.get("demo") and source.enabled:
            raise ValueError("虚构示例的来源必须停用")
    assets = {"config/sources.json": json.dumps(sources, ensure_ascii=False, indent=2) + "\n",
              "policy_agent/data/mi_dictionary.json": json.dumps(vocabulary, ensure_ascii=False, indent=2) + "\n",
              "docs/MI_DICTIONARY.md": render_dictionary(vocabulary)}
    manifest = {"schema_version": 1, "files": [{"path": name, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
                                               for name, text in assets.items()]}
    assets["PACKAGE_MANIFEST.json"] = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    created = []
    try:
        for name, text in assets.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation preserves any files created by another process.
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                created.append(path)
                handle.write(text)
        dictionary.cache_clear()
        return check_dictionary_assets(root, verify_manifest=True)
    except Exception:
        for path in reversed(created):
            path.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description="只在包目录导入本地数据；公开仓库不含业务数据")
    parser.add_argument("--demo", action="store_true", help="使用停用来源和虚构字典进行安装测试")
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--dictionary", type=Path)
    args = parser.parse_args()
    try:
        if args.demo:
            if args.sources or args.dictionary:
                raise ValueError("--demo 不能与私有数据导入参数同时使用")
            sources = ROOT / "examples/sources.example.json"
            vocabulary = ROOT / "examples/mi_dictionary.example.json"
        else:
            if not args.sources or not args.dictionary:
                raise ValueError("请提供 --sources 和 --dictionary，或使用 --demo")
            sources, vocabulary = args.sources, args.dictionary
        report = initialize(json.loads(sources.read_text(encoding="utf-8-sig")),
                            json.loads(vocabulary.read_text(encoding="utf-8-sig")))
        print(json.dumps({"initialized": True, "demo": args.demo, **report}, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
