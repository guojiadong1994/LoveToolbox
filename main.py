import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QGridLayout, 
                             QPushButton, QLabel, QVBoxLayout, QFrame)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont

# 导入你的子应用
from apps.watermark_app import WatermarkRemover
from apps.downloader_app import DownloaderApp
from apps.video_sorter_app import VideoSorterApp
from apps.renamer_app import RenamerApp

class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("我的百宝箱 (Python Desktop Tools)")
        self.resize(600, 400)
        
        # 主容器
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 布局：网格布局 (类似 iPhone 桌面)
        self.grid_layout = QGridLayout()
        # 设置间距
        self.grid_layout.setSpacing(20)
        
        # 顶部标题
        title = QLabel("选择一个功能启动")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 整体垂直布局
        main_layout = QVBoxLayout()
        main_layout.addWidget(title)
        main_layout.addLayout(self.grid_layout)
        main_layout.addStretch() # 底部填充
        
        central_widget.setLayout(main_layout)
        
        # --- 初始化应用图标 ---
        self.init_apps()

    def init_apps(self):
        # 参数：图标文字，点击后的回调函数，行，列
        self.add_app_icon("🖼️\n图片去水印", self.open_watermark_app, 0, 0)
        self.add_app_icon("⬇️\n全能下载\n", self.open_downloader_app, 0, 1)
        self.add_app_icon("🎬\n视频分类整理", self.open_sorter_app, 0, 2)
        # 1行0列：重命名工具 (新增)
        self.add_app_icon("🔢\n分组重命名", self.open_renamer_app, 1, 0)

    def add_app_icon(self, text, callback, row, col):
        """创建一个类似APP图标的按钮"""
        btn = QPushButton(text)
        btn.setFixedSize(120, 120) # 方形图标
        btn.setFont(QFont("Microsoft YaHei", 10))
        
        # 简单的样式美化
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
            btn.setEnabled(False) # 还没开发的功能置灰
            
        self.grid_layout.addWidget(btn, row, col)

    # --- 打开子应用逻辑 ---
    def open_watermark_app(self):
        # 实例化子应用窗口
        self.watermark_window = WatermarkRemover()
        self.watermark_window.show()
        # 如果你想打开子应用时隐藏主窗口，可以使用 self.hide() 
        # 并在子窗口关闭时 show() 回来，这需要一点额外的信号处理
        # 目前先采用多窗口模式

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
    
    # 全局样式调整（可选，让界面看起来更现代）
    app.setStyle("Fusion")
    
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())