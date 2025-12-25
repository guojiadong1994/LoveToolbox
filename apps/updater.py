import sys
import os
import requests
import subprocess
import platform  # 用于判断系统
import zipfile  # 用于解压Mac包
from PyQt6.QtWidgets import QMessageBox, QProgressDialog
from PyQt6.QtCore import Qt

# ==========================================
# 👇 请修改你的仓库名 (格式: 用户名/仓库名)
GITHUB_REPO = "GuoJiaDong/LoveToolbox"
# 👇 每次发布新版本前，记得修改这里
CURRENT_VERSION = "v1.0"


# ==========================================

def get_system_asset_name():
    """根据当前系统返回需要下载的文件名关键词"""
    sys_name = platform.system()
    if sys_name == "Windows":
        return "LoveToolbox-Windows.exe"
    elif sys_name == "Darwin":  # macOS
        return "LoveToolbox-macOS.zip"
    else:
        return None


def check_update(parent_window):
    """检查更新主逻辑"""
    print(f"[{platform.system()}] 正在检查更新...")
    try:
        api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        response = requests.get(api_url, timeout=5)

        if response.status_code != 200:
            print("检查失败: 无法连接 GitHub API")
            return

        data = response.json()
        latest_version = data['tag_name']

        # 版本对比
        if latest_version != CURRENT_VERSION:
            # 发现新版本 -> 弹窗提示
            reply = QMessageBox.question(
                parent_window,
                "发现新版本 ✨",
                f"当前版本：{CURRENT_VERSION}\n最新版本：{latest_version}\n\n检测到有新功能，是否立即更新？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                target_asset_name = get_system_asset_name()
                if not target_asset_name:
                    QMessageBox.warning(parent_window, "错误", "不支持的操作系统。")
                    return

                # 在 Release 列表中寻找对应的文件
                download_url = ""
                for asset in data['assets']:
                    if target_asset_name in asset['name']:
                        download_url = asset['browser_download_url']
                        break

                if download_url:
                    perform_update(parent_window, download_url, latest_version, target_asset_name)
                else:
                    QMessageBox.warning(parent_window, "错误", f"未找到适用于 {platform.system()} 的安装包。")
        else:
            # 没有更新 -> 弹窗提示已是最新
            QMessageBox.information(parent_window, "检查更新", f"当前已是最新版本 ({CURRENT_VERSION})！\n无需更新。")

    except Exception as e:
        print(f"检查出错: {e}")
        # 静默失败，不打扰


def perform_update(parent_window, url, version, filename):
    """执行下载和替换 (双端适配)"""

    # 1. 确定下载路径
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
        # Mac 特殊处理：sys.executable 在 App/Contents/MacOS/ 里，需要回退到 App 所在目录
        if platform.system() == "Darwin":
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(base_dir)))
    else:
        base_dir = os.getcwd()

    save_path = os.path.join(base_dir, filename)

    # 2. 国内加速下载
    fast_url = f"https://mirror.ghproxy.com/{url}"

    progress = QProgressDialog(f"正在下载 {version}...", "取消", 0, 100, parent_window)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.show()

    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        with requests.get(fast_url, stream=True, headers=headers, timeout=60) as r:
            r.raise_for_status()
            total_length = int(r.headers.get('content-length', 0))
            dl = 0
            with open(save_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if progress.wasCanceled():
                        return
                    if chunk:
                        dl += len(chunk)
                        f.write(chunk)
                        if total_length > 0:
                            done = int(100 * dl / total_length)
                            progress.setValue(done)
            progress.setValue(100)

    except Exception as e:
        QMessageBox.warning(parent_window, "失败", f"下载失败：{str(e)}")
        return

    # 3. 根据系统执行替换逻辑
    if platform.system() == "Windows":
        update_on_windows(base_dir, save_path)
    elif platform.system() == "Darwin":
        update_on_mac(base_dir, save_path)


def update_on_windows(base_dir, new_exe_path):
    """Windows 更新逻辑 (.bat)"""
    current_exe = sys.executable

    bat_script = f"""
@echo off
timeout /t 2 /nobreak > NUL
del "{current_exe}"
move "{new_exe_path}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
"""
    bat_path = os.path.join(base_dir, "update.bat")
    with open(bat_path, "w", encoding="gbk") as f:
        f.write(bat_script)

    subprocess.Popen(bat_path, shell=True)
    sys.exit()


def update_on_mac(base_dir, new_zip_path):
    """Mac 更新逻辑 (.sh)"""
    app_name = "LoveToolbox.app"
    current_app_path = os.path.join(base_dir, app_name)
    temp_dir = os.path.join(base_dir, "update_temp")

    # 1. 解压
    try:
        with zipfile.ZipFile(new_zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
            new_app_source = os.path.join(temp_dir, app_name)
            if not os.path.exists(new_app_source):
                raise Exception("解压后未找到 .app 文件")
    except Exception as e:
        QMessageBox.warning(None, "错误", f"解压失败: {e}")
        return

    # 2. 生成 Shell 脚本进行替换
    sh_path = os.path.join(base_dir, "update.sh")
    sh_script = f"""#!/bin/bash
sleep 2
rm -rf "{current_app_path}"
mv "{os.path.join(temp_dir, app_name)}" "{current_app_path}"
rm -rf "{temp_dir}"
rm "{new_zip_path}"
# 尝试移除隔离属性，防止文件损坏提示
xattr -d com.apple.quarantine "{current_app_path}"
open "{current_app_path}"
rm "$0"
"""
    with open(sh_path, "w") as f:
        f.write(sh_script)

    os.chmod(sh_path, 0o755)
    subprocess.Popen(["/bin/bash", sh_path])
    sys.exit()