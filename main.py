import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QGridLayout,
                             QPushButton, QLabel, QVBoxLayout, QHBoxLayout)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont

# 导入子应用
from apps.watermark_app import WatermarkRemover
from apps.downloader_app import DownloaderApp
from apps.video_sorter_app import VideoSorterApp
from apps.renamer_app import RenamerApp
# 导入违禁词检测功能
from apps.ad_checker_app import AdCheckerApp

# 导入更新模块
from apps.updater import check_update, CURRENT_VERSION

# 👇 新增这一行
from apps.qrcode_app import QRCodeApp

from apps.title_spinner_app import TitleSpinnerApp

from apps.image_sorter_app import ImageSorterApp


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"我的百宝箱 {CURRENT_VERSION}")
        self.resize(650, 500)  # 稍微调大一点，适应新增的功能

        # 主容器
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(20)

        title = QLabel("选择一个功能启动")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # --- 整体布局 ---
        main_layout = QVBoxLayout()
        main_layout.addWidget(title)
        main_layout.addLayout(self.grid_layout)
        main_layout.addStretch()

        # === 底部状态栏 (版本号 + 更新按钮) ===
        bottom_layout = QHBoxLayout()

        self.lbl_version = QLabel(f"当前版本: {CURRENT_VERSION}")
        self.lbl_version.setStyleSheet("color: gray; margin-left: 10px;")

        self.btn_update = QPushButton("🔄 检查更新")
        self.btn_update.setFixedSize(100, 30)
        self.btn_update.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 5px;")
        # 只有点击时才触发 check_update
        self.btn_update.clicked.connect(lambda: check_update(self))

        bottom_layout.addWidget(self.lbl_version)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_update)

        main_layout.addLayout(bottom_layout)
        # ==========================================

        central_widget.setLayout(main_layout)

        self.init_apps()

        # 【已删除】启动后自动检查更新的代码
        # QTimer.singleShot(2000, lambda: check_update(self)) <--- 这行已经去掉了

    def init_apps(self):
        # 第0行
        self.add_app_icon("🖼️\n图片去水印", self.open_watermark_app, 0, 0)
        self.add_app_icon("⬇️\n全能下载\n", self.open_downloader_app, 0, 1)
        self.add_app_icon("🎬\n视频分类整理", self.open_sorter_app, 0, 2)

        # 第1行
        self.add_app_icon("🔢\n分组重命名", self.open_renamer_app, 1, 0)
        # 新增的广告检测入口
        self.add_app_icon("🛡️\n违禁词排雷", self.open_ad_checker_app, 1, 1)
        # 👇 新增这一行 (放在第 1 行，第 2 列)
        self.add_app_icon("📱\n二维码工坊", self.open_qrcode_app, 1, 2)
        self.add_app_icon("🧬\n标题裂变", self.open_title_spinner_app, 2, 0)
        self.add_app_icon("📂\n图片分辨率\n分拣", self.open_image_sorter_app, 2, 1)

    def add_app_icon(self, text, callback, row, col):
        btn = QPushButton(text)
        btn.setFixedSize(120, 120)
        btn.setFont(QFont("Microsoft YaHei", 10))
        btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                border: 2px solid #ddd;
                border-radius: 15px;
                color: #333;
            }
            QPushButton:hover {
                background-color: #e6f7ff;
                border-color: #1890ff;
            }
            QPushButton:pressed {
                background-color: #bae7ff;
            }
        """)
        if callback:
            btn.clicked.connect(callback)
        else:
            btn.setEnabled(False)
        self.grid_layout.addWidget(btn, row, col)

    def open_watermark_app(self):
        self.watermark_window = WatermarkRemover()
        self.watermark_window.show()

    def open_downloader_app(self):
        self.downloader_window = DownloaderApp()
        self.downloader_window.show()

    def open_sorter_app(self):
        self.sorter_window = VideoSorterApp()
        self.sorter_window.show()

    def open_renamer_app(self):
        self.renamer_window = RenamerApp()
        self.renamer_window.show()

    def open_ad_checker_app(self):
        self.ad_checker_window = AdCheckerApp()
        self.ad_checker_window.show()

    # 👇 新增这个函数
    def open_qrcode_app(self):
        self.qrcode_window = QRCodeApp()
        self.qrcode_window.show()

    # 👇 新增这个函数
    def open_title_spinner_app(self):
        self.title_window = TitleSpinnerApp()
        self.title_window.show()

    # 👇 新增这个函数
    def open_image_sorter_app(self):
        self.image_sorter_window = ImageSorterApp()
        self.image_sorter_window.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())