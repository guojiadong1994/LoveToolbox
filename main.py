import sys
import time

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QGridLayout,
    QPushButton,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QSplashScreen,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QPixmap


# 当前版本号（仅用于显示，不再提供远程更新）
CURRENT_VERSION = "v1.2"


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"运营素材归档工作台 {CURRENT_VERSION}")

        self.resize(700, 620)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(25)

        title = QLabel("🚀 今天要开心呀！")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #333; margin-bottom: 20px; margin-top: 10px;")

        main_layout = QVBoxLayout()
        main_layout.addWidget(title)
        main_layout.addLayout(self.grid_layout)
        main_layout.addStretch()

        bottom_layout = QHBoxLayout()
        self.lbl_version = QLabel(f"版本: {CURRENT_VERSION} | 专为高效工作打造 ❤️")
        self.lbl_version.setStyleSheet("color: gray; margin-left: 10px;")

        bottom_layout.addWidget(self.lbl_version)
        bottom_layout.addStretch()

        main_layout.addLayout(bottom_layout)

        central_widget.setLayout(main_layout)
        self.init_apps()

    def init_apps(self):
        self.add_app_icon("🎬\n视频分类器", self.open_sorter_app, 0, 0)
        self.add_app_icon("📂\n图片分拣器", self.open_image_sorter_app, 0, 1)
        self.add_app_icon("🔢\n分组重命名", self.open_renamer_app, 1, 0)
        self.add_app_icon("⬇️\n全能下载器", self.open_downloader_app, 1, 1, is_special=True)
        self.add_app_icon("🔗\n链接检测", self.open_link_checker_app, 2, 0)

    def add_app_icon(self, text, callback, row, col, is_special=False):
        btn = QPushButton(text)
        btn.setFixedSize(140, 140)
        btn.setFont(QFont("Microsoft YaHei", 12))

        if is_special:
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
        btn.clicked.connect(callback)
        self.grid_layout.addWidget(btn, row, col)

    # ===============================
    # 懒加载：点击时才加载对应功能
    # ===============================
    def open_sorter_app(self):
        from apps.video_sorter_app import VideoSorterApp
        self.sorter_window = VideoSorterApp()
        self.sorter_window.show()

    def open_renamer_app(self):
        from apps.renamer_app import RenamerApp
        self.renamer_window = RenamerApp()
        self.renamer_window.show()

    def open_image_sorter_app(self):
        from apps.image_sorter_app import ImageSorterApp
        self.image_sorter_window = ImageSorterApp()
        self.image_sorter_window.show()

    def open_downloader_app(self):
        from apps.downloader_app import DownloaderApp
        self.downloader_window = DownloaderApp()
        self.downloader_window.show()

    def open_link_checker_app(self):
        from apps.link_checker_app import LinkCheckerApp
        self.link_checker_window = LinkCheckerApp()
        self.link_checker_window.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 启动画面，避免首次加载时空白等待
    splash_pix = QPixmap(400, 250)
    splash_pix.fill(Qt.GlobalColor.white)
    splash = QSplashScreen(splash_pix)
    splash.showMessage(
        "LoveToolbox\n\n正在启动...",
        Qt.AlignmentFlag.AlignCenter,
        Qt.GlobalColor.darkGray,
    )
    splash.show()
    app.processEvents()

    time.sleep(0.3)

    window = LauncherWindow()
    window.show()
    splash.finish(window)

    sys.exit(app.exec())
