"""
盘感训练器 - 自动升级模块

负责检查版本、下载更新、执行升级替换。
升级时保留 config.yaml / training_history.db 等用户数据。

关键设计：
- 升级脚本使用 PowerShell（非 bat），原生支持 Unicode 路径
- 全流程写日志到 app_dir/_update.log，方便排查问题
- SHA256 校验兼容 "sha256:" 前缀格式
"""

import hashlib
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests


# 当前版本号（与 git tag 保持一致）
__version__ = "1.2.1"


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


def _log(msg: str) -> None:
    """追加日志到 app 目录下的 _update.log。"""
    try:
        app_dir = Path(sys.executable).parent
        log_path = app_dir / "_update.log"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass  # 日志写入失败不应阻断主流程


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

    _log(f"检查更新: {server_url}/api/update/check params={params}")

    try:
        resp = requests.get(
            f"{server_url}/api/update/check",
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        _log(f"检查更新失败: {e}")
        return None

    if not data or data.get("version") == __version__:
        _log("已是最新版本")
        return None

    # 用户跳过的版本
    if skip_ver and data.get("version") == skip_ver:
        _log(f"用户已跳过版本 {skip_ver}")
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

    _log(f"发现新版本: v{info.version}, size={info.size}, url={info.download_url}")
    return info


def download_update(
    info: UpdateInfo,
    progress_cb=None,
) -> str:
    """
    下载更新 zip 到 app 同级目录（用户可见）。

    Args:
        info: UpdateInfo
        progress_cb: 可选回调 (downloaded_bytes, total_bytes)

    Returns:
        下载的 zip 文件路径

    Raises:
        Exception: 下载失败或校验不通过
    """
    # 保存到 app 目录下，用户可见、方便排查
    app_dir = Path(sys.executable).parent
    download_dir = app_dir / "_update_download"
    download_dir.mkdir(exist_ok=True)
    zip_path = download_dir / f"update_v{info.version}.zip"

    _log(f"开始下载: {info.download_url} -> {zip_path}")

    # 如果已有同版本 zip 且大小匹配，跳过下载
    if zip_path.exists() and zip_path.stat().st_size == info.size:
        _log(f"已存在同版本 zip ({info.size} bytes)，跳过下载")
    else:
        resp = requests.get(info.download_url, stream=True, timeout=120)
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

        _log(f"下载完成: {downloaded} bytes")

        # SHA256 校验（兼容 "sha256:" 前缀格式）
        expected_sha = info.sha256
        if expected_sha.startswith("sha256:"):
            expected_sha = expected_sha[7:]
        actual_sha = sha.hexdigest()

        if expected_sha and actual_sha != expected_sha:
            zip_path.unlink(missing_ok=True)
            error_msg = (
                f"SHA256 校验失败\n"
                f"期望: {expected_sha}\n"
                f"实际: {actual_sha}"
            )
            _log(error_msg)
            raise ValueError(error_msg)

        _log(f"SHA256 校验通过: {actual_sha}")

    return str(zip_path)


def apply_update(zip_path: str) -> None:
    """
    执行升级替换。生成 PowerShell 脚本后退出主程序。

    为什么用 PowerShell 而不是 bat：
    - PowerShell 原生支持 UTF-8/Unicode，中文路径不会乱码
    - bat 文件以 UTF-8 保存但 cmd.exe 默认用 GBK 读取，中文路径会乱码
    - 文件操作更可靠（Copy-Item、Expand-Archive 等）

    升级流程（PowerShell 脚本执行）：
    1. 等待主 exe 退出
    2. 备份 config.yaml / training_history.db 等用户文件
    3. 备份旧版本到 backup 目录
    4. 解压新版本覆盖安装目录
    5. 恢复用户文件
    6. 重启主程序

    Args:
        zip_path: 下载的新版本 zip 文件路径
    """
    app_dir = Path(sys.executable).parent
    exe_name = Path(sys.executable).name
    ps1_path = app_dir / "_updater.ps1"

    # 需要保留的用户文件列表
    preserve_files = [
        "config.yaml",
        "training_history.db",
        "training_history.db-shm",
        "training_history.db-wal",
    ]

    _log(f"准备升级: zip={zip_path}, app_dir={app_dir}, exe={exe_name}")

    # 生成 PowerShell 升级脚本
    ps1_content = r"""
# StockTraining Auto Update Script
# Generated by updater.py — DO NOT EDIT MANUALLY

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$AppDir = '{app_dir}'
$ExeName = '{exe_name}'
$ZipPath = '{zip_path}'
$LogFile = Join-Path $AppDir '_update.log'
$PidName = $ExeName -replace '\.\w+$', ''

function Write-Log($msg) {{
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$ts] [PS] $msg"
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}}

Write-Log '===== 升级脚本启动 ====='
Write-Log "AppDir: $AppDir"
Write-Log "ZipPath: $ZipPath"

# ---- 1. 等待主程序退出 ----
Write-Log '[1/6] 等待主程序退出...'
$waited = 0
$maxWait = 30
while ($waited -lt $maxWait) {{
    $proc = Get-Process -Name $PidName -ErrorAction SilentlyContinue
    if (-not $proc) {{
        Write-Log '主程序已退出'
        break
    }}
    Start-Sleep -Seconds 1
    $waited++
}}

if ($waited -ge $maxWait) {{
    Write-Log '[警告] 等待超时，尝试强制关闭...'
    try {{
        Stop-Process -Name $PidName -Force -ErrorAction Stop
        Start-Sleep -Seconds 2
        Write-Log '已强制关闭'
    }} catch {{
        Write-Log "[错误] 无法关闭主程序: $_"
        Read-Host '按回车键关闭此窗口'
        exit 1
    }}
}}

# ---- 2. 备份用户文件 ----
Write-Log '[2/6] 备份用户文件...'
$BackupDir = Join-Path $AppDir '_update_backup'
if (Test-Path $BackupDir) {{ Remove-Item $BackupDir -Recurse -Force }}
New-Item -ItemType Directory -Path $BackupDir | Out-Null
""".rstrip()

    for f in preserve_files:
        ps1_content += f"""
$src = Join-Path $AppDir '{f}'
if (Test-Path $src) {{
    Copy-Item $src (Join-Path $BackupDir '{f}') -Force
    Write-Log "  已备份: {f}"
}}
"""

    ps1_content += r"""

# ---- 3. 备份旧版本 ----
Write-Log '[3/6] 备份旧版本...'
$OldDir = Join-Path $AppDir 'backup'
if (Test-Path $OldDir) {{ Remove-Item $OldDir -Recurse -Force }}
New-Item -ItemType Directory -Path $OldDir | Out-Null

$internalDir = Join-Path $AppDir '_internal'
if (Test-Path $internalDir) {{
    Copy-Item $internalDir (Join-Path $OldDir '_internal') -Recurse -Force
    Write-Log '  已备份 _internal/'
}}
$oldExe = Join-Path $AppDir $ExeName
if (Test-Path $oldExe) {{
    Copy-Item $oldExe (Join-Path $OldDir $ExeName) -Force
    Write-Log "  已备份 $ExeName"
}}

# ---- 4. 解压新版本 ----
Write-Log '[4/6] 解压新版本...'
$TmpDir = Join-Path $AppDir '_update_tmp'
if (Test-Path $TmpDir) {{ Remove-Item $TmpDir -Recurse -Force }}

try {{
    Expand-Archive -Path $ZipPath -DestinationPath $TmpDir -Force
    Write-Log '  解压完成'
}} catch {{
    Write-Log "[错误] 解压失败: $_"
    Write-Log '正在回滚...'
    Copy-Item (Join-Path $OldDir $ExeName) $AppDir -Force
    if (Test-Path (Join-Path $OldDir '_internal')) {{
        Copy-Item (Join-Path $OldDir '_internal') $internalDir -Recurse -Force
    }}
    # 恢复用户文件
"""

    for f in preserve_files:
        ps1_content += f"""
    $bf = Join-Path $BackupDir '{f}'
    if (Test-Path $bf) {{ Copy-Item $bf (Join-Path $AppDir '{f}') -Force }}
"""

    ps1_content += r"""
    Read-Host '升级失败，已回滚。按回车键关闭此窗口'
    exit 1
}}

# 查找解压后的源目录（zip 可能套了一层目录）
$SrcDir = $TmpDir
$subDirs = Get-ChildItem $TmpDir -Directory
foreach ($d in $subDirs) {{
    if (Test-Path (Join-Path $d.FullName $ExeName)) {{
        $SrcDir = $d.FullName
        Write-Log "  找到源目录: $SrcDir"
        break
    }}
}}

# ---- 5. 替换文件 ----
Write-Log '[5/6] 替换文件...'

# 删除旧 _internal
if (Test-Path $internalDir) {{
    Remove-Item $internalDir -Recurse -Force
    Write-Log '  已删除旧 _internal/'
}}

# 删除旧 exe
if (Test-Path $oldExe) {{
    Remove-Item $oldExe -Force
    Write-Log '  已删除旧 exe'
}}

# 复制新文件
$newExe = Join-Path $SrcDir $ExeName
if (Test-Path $newExe) {{
    Copy-Item $newExe $AppDir -Force
    Write-Log "  已复制 $ExeName"

    $newInternal = Join-Path $SrcDir '_internal'
    if (Test-Path $newInternal) {{
        Copy-Item $newInternal $internalDir -Recurse -Force
        Write-Log '  已复制 _internal/'
    }}
}} else {{
    Write-Log '[错误] 未找到新版本 exe，正在回滚...'
    Copy-Item (Join-Path $OldDir $ExeName) $AppDir -Force
    if (Test-Path (Join-Path $OldDir '_internal')) {{
        Copy-Item (Join-Path $OldDir '_internal') $internalDir -Recurse -Force
    }}
"""

    for f in preserve_files:
        ps1_content += f"""
    $bf = Join-Path $BackupDir '{f}'
    if (Test-Path $bf) {{ Copy-Item $bf (Join-Path $AppDir '{f}') -Force }}
"""

    ps1_content += r"""
    Read-Host '升级失败，已回滚。按回车键关闭此窗口'
    exit 1
}}

# 恢复用户文件
Write-Log '  恢复用户文件...'
"""

    for f in preserve_files:
        ps1_content += f"""
$bf = Join-Path $BackupDir '{f}'
if (Test-Path $bf) {{
    Copy-Item $bf (Join-Path $AppDir '{f}') -Force
    Write-Log "  已恢复: {f}"
}}
"""

    ps1_content += r"""

# ---- 6. 清理并重启 ----
Write-Log '[6/6] 清理并重启...'

# 清理临时目录
if (Test-Path $TmpDir) {{ Remove-Item $TmpDir -Recurse -Force }}
if (Test-Path $BackupDir) {{ Remove-Item $BackupDir -Recurse -Force }}

# 保留 zip 不删除（方便排查）
Write-Log '升级完成！'

Start-Sleep -Seconds 1

# 重启主程序
$newExePath = Join-Path $AppDir $ExeName
Write-Log "启动: $newExePath"
Start-Process $newExePath

# 自删除脚本
Write-Log '清理升级脚本...'
$self = $MyInvocation.MyCommand.Path
Remove-Item $self -Force

Write-Log '===== 升级完成 ====='
"""

    # 填入实际路径
    ps1_content = ps1_content.format(
        app_dir=str(app_dir),
        exe_name=exe_name,
        zip_path=str(zip_path),
    )

    ps1_path.write_text(ps1_content, encoding="utf-8-sig")  # BOM 确保 PowerShell 正确识别 UTF-8
    _log(f"升级脚本已生成: {ps1_path}")

    # 用 powershell.exe 启动升级脚本（-ExecutionPolicy Bypass 绕过执行策略）
    subprocess.Popen(
        [
            "powershell.exe",
            "-ExecutionPolicy", "Bypass",
            "-NoProfile",
            "-File", str(ps1_path),
        ],
        cwd=str(app_dir),
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        if sys.platform == "win32"
        else 0,
    )
    _log("升级脚本已启动，主程序即将退出")

    # 退出主程序
    sys.exit(0)
