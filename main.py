import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QGridLayout,
                             QPushButton, QLabel, QVBoxLayout, QHBoxLayout)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

# ========================================================
# 1. 导入核心工具
# ========================================================
from apps.video_sorter_app import VideoSorterApp  # 视频分类
from apps.renamer_app import RenamerApp  # 分组重命名
from apps.image_sorter_app import ImageSorterApp  # 图片分拣
from apps.downloader_app import DownloaderApp  # ⬇️ 新增：全能素材归档下载器
from apps.link_checker_app import LinkCheckerApp

# 导入更新模块
from apps.updater import check_update, CURRENT_VERSION


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"运营素材归档工作台 {CURRENT_VERSION}")

        # 窗口大小
        self.resize(700, 620)

        # 主容器
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(25)  # 间距稍微大一点

        # 标题
        title = QLabel("🚀 今天要开心呀！")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #333; margin-bottom: 20px; margin-top: 10px;")

        # --- 整体布局 ---
        main_layout = QVBoxLayout()
        main_layout.addWidget(title)
        main_layout.addLayout(self.grid_layout)
        main_layout.addStretch()

        # === 底部状态栏 ===
        bottom_layout = QHBoxLayout()
        self.lbl_version = QLabel(f"版本: {CURRENT_VERSION} | 专为高效工作打造 ❤️")
        self.lbl_version.setStyleSheet("color: gray; margin-left: 10px;")

        # self.btn_update = QPushButton("🔄 检查更新")
        # self.btn_update.setFixedSize(100, 30)
        # self.btn_update.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 5px;")
        # self.btn_update.clicked.connect(lambda: check_update(self))

        bottom_layout.addWidget(self.lbl_version)
        bottom_layout.addStretch()
        # bottom_layout.addWidget(self.btn_update)

        main_layout.addLayout(bottom_layout)

        central_widget.setLayout(main_layout)
        self.init_apps()

    def init_apps(self):
        # ========================================================
        # 2. 排布图标 (2行 x 2列)
        # ========================================================

        # Row 0: 整理旧素材
        self.add_app_icon("🎬\n视频分类器", self.open_sorter_app, 0, 0)
        self.add_app_icon("📂\n图片分拣器", self.open_image_sorter_app, 0, 1)

        # Row 1: 命名与下载
        self.add_app_icon("🔢\n分组重命名", self.open_renamer_app, 1, 0)

        # 👇 压轴神器：高亮显示
        self.add_app_icon("⬇️\n全能下载器", self.open_downloader_app, 1, 1, is_special=True)
        # Row 2: 链接检测
        self.add_app_icon("🔗\n链接检测", self.open_link_checker_app, 2, 0)

    def add_app_icon(self, text, callback, row, col, is_special=False):
        btn = QPushButton(text)
        btn.setFixedSize(140, 140)
        btn.setFont(QFont("Microsoft YaHei", 12))

        if is_special:
            # 给下载器一个特别的颜色（绿色），突显它是核心功能
            style = """
                QPushButton {
                    background-color: #e8f5e9;
                    border: 2px solid #4caf50;
                    border-radius: 18px;
                    color: #2e7d32;
                    font-weight: bold;
                }
                QPushButton:hover { background-color: #c8e6c9; }
                QPushButton:pressed { background-color: #a5d6a7; }
            """
        else:
            style = """
                QPushButton {
                    background-color: #ffffff;
                    border: 2px solid #ddd;
                    border-radius: 18px;
                    color: #333;
                }
                QPushButton:hover { background-color: #f5f5f5; border-color: #bbb; }
                QPushButton:pressed { background-color: #e0e0e0; }
            """

        btn.setStyleSheet(style)
        if callback:
            btn.clicked.connect(callback)
        else:
            btn.setEnabled(False)
        self.grid_layout.addWidget(btn, row, col)

    # ========================================================
    # 3. 启动函数
    # ========================================================
    def open_sorter_app(self):
        self.sorter_window = VideoSorterApp()
        self.sorter_window.show()

    def open_renamer_app(self):
        self.renamer_window = RenamerApp()
        self.renamer_window.show()

    def open_image_sorter_app(self):
        self.image_sorter_window = ImageSorterApp()
        self.image_sorter_window.show()

    def open_downloader_app(self):
        # 启动刚才写好的新下载器
        self.downloader_window = DownloaderApp()
        self.downloader_window.show()

    def open_link_checker_app(self):
        self.link_checker_window = LinkCheckerApp()
        self.link_checker_window.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())