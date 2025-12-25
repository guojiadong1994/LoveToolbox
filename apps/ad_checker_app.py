import sys
import re
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QTextEdit, QTableWidget, QTableWidgetItem,
                             QHeaderView, QSplitter, QMessageBox)
from PyQt6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PyQt6.QtCore import Qt


class AdCheckerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("广告法违禁词排雷助手 (Vivo专版)")
        # 1. 调整窗口大小：增加高度，让输入框更舒服
        self.resize(1100, 850)

        # === 🚫 内置违禁词库 ===
        self.banned_dict = {
            "第一": "TOP1 / 前列",
            "唯一": "独特 / 少有",
            "国家级": "（建议删除）",
            "最高级": "（建议删除）",
            "最佳": "出色 / 优选",
            "顶级": "高端 / 旗舰",
            "极品": "优质",
            "首选": "优选",
            "完美": "优秀",
            "100%": "高达 / 约",
            "百分百": "（建议数据化）",
            "全球": "（需数据证明）",
            "全网": "（需数据证明）",
            "独家": "（需授权证明）",
            "万能": "多功能",
            "永久": "长期",
            "特效": "功效",
            "痊愈": "康复",
            "根治": "改善",
            "不反弹": "（严禁承诺）",
            "点击领": "（需明示条件）",
            "免费": "（需明示条件）",
            "送现金": "（严禁诱导）",
            "躺赚": "（涉嫌诈骗）",
            "保本": "（严禁承诺）",
        }

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        # 减小边缘留白，让内容铺得更满
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # 2. 顶部区域极简优化 (合并成一行)
        header_layout = QHBoxLayout()

        title = QLabel("🛡️ 广告合规检测")
        # 字体稍微调小一点，不再那么占地
        title.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        header_layout.addWidget(title)

        tips = QLabel("（操作指南：粘贴文案到左侧 -> 点击底部【一键排雷】 -> 右侧查看结果）")
        tips.setStyleSheet("color: #666; font-size: 12px; margin-left: 10px;")
        header_layout.addWidget(tips)

        header_layout.addStretch()  # 让标题靠左对齐，右边留白

        layout.addLayout(header_layout)

        # 3. 主体区域 (使用 Splitter 分割)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- 左侧：编辑区 ---
        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)  # 去掉内部留白

        lbl_input = QLabel("📝 粘贴文案:")
        lbl_input.setStyleSheet("font-weight: bold; color: #333;")
        left_layout.addWidget(lbl_input)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "请在此粘贴标题、正文或口号...\n\n例如：\n这是全网第一的祛痘产品，100%有效，国家级认证！\n点击免费领，名额有限！")
        self.text_edit.setFont(QFont("Microsoft YaHei", 11))
        # 设置行高，看起来不那么挤
        self.text_edit.setStyleSheet("QTextEdit { line-height: 150%; padding: 10px; }")

        left_layout.addWidget(self.text_edit)
        left_widget.setLayout(left_layout)

        # --- 右侧：报告区 ---
        right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)

        lbl_report = QLabel("📊 检测报告:")
        lbl_report.setStyleSheet("font-weight: bold; color: #333;")
        right_layout.addWidget(lbl_report)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(3)
        self.result_table.setHorizontalHeaderLabels(["违禁词", "次数", "建议修改"])
        # 优化列宽比例：违禁词(2) : 次数(1) : 建议(3)
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.result_table.setAlternatingRowColors(True)
        self.result_table.setStyleSheet("QTableWidget { gridline-color: #eee; }")

        right_layout.addWidget(self.result_table)
        right_widget.setLayout(right_layout)

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 7)  # 左侧给 70% 空间
        splitter.setStretchFactor(1, 3)  # 右侧给 30% 空间
        # 设置 splitter 的样式，让分割线明显一点
        splitter.setStyleSheet("QSplitter::handle { background-color: #ddd; }")

        # 关键：设置 stretch=1，确保它占据所有剩余垂直空间
        layout.addWidget(splitter, 1)

        # 4. 底部按钮
        btn_layout = QHBoxLayout()

        self.btn_check = QPushButton("⚡ 一键排雷")
        self.btn_check.setFixedHeight(50)
        self.btn_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_check.setStyleSheet("""
            QPushButton {
                background-color: #d93025; 
                color: white; 
                font-weight: bold; 
                font-size: 16px; 
                border-radius: 8px;
            }
            QPushButton:hover { background-color: #b02018; }
        """)
        self.btn_check.clicked.connect(self.check_text)

        self.btn_clear = QPushButton("🗑️ 清空内容")
        self.btn_clear.setFixedHeight(50)
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #f1f3f4; 
                color: #333; 
                border: 1px solid #dadce0; 
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #e8eaed; }
        """)
        self.btn_clear.clicked.connect(lambda: (self.text_edit.clear(), self.result_table.setRowCount(0)))

        btn_layout.addWidget(self.btn_check, 3)  # 按钮比例 3
        btn_layout.addWidget(self.btn_clear, 1)  # 按钮比例 1

        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def check_text(self):
        """核心检测逻辑"""
        content = self.text_edit.toPlainText()
        if not content:
            QMessageBox.warning(self, "提示", "请先输入文案！")
            return

        # 1. 重置所有格式 (清除旧的高亮)
        cursor = self.text_edit.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        format = QTextCharFormat()
        format.setBackground(Qt.GlobalColor.transparent)
        format.setForeground(Qt.GlobalColor.black)
        cursor.setCharFormat(format)

        # 2. 开始查找
        found_issues = {}

        highlight_format = QTextCharFormat()
        highlight_format.setBackground(QColor("#fff2cc"))
        highlight_format.setForeground(QColor("#d93025"))
        highlight_format.setFontWeight(QFont.Weight.Bold)

        for banned_word, suggestion in self.banned_dict.items():
            cursor = self.text_edit.textCursor()
            cursor.setPosition(0)
            self.text_edit.setTextCursor(cursor)

            count = 0
            while self.text_edit.find(banned_word):
                self.text_edit.textCursor().mergeCharFormat(highlight_format)
                count += 1

            if count > 0:
                found_issues[banned_word] = {"count": count, "suggestion": suggestion}

        # 3. 填充右侧表格
        self.result_table.setRowCount(len(found_issues))
        # 按出现频率或违禁词长度排序可能更好，这里先按字典序
        sorted_issues = sorted(found_issues.items(), key=lambda x: x[1]['count'], reverse=True)

        for row, (word, info) in enumerate(sorted_issues):
            item_word = QTableWidgetItem(word)
            item_word.setForeground(QColor("#d93025"))
            item_word.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.result_table.setItem(row, 0, item_word)

            item_count = QTableWidgetItem(str(info['count']))
            item_count.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.result_table.setItem(row, 1, item_count)

            item_sugg = QTableWidgetItem(info['suggestion'])
            item_sugg.setForeground(QColor("#188038"))
            item_sugg.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.result_table.setItem(row, 2, item_sugg)

        if not found_issues:
            QMessageBox.information(self, "完美", "✅ 未发现违禁词！")
        else:
            QMessageBox.warning(self, "检测完成", f"⚠️ 发现 {len(found_issues)} 处违规，已高亮显示。")


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    win = AdCheckerApp()
    win.show()
    sys.exit(app.exec())