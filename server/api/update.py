"""
盘感训练器 - 升级服务 API Blueprint

部署到 stock.maolige.com 的 Flask 应用中。
注册方式: app.register_blueprint(update_bp, url_prefix='/api/update')

API 端点:
  GET /api/update/check    - 检查是否有新版本
  GET /api/update/changelog - 获取两个版本间的更新日志
"""

import json
import os
from pathlib import Path

from flask import Blueprint, request, jsonify, send_file

update_bp = Blueprint("update", __name__)

# 版本注册表路径（与 Flask static 目录同级）
_VERSIONS_FILE = Path(__file__).resolve().parent.parent / "static" / "releases" / "versions.json"


def _load_versions() -> dict:
    """加载版本注册表。"""
    if not _VERSIONS_FILE.is_file():
        return {"latest": "0.0.0", "versions": {}}
    with open(_VERSIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _compare_versions(v1: str, v2: str) -> int:
    """
    比较两个语义化版本号。

    Returns:
        >0 if v1 > v2, 0 if equal, <0 if v1 < v2
    """
    def _parts(v):
        return [int(x) for x in v.lstrip("v").split(".")]

    p1, p2 = _parts(v1), _parts(v2)
    for a, b in zip(p1, p2):
        if a != b:
            return a - b
    return len(p1) - len(p2)


@update_bp.route("/check", methods=["GET"])
def check():
    """
    检查是否有新版本。

    Query 参数:
      platform: win / mac / linux
      arch:     x64 / arm64
      version:  当前版本号（如 1.1.2）

    返回:
      200: 有新版本时返回版本信息
      204: 已是最新版本
    """
    platform_name = request.args.get("platform", "win")
    arch = request.args.get("arch", "x64")
    current_version = request.args.get("version", "0.0.0")

    versions = _load_versions()
    latest = versions.get("latest", "0.0.0")

    # 当前版本 >= 最新版本 → 无更新
    if _compare_versions(current_version, latest) >= 0:
        return "", 204

    # 查找最新版本的详细信息
    ver_info = versions.get("versions", {}).get(latest)
    if not ver_info:
        return "", 204

    # 查找对应平台的下载信息
    platform_key = f"{platform_name}-{arch}"
    platform_info = ver_info.get("platforms", {}).get(platform_key)

    if not platform_info:
        # 平台不匹配，返回版本信息但不提供下载
        return jsonify({
            "version": latest,
            "changelog": ver_info.get("changelog", ""),
            "download_url": "",
            "sha256": "",
            "size": 0,
        })

    return jsonify({
        "version": latest,
        "changelog": ver_info.get("changelog", ""),
        "download_url": platform_info.get("url", ""),
        "sha256": platform_info.get("sha256", ""),
        "size": platform_info.get("size", 0),
    })


@update_bp.route("/changelog", methods=["GET"])
def changelog():
    """
    获取两个版本间的更新日志。

    Query 参数:
      from: 起始版本（可选，默认返回全部）
      to:   结束版本（可选，默认为最新）

    返回:
      200: JSON 数组，每项为 {version, date, changelog}
    """
    from_ver = request.args.get("from", "0.0.0")
    to_ver = request.args.get("to")

    versions = _load_versions()
    all_versions = versions.get("versions", {})

    result = []
    for ver, info in sorted(
        all_versions.items(),
        key=lambda x: list(map(int, x[0].lstrip("v").split("."))),
        reverse=True,  # 新版本在前
    ):
        if _compare_versions(ver, from_ver) <= 0:
            break
        if to_ver and _compare_versions(ver, to_ver) > 0:
            continue
        result.append({
            "version": ver,
            "date": info.get("release_date", ""),
            "changelog": info.get("changelog", ""),
        })

    return jsonify(result)
