import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QGridLayout, 
                             QPushButton, QLabel, QVBoxLayout, QHBoxLayout) # 记得加 QHBoxLayout
from PyQt6.QtCore import Qt, QSize, QTimer # 记得加 QTimer
from PyQt6.QtGui import QFont

# 导入子应用
from apps.watermark_app import WatermarkRemover
from apps.downloader_app import DownloaderApp
from apps.video_sorter_app import VideoSorterApp
from apps.renamer_app import RenamerApp

# === 新增：导入更新模块 ===
from apps.updater import check_update, CURRENT_VERSION

class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"我的百宝箱 {CURRENT_VERSION}") # 标题带上版本号
        self.resize(600, 450) #稍微调高一点，放下底部的按钮
        
        # 主容器
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(20)
        
        title = QLabel("选择一个功能启动")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # --- 整体布局 ---
        main_layout = QVBoxLayout()
        main_layout.addWidget(title)
        main_layout.addLayout(self.grid_layout)
        main_layout.addStretch() 
        
        # === 新增：底部状态栏 (版本号 + 更新按钮) ===
        bottom_layout = QHBoxLayout()
        
        self.lbl_version = QLabel(f"当前版本: {CURRENT_VERSION}")
        self.lbl_version.setStyleSheet("color: gray; margin-left: 10px;")
        
        self.btn_update = QPushButton("🔄 检查更新")
        self.btn_update.setFixedSize(100, 30)
        self.btn_update.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc; border-radius: 5px;")
        # 点击按钮触发检查
        self.btn_update.clicked.connect(lambda: check_update(self))
        
        bottom_layout.addWidget(self.lbl_version)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_update)
        
        main_layout.addLayout(bottom_layout)
        # ==========================================

        central_widget.setLayout(main_layout)
        
        self.init_apps()
        
        # === 可选：启动后自动静默检查更新 ===
        # 延时 2 秒检查，不卡启动界面
        QTimer.singleShot(2000, lambda: check_update(self))

    def init_apps(self):
        self.add_app_icon("🖼️\n图片去水印", self.open_watermark_app, 0, 0)
        self.add_app_icon("⬇️\n全能下载\n", self.open_downloader_app, 0, 1)
        self.add_app_icon("🎬\n视频分类整理", self.open_sorter_app, 0, 2)
        self.add_app_icon("🔢\n分组重命名", self.open_renamer_app, 1, 0)

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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())