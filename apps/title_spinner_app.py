import sys
import itertools
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QTextEdit, QSpinBox, QMessageBox,
                             QSplitter, QGroupBox, QCheckBox, QApplication)
from PyQt6.QtGui import QFont, QClipboard
from PyQt6.QtCore import Qt


class TitleSpinnerApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("广告标题裂变生成器 (Vivo运营专用)")
        self.resize(1000, 700)

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # 1. 顶部标题
        header = QLabel("🧬 广告标题裂变工厂")
        header.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        layout.addWidget(header)

        tips = QLabel("说明：输入关键词（一行一个），系统将自动排列组合，生成上百条不重复的标题。")
        tips.setStyleSheet("color: #666; margin-bottom: 5px;")
        layout.addWidget(tips)

        # 2. 中间主体 (左右分栏)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # === 左侧：原料区 ===
        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 原料输入框组
        self.input_product = self.create_input_group("1. 产品/品牌词 (必填)", "例如：\nVivo X100\n新款手机\n千元神机")
        self.input_selling = self.create_input_group("2. 卖点/痛点 (必填)",
                                                     "例如：\n拍照超级好看\n运行速度飞快\n打游戏不卡顿")
        self.input_action = self.create_input_group("3. 引导/福利 (选填)", "例如：\n点击免费领\n限时查收\n0元试用")
        self.input_prefix = self.create_input_group("4. 前缀/修饰 (选填)", "例如：\n震惊！\n很多人不知道\n终于来了")

        left_layout.addWidget(self.input_product)
        left_layout.addWidget(self.input_selling)
        left_layout.addWidget(self.input_action)
        left_layout.addWidget(self.input_prefix)

        left_widget.setLayout(left_layout)

        # === 右侧：成品区 ===
        right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 设置区
        settings_group = QGroupBox("⚙️ 生成设置")
        settings_layout = QHBoxLayout()

        self.chk_shuffle = QCheckBox("乱序重排 (AB/BA模式)")
        self.chk_shuffle.setChecked(True)
        self.chk_shuffle.setToolTip("选中后会生成更多句式，如：'产品+卖点' 和 '卖点+产品'")

        settings_layout.addWidget(self.chk_shuffle)

        settings_layout.addWidget(QLabel("最大字数限制:"))
        self.spin_length = QSpinBox()
        self.spin_length.setRange(10, 100)
        self.spin_length.setValue(30)  # Vivo 标题通常限制 30 字
        settings_layout.addWidget(self.spin_length)

        settings_layout.addStretch()
        settings_group.setLayout(settings_layout)
        right_layout.addWidget(settings_group)

        # 结果显示
        self.result_area = QTextEdit()
        self.result_area.setPlaceholderText("生成的标题将显示在这里...\n支持一键复制到 Excel")
        self.result_area.setFont(QFont("Microsoft YaHei", 11))
        right_layout.addWidget(self.result_area)

        # 统计标签
        self.lbl_count = QLabel("共生成: 0 条")
        self.lbl_count.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_layout.addWidget(self.lbl_count)

        right_widget.setLayout(right_layout)

        # 加入分割器
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)

        layout.addWidget(splitter)

        # 3. 底部按钮
        btn_layout = QHBoxLayout()

        self.btn_gen = QPushButton("⚡ 开始裂变")
        self.btn_gen.setFixedHeight(50)
        self.btn_gen.setStyleSheet(
            "background-color: #0078d7; color: white; font-weight: bold; font-size: 16px; border-radius: 5px;")
        self.btn_gen.clicked.connect(self.generate_titles)

        self.btn_copy = QPushButton("📋 一键复制全部")
        self.btn_copy.setFixedHeight(50)
        self.btn_copy.setStyleSheet(
            "background-color: #f1f3f4; border: 1px solid #ccc; font-size: 14px; border-radius: 5px;")
        self.btn_copy.clicked.connect(self.copy_results)

        self.btn_clear = QPushButton("🗑️ 清空")
        self.btn_clear.setFixedHeight(50)
        self.btn_clear.clicked.connect(self.clear_all)

        btn_layout.addWidget(self.btn_gen, 2)
        btn_layout.addWidget(self.btn_copy, 1)
        btn_layout.addWidget(self.btn_clear, 1)

        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def create_input_group(self, title, placeholder):
        """辅助函数：创建带标题的输入框"""
        group = QGroupBox(title)
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        text_edit = QTextEdit()
        text_edit.setPlaceholderText(placeholder)
        text_edit.setFixedHeight(80)  # 固定高度，避免太占地
        layout.addWidget(text_edit)
        group.setLayout(layout)
        # 把 text_edit 存到 group 对象里，方便后续获取
        group.input_field = text_edit
        return group

    def get_lines(self, group_box):
        """获取输入框内容，按行分割，去空去重"""
        text = group_box.input_field.toPlainText()
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        return list(set(lines))  # 去重

    def generate_titles(self):
        products = self.get_lines(self.input_product)
        sellings = self.get_lines(self.input_selling)
        actions = self.get_lines(self.input_action)
        prefixes = self.get_lines(self.input_prefix)

        if not products or not sellings:
            QMessageBox.warning(self, "缺少原料", "【产品词】和【卖点词】是必填项哦！")
            return

        # 补充空项，方便 itertools 排列
        if not actions: actions = [""]
        if not prefixes: prefixes = [""]

        generated = set()
        max_len = self.spin_length.value()

        # 定义多种拼接模版
        # P=产品, S=卖点, A=引导, Pre=前缀

        # 基础循环
        for p in products:
            for s in sellings:
                for a in actions:
                    for pre in prefixes:
                        # 组合逻辑
                        combos = []

                        # 模版1: 前缀 + 产品 + 卖点 + 引导 (标准)
                        # "震惊！VivoX100 拍照好看 点击领红包"
                        t1 = f"{pre}{p}{s}{a}"
                        combos.append(t1)

                        if self.chk_shuffle.isChecked():
                            # 模版2: 前缀 + 卖点 + 产品 + 引导 (强调卖点)
                            # "震惊！拍照好看的 VivoX100 点击领红包"
                            t2 = f"{pre}{s}的{p}{a}"
                            combos.append(t2)

                            # 模版3: 引导 + 产品 + 卖点 (强调动作)
                            # "点击领红包 VivoX100 拍照好看"
                            if a:  # 只有当有引导词时才生成
                                t3 = f"{a}，{p}{s}"
                                combos.append(t3)

                        # 过滤和去重
                        for title in combos:
                            # 去掉可能多余的空格或标点
                            clean_title = title.replace("  ", " ").strip()
                            if len(clean_title) <= max_len:
                                generated.add(clean_title)

        # 排序输出 (按长度排序可能看起来更整齐)
        sorted_titles = sorted(list(generated), key=len)

        self.result_area.setPlainText("\n".join(sorted_titles))
        self.lbl_count.setText(f"共生成: {len(sorted_titles)} 条")

        if len(sorted_titles) == 0:
            QMessageBox.information(self, "提示", "生成结果为0，可能是字数限制太严格了？")

    def copy_results(self):
        content = self.result_area.toPlainText()
        if not content:
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(content)
        QMessageBox.information(self, "成功", "✅ 已复制到剪贴板！\n直接去 Excel 粘贴即可。")

    def clear_all(self):
        self.input_product.input_field.clear()
        self.input_selling.input_field.clear()
        self.input_action.input_field.clear()
        self.input_prefix.input_field.clear()
        self.result_area.clear()
        self.lbl_count.setText("共生成: 0 条")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = TitleSpinnerApp()
    win.show()
    sys.exit(app.exec())