"""Local CPU OCR with per-image text, boxes, confidence and immutable evidence."""
from pathlib import Path
from threading import Lock
import hashlib
import json
import shutil
from .paths import PACKAGE_ROOT, local_path
from .runtime import configure

_engine, _lock = None, Lock()


def engine():
    global _engine
    with _lock:
        if _engine is None:
            configure()
            import rapidocr
            models = local_path(PACKAGE_ROOT / ".runtime" / "ocr-models", "OCR 模型目录")
            models.mkdir(parents=True, exist_ok=True)
            bundled = local_path(Path(rapidocr.__file__).parent / "models", "包内 OCR 模型", must_exist=True)
            names = {"Det": "PP-OCRv6_det_small.onnx", "Cls": "ch_ppocr_mobile_v2.0_cls_mobile.onnx", "Rec": "PP-OCRv6_rec_small.onnx"}
            params = {"Global.model_root_dir": str(models), "Global.log_level": "error", "Global.text_score": 0.0,
                      "Global.max_side_len": 2400, "Det.limit_type": "max", "Det.limit_side_len": 1800,
                      "EngineConfig.onnxruntime.intra_op_num_threads": 2, "EngineConfig.onnxruntime.inter_op_num_threads": 1}
            for kind, name in names.items():
                target = local_path(models / name, "OCR 模型")
                origin = bundled / name
                if not target.exists() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(origin.read_bytes()).digest():
                    shutil.copyfile(origin, target)
                params[kind + ".model_path"] = str(target)
            _engine = rapidocr.RapidOCR(params=params)
    return _engine


def recognize(image_path, output_path, min_characters=80):
    image_path = local_path(image_path, "OCR 原图", must_exist=True)
    output_path = local_path(output_path, "OCR 证据")
    runner = engine()
    from PIL import Image
    from math import ceil
    lines, tiles = [], []
    with Image.open(image_path) as original:
        original.load()
        width, height = original.size
        if width * height > 100_000_000:
            raise ValueError("OCR_IMAGE_SIZE_LIMIT_EXCEEDED")
        # Long scanned articles must retain their native text size rather than shrink
        # to the detector's image limit. Overlap keeps boundary lines intact.
        starts = [0] if height <= 2400 else list(range(0, height - 1800 + 1600, 1600))
        for index, top in enumerate(starts):
            bottom = min(top + 1800, height)
            tile_path = image_path
            if len(starts) > 1:
                tile_path = local_path(output_path.with_name(output_path.name + f".tile_{index + 1:03d}.png"), "OCR 分块原图")
                tile_path.parent.mkdir(parents=True, exist_ok=True)
                original.crop((0, top, width, bottom)).save(tile_path)
            with _lock:
                result = runner(str(tile_path))
            tiles.append({"path": str(tile_path), "top": top, "bottom": bottom})
            for text, score, box in zip(result.txts or (), result.scores or (), result.boxes if result.boxes is not None else ()):
                points = box.tolist()
                center = sum(point[1] for point in points) / len(points)
                if len(starts) > 1 and ((index > 0 and center < 100) or (index < len(starts) - 1 and center >= 1700)):
                    continue
                for point in points:
                    point[1] += top
                lines.append({"text": text, "confidence": float(score), "box": points})
            if bottom == height:
                break
    scores = [line["confidence"] for line in lines]
    text = "\n".join(line["text"] for line in lines)
    mean = sum(scores) / max(len(scores), 1)
    low = sum(score < 0.75 for score in scores) / max(len(scores), 1)
    valid = len(text.strip()) >= min_characters and mean >= 0.90 and low <= 0.10
    data = {"engine": "RapidOCR 3.9.2 / CPU / PP-OCRv6", "tiles": tiles, "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
            "image_path": str(image_path), "text": text, "lines": lines, "mean_confidence": mean,
            "low_confidence_fraction": low, "min_characters": min_characters, "valid": valid, "error": "" if valid else "OCR_EMPTY_OR_LOW_CONFIDENCE"}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
