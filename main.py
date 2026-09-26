import sys

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QGridLayout,
    QPushButton,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
)
from PyQt6.QtCore import Qt


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
        # 使用系统默认字体，只调整字号/粗细。
        # 避免 macOS 启动时额外查找 Windows 专属字体 Microsoft YaHei。
        title_font = title.font()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)
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
        # 首页采用 3 列布局：每排 3 个工具
        self.add_app_icon("🎬\n视频分类器", self.open_sorter_app, 0, 0)
        self.add_app_icon("📂\n图片分拣器", self.open_image_sorter_app, 0, 1)
        self.add_app_icon("🔢\n分组重命名", self.open_renamer_app, 0, 2)

        self.add_app_icon("⬇️\n全能下载器", self.open_downloader_app, 1, 0, is_special=True)
        self.add_app_icon("🔗\n链接检测", self.open_link_checker_app, 1, 1)
        self.add_app_icon("📊\n转换数据", self.open_data_converter_app, 1, 2)
        self.add_app_icon("🖼️\n图片转换", self.open_image_converter_app, 2, 0)

    def add_app_icon(self, text, callback, row, col, is_special=False):
        btn = QPushButton(text)
        btn.setFixedSize(140, 140)

        # 保留系统字体，只设置字号，减少跨平台字体回退/别名扫描。
        btn_font = btn.font()
        btn_font.setPointSize(12)
        btn.setFont(btn_font)

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

    def open_data_converter_app(self):
        from apps.data_converter_app import DataConverterApp
        self.data_converter_window = DataConverterApp()
        self.data_converter_window.show()

    def open_image_converter_app(self):
        from apps.image_converter_app import ImageConverterApp
        self.image_converter_window = ImageConverterApp()
        self.image_converter_window.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 不再强制 Fusion 样式，也不再创建 Splash / 人为 sleep。
    # 直接使用系统原生 Qt 样式并尽快显示首页。
    window = LauncherWindow()
    window.show()

    sys.exit(app.exec())
