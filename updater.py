"""
盘感训练器 - 自动升级模块

负责检查版本、下载更新、执行升级替换。
升级时保留 config.yaml / training_history.db 等用户数据。
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import requests


# 当前版本号（与 git tag 保持一致）
__version__ = "1.1.8"


@dataclass
class UpdateInfo:
    """服务端返回的版本信息。"""
    version: str = ""
    changelog: str = ""
    download_url: str = ""
    sha256: str = ""
    size: int = 0


def _get_platform_tag() -> str:
    """返回当前平台的标签，如 'win-x64'。"""
    system = platform.system().lower()
    if system == "windows":
        arch = platform.machine().lower()
        if arch in ("amd64", "x86_64"):
            return "win-x64"
        elif arch in ("arm64", "aarch64"):
            return "win-arm64"
        return "win-x64"
    elif system == "darwin":
        arch = platform.machine().lower()
        return "mac-arm64" if arch == "arm64" else "mac-x64"
    elif system == "linux":
        arch = platform.machine().lower()
        return "linux-x64" if arch == "x86_64" else "linux-arm64"
    return "win-x64"


def check_update(config: dict) -> UpdateInfo | None:
    """
    向服务器查询是否有新版本。

    Args:
        config: 应用配置字典（含 update.server_url）

    Returns:
        UpdateInfo 如果有新版本，None 如果已是最新或检查失败。
    """
    update_cfg = config.get("update", {})
    server_url = update_cfg.get("server_url", "https://stock.maolige.com")
    skip_ver = update_cfg.get("skip_version", "")

    plat = _get_platform_tag()
    params = {
        "platform": plat.split("-")[0],
        "arch": plat.split("-")[1],
        "version": __version__,
    }

    try:
        resp = requests.get(
            f"{server_url}/api/update/check",
            params=params,
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    if not data or data.get("version") == __version__:
        return None

    # 用户跳过的版本
    if skip_ver and data.get("version") == skip_ver:
        return None

    info = UpdateInfo(
        version=data.get("version", ""),
        changelog=data.get("changelog", ""),
        download_url=data.get("download_url", ""),
        sha256=data.get("sha256", ""),
        size=data.get("size", 0),
    )

    # 补全相对 URL
    if info.download_url and not info.download_url.startswith("http"):
        info.download_url = server_url + info.download_url

    return info


def download_update(
    info: UpdateInfo,
    progress_cb=None,
) -> str:
    """
    下载更新 zip 到临时目录。

    Args:
        info: UpdateInfo
        progress_cb: 可选回调 (downloaded_bytes, total_bytes)

    Returns:
        下载的 zip 文件路径

    Raises:
        Exception: 下载失败或校验不通过
    """
    tmp_dir = tempfile.mkdtemp(prefix="kline_update_")
    zip_path = os.path.join(tmp_dir, f"update_{info.version}.zip")

    resp = requests.get(info.download_url, stream=True, timeout=60)
    resp.raise_for_status()

    total = int(resp.headers.get("content-length", info.size))
    downloaded = 0
    sha = hashlib.sha256()

    with open(zip_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
            sha.update(chunk)
            downloaded += len(chunk)
            if progress_cb:
                progress_cb(downloaded, total)

    # SHA256 校验
    if info.sha256 and sha.hexdigest() != info.sha256:
        os.remove(zip_path)
        raise ValueError(
            f"SHA256 校验失败\n"
            f"期望: {info.sha256}\n"
            f"实际: {sha.hexdigest()}"
        )

    return zip_path


def apply_update(zip_path: str) -> None:
    """
    执行升级替换。生成 bat 脚本后退出主程序。

    升级流程（bat 脚本执行）：
    1. 等待主 exe 退出
    2. 备份 config.yaml / training_history.db 等用户文件
    3. 解压新版本覆盖安装目录
    4. 恢复用户文件
    5. 重启主程序

    Args:
        zip_path: 下载的新版本 zip 文件路径
    """
    # 主程序所在目录
    app_dir = Path(sys.executable).parent
    exe_name = Path(sys.executable).name
    bat_path = app_dir / "_updater.bat"

    # 需要保留的用户文件列表
    preserve_files = [
        "config.yaml",
        "training_history.db",
        "training_history.db-shm",
        "training_history.db-wal",
    ]

    # 生成 bat 脚本
    bat_content = f"""@echo off
