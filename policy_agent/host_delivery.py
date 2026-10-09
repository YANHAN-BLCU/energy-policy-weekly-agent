"""Prepare host email requests and validate receipts without storing credentials."""
from pathlib import Path
import hashlib
from .paths import local_path


def digest(path):
    return hashlib.sha256(local_path(path, "附件路径", must_exist=True).read_bytes()).hexdigest()


def make_request(workbook, recipient, run_id, count, failed_sources=0, unverified_dates=0):
    path = local_path(workbook, "附件路径", must_exist=True)
    return {
        "run_id": run_id,
        "recipient": recipient,
        "subject": f"每周政策情报 {run_id}",
        "body": (f"本次周报收录已取得正文且发布日期在本周窗口内的政策 {count} 条。"
                 f"另有正文已取得但日期未核验的记录 {unverified_dates} 条，未计入本周政策。"
                 f"采集异常或停用来源 {failed_sources} 个。详情和来源采集状态见附件；采集失败不能据此判断该站本周无政策。"),
        "attachment": str(path),
        "attachment_sha256": digest(path),
        "status": "pending",
    }


def validate_receipt(request, receipt):
    """A connector acknowledgment is required before a run becomes delivered."""
    if receipt.get("run_id") != request["run_id"]:
        raise ValueError("Receipt run_id does not match")
    if receipt.get("recipient") != request["recipient"]:
        raise ValueError("Receipt recipient does not match")
    status = receipt.get("status")
    if status not in {"sent", "pending", "failed"}:
        raise ValueError("Receipt status must be sent, pending or failed")
    if receipt.get("attachment_sha256") != request["attachment_sha256"]:
        raise ValueError("Receipt attachment checksum does not match")
    if digest(request["attachment"]) != request["attachment_sha256"]:
        raise ValueError("Workbook changed after preparing delivery")
    if status == "sent" and not (receipt.get("transport") and receipt.get("message_id")):
        raise ValueError("Sent requires transport and connector message_id/acknowledgment")
    return {
        "run_id": request["run_id"],
        "recipient": request["recipient"],
        "attachment_sha256": request["attachment_sha256"],
        "status": status,
        "transport": str(receipt.get("transport", "")),
        "message_id": str(receipt.get("message_id", "")),
        "error": str(receipt.get("error", "")),
    }