chcp 65001 >nul
echo ============================================
echo   StockTraining Auto Update
echo ============================================
echo.

REM ---- 1. 等待主程序退出 ----
echo [1/5] 等待程序退出...
timeout /t 2 /nobreak >nul

REM ---- 2. 备份用户文件 ----
echo [2/5] 备份配置和数据文件...
set "BACKUP_DIR={app_dir}\\_update_backup"
if exist "%BACKUP_DIR%" rmdir /s /q "%BACKUP_DIR%"
mkdir "%BACKUP_DIR%"
"""
    for f in preserve_files:
        bat_content += f'if exist "{app_dir}\\{f}" copy /y "{app_dir}\\{f}" "%BACKUP_DIR%\\{f}" >nul\n'

    # 备份旧版本到 backup 目录
    bat_content += f"""
REM ---- 3. 备份旧版本 ----
echo [3/5] 备份旧版本...
set "OLD_DIR={app_dir}\\backup"
if exist "%OLD_DIR%" rmdir /s /q "%OLD_DIR%"
mkdir "%OLD_DIR%"
xcopy "{app_dir}\\_internal" "%OLD_DIR%\\_internal\\" /e /i /q >nul 2>&1
copy /y "{app_dir}\\{exe_name}" "%OLD_DIR%\\" >nul 2>&1

REM ---- 4. 解压新版本 ----
echo [4/5] 解压新版本...
set "TMP_DIR={app_dir}\\_update_tmp"
if exist "%TMP_DIR%" rmdir /s /q "%TMP_DIR%"
mkdir "%TMP_DIR%"
powershell -Command "Expand-Archive -Path '{zip_path}' -DestinationPath '%TMP_DIR%' -Force"

REM 查找解压后的目录（可能是套了一层目录）
set "SRC_DIR=%TMP_DIR%"
for /d %%i in ("%TMP_DIR%\\*") do (
    if exist "%%i\\{exe_name}" set "SRC_DIR=%%i"
)

REM 删除旧文件
rmdir /s /q "{app_dir}\\_internal" 2>nul
del /q "{app_dir}\\{exe_name}" 2>nul

REM 复制新文件
if exist "%SRC_DIR%\\{exe_name}" (
    copy /y "%SRC_DIR%\\{exe_name}" "{app_dir}\\" >nul
    xcopy "%SRC_DIR%\\_internal" "{app_dir}\\_internal\\" /e /i /q >nul
) else (
    echo [错误] 未找到新版本文件，正在回滚...
    copy /y "%OLD_DIR%\\{exe_name}" "{app_dir}\\" >nul
    xcopy "%OLD_DIR%\\_internal" "{app_dir}\\_internal\\" /e /i /q >nul
)

REM ---- 5. 恢复用户文件 ----
echo [5/5] 恢复配置和数据文件...
"""
    for f in preserve_files:
        bat_content += f'if exist "%BACKUP_DIR%\\{f}" copy /y "%BACKUP_DIR%\\{f}" "{app_dir}\\{f}" >nul\n'

    bat_content += f"""
REM 清理临时文件
rmdir /s /q "%TMP_DIR%" 2>nul
rmdir /s /q "%BACKUP_DIR%" 2>nul
del /q "{zip_path}" 2>nul

echo.
echo 升级完成！正在启动...
timeout /t 1 /nobreak >nul

REM ---- 重启主程序 ----
start "" "{app_dir}\\{exe_name}"

REM 自删除
(goto) 2>nul & del "%~f0"
"""
    bat_path.write_text(bat_content, encoding="utf-8")

    # 启动 bat 脚本并退出主程序
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        cwd=str(app_dir),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        if sys.platform == "win32"
        else 0,
    )

    # 退出主程序
    sys.exit(0)
