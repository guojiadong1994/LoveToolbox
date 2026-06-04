import html
import re
from difflib import SequenceMatcher
from urllib.parse import urlparse, parse_qsl, unquote

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QTextEdit,
    QMessageBox
)
from PyQt6.QtGui import QFont


class LinkCheckerApp(QWidget):
    """广告链接检测工具：检测渠道、链接类型、字段差异和链接合法性。"""

    CHANNELS = {
        "华为鸿飞": ["huaweihongfei"],
        "华为信息流": ["huawei"],
        "荣耀信息流": ["rongyaoxxl"],
        "OPPO 竞价 push": ["oppojjpush"],
        "小米信息流": ["xiaomixxl"],
        "OPPO 信息流": ["oppoxxl"],
        "荣耀商业化 PUSH": ["rongyao"],
        "vivo 信息流": ["vivoxxl"],
    }

    TARGET_CHANNEL_CODE = "vivoxxl"
    TARGET_CHANNEL_NAME = "vivo 信息流"
    TARGET_LINK_TYPE = "DP"
    BASE_KEY = "__base__"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("链接检测")
        self.resize(940, 720)
        self.init_ui()

    def init_ui(self):
        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(16, 10, 16, 14)
        left_layout.setSpacing(8)

        original_label = QLabel("原始链接")
        original_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        left_layout.addWidget(original_label)

        self.original_input = QTextEdit()
        self.original_input.setPlaceholderText("请粘贴从原平台复制出来的原始链接")
        self.original_input.setFixedHeight(90)
        self.original_input.setStyleSheet("font-family: Consolas, Microsoft YaHei; font-size: 13px;")
        left_layout.addWidget(self.original_input)

        modified_label = QLabel("修改后的链接")
        modified_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        left_layout.addWidget(modified_label)

        self.modified_input = QTextEdit()
        self.modified_input.setPlaceholderText("请粘贴你自己修改后的链接")
        self.modified_input.setFixedHeight(90)
        self.modified_input.setStyleSheet("font-family: Consolas, Microsoft YaHei; font-size: 13px;")
        left_layout.addWidget(self.modified_input)

        self.check_btn = QPushButton("一键检测")
        self.check_btn.setFixedHeight(44)
        self.check_btn.setStyleSheet(
            "background-color: #1677ff; color: white; font-weight: bold; "
            "font-size: 16px; border-radius: 8px;"
        )
        self.check_btn.clicked.connect(self.run_check)
        left_layout.addWidget(self.check_btn)

        result_label = QLabel("检测结果")
        result_label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
        result_label.setStyleSheet("margin-top: 4px;")
        left_layout.addWidget(result_label)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMinimumHeight(300)
        self.result_text.setStyleSheet("font-family: Microsoft YaHei; font-size: 14px; background-color: #fbfbfb;")
        left_layout.addWidget(self.result_text)

        self.setLayout(left_layout)

    def run_check(self):
        original_link = self.original_input.toPlainText().strip()
        modified_link = self.modified_input.toPlainText().strip()

        if not original_link or not modified_link:
            QMessageBox.warning(self, "提示", "请先填写原始链接和修改后的链接。")
            return

        original_channel_name, original_channel_code = self.detect_channel(original_link)
        modified_channel_name, modified_channel_code = self.detect_channel(modified_link)
        original_type = self.detect_link_type(original_link)
        modified_type = self.detect_link_type(modified_link)
        validity_messages = self.validate_link(modified_link, original_link)
        differences = self.compare_links(original_link, modified_link)
        original_hk_items = self.extract_hk_items(original_link)
        modified_hk_items = self.extract_hk_items(modified_link)

        html_lines = []

        # 1. 渠道检测
        channel_text = f"原始链接所属渠道：{original_channel_name}（{original_channel_code}）"
        if original_channel_code == self.TARGET_CHANNEL_CODE:
            html_lines.append(self.green_line(channel_text + "，这是 vivo 信息流渠道。"))
        else:
            html_lines.append(
                self.red_line(channel_text + "，这不是 vivo 信息流渠道的，请仔细检查。")
            )

        if modified_channel_code != original_channel_code:
            html_lines.append(
                self.red_line(
                    f"修改后链接所属渠道：{modified_channel_name}（{modified_channel_code}），"
                    f"与原始链接渠道不一致，请仔细检查。"
                )
            )
        else:
            html_lines.append(
                self.green_line(
                    f"修改后链接所属渠道：{modified_channel_name}（{modified_channel_code}），与原始链接一致。"
                )
            )

        # 2. 链接类型检测
        type_text = f"链接类型：原始链接是 {original_type}，修改后链接是 {modified_type}。"
        if original_type == self.TARGET_LINK_TYPE and modified_type == self.TARGET_LINK_TYPE:
            html_lines.append(self.green_line(type_text + "类型正确。"))
        else:
            html_lines.append(self.red_line(type_text + "不是 DP 的，请仔细检查。"))

        # 3. 差异检测
        html_lines.append("<hr>")
        html_lines.append("<b>原始链接和修改后链接的不同位置：</b>")
        if not differences:
            html_lines.append(self.green_line("没有检测到字段或连续区域差异。"))
        else:
            for item in differences:
                html_lines.append(self.diff_line(item['old'], item['new']))

        # 4. HK 区域检测
        html_lines.append("<hr>")
        html_lines.append("<b>检测HK区域：</b>")
        html_lines.extend(self.hk_area_lines(original_hk_items, modified_hk_items))

        # 5. 合法性检测
        html_lines.append("<hr>")
        html_lines.append("<b>修改后链接合法性检测：</b>")
        if validity_messages:
            for message in validity_messages:
                html_lines.append(self.red_line(message))
        else:
            html_lines.append(
                self.green_line("修改后链接格式合法，没有发现明显的 &、%、等号、字段结构或链接整体结构错误。")
            )

        self.result_text.setHtml("".join(html_lines))

    def extract_hk_items(self, link):
        decoded_text = self.decode_repeated(link.strip())
        tokens = re.findall(r"HK[A-Za-z0-9_-]+", decoded_text)
        items = []
        seen = set()
        for token in tokens:
            if token not in seen:
                items.append({"token": token, "count": tokens.count(token)})
                seen.add(token)
        return items

    def hk_area_lines(self, original_items, modified_items):
        lines = []
        if not original_items and not modified_items:
            return [self.green_line("没有检测到以 HK 开头的字符串。")]

        original_tokens = [item["token"] for item in original_items]
        modified_tokens = [item["token"] for item in modified_items]

        if original_items:
            lines.append("<p style='margin:8px 0 4px 0; color:#222222; font-weight:bold;'>原始链接 HK：</p>")
            for item in original_items:
                count_text = f"，出现 {item['count']} 次" if item["count"] > 1 else ""
                lines.append(self.green_line(f"{self.safe(item['token'])}{count_text}"))
        else:
            lines.append(self.red_line("原始链接没有检测到 HK 字符串。"))

        if modified_items:
            lines.append("<p style='margin:8px 0 4px 0; color:#222222; font-weight:bold;'>修改后链接 HK：</p>")
            for item in modified_items:
                count_text = f"，出现 {item['count']} 次" if item["count"] > 1 else ""
                if item["token"] in original_tokens:
                    lines.append(self.green_line(f"{self.safe(item['token'])}{count_text}"))
                else:
                    lines.append(self.red_line(f"{self.safe(item['token'])}{count_text}，原始链接中没有这个 HK，请检查。"))
        else:
            lines.append(self.red_line("修改后链接没有检测到 HK 字符串。"))

        if original_tokens == modified_tokens:
            lines.append(self.green_line("HK 内容与原始链接一致。"))
        else:
            missing = [token for token in original_tokens if token not in modified_tokens]
            extra = [token for token in modified_tokens if token not in original_tokens]
            if missing:
                lines.append(self.red_line(f"修改后链接缺少这些 HK：{self.safe(', '.join(missing))}"))
            if extra:
                lines.append(self.red_line(f"修改后链接新增这些 HK：{self.safe(', '.join(extra))}"))
            if not missing and not extra:
                lines.append(self.red_line("HK 出现顺序或重复情况与原始链接不一致，请检查。"))
        return lines

    def detect_channel(self, link):
        params = self.extract_params(link)

        # 优先从 requestFrom / media 这种核心字段里判断，避免 huaweihongfei 被误判成 huawei。
        priority_values = []
        for key, value in params.items():
            key_lower = key.lower()
            if key_lower.endswith("requestfrom") or key_lower.endswith("media"):
                priority_values.append(value.lower())

        for name, codes in self.CHANNELS.items():
            for code in codes:
                if code.lower() in priority_values:
                    return name, code

        decoded_link = self.decode_repeated(link).lower()
        channel_items = []
        for name, codes in self.CHANNELS.items():
            for code in codes:
                channel_items.append((name, code))
        channel_items.sort(key=lambda x: len(x[1]), reverse=True)

        for name, code in channel_items:
            if code.lower() in decoded_link:
                return name, code

        return "未知渠道", "unknown"

    def detect_link_type(self, link):
        link_strip = link.strip()
        lower_link = self.decode_repeated(link_strip).lower()
        parsed = urlparse(link_strip)
        params = self.extract_params(link_strip)
        action = ""
        for key, value in params.items():
            if key.lower().endswith("action"):
                action = value.lower()
                break

        if link_strip.lower().startswith("alipays://platformapi/startapp"):
            return "DP"
        if "render.alipay.com/p/s/i/" in lower_link:
            return "H5"
        if "ulink.alipay.com" in lower_link:
            return "ULink"
        if "ugapi.alipay.com/monitor" in lower_link:
            if action == "expose":
                return "曝光链接"
            if action == "click":
                return "点击链接"
            return "监测链接"
        if parsed.scheme:
            return "其他链接"
        return "未知类型"

    def validate_link(self, link, original_link=None):
        messages = []
        text = link.strip()

        if not text:
            return ["修改后链接为空。"]
        if any(ch.isspace() for ch in text):
            messages.append("修改后链接中包含空格、换行或制表符，请检查是否复制了多余字符。")
        if re.search(r"%(?![0-9A-Fa-f]{2})", text):
            messages.append("修改后链接存在错误的百分号编码，例如 % 后面不是两位十六进制字符。")
        if any(ch in text for ch in ["＆", "？", "＝", "＃"]):
            messages.append("修改后链接中出现中文全角符号，请改成英文半角符号，例如 &、?、=、#。")
        if "&&" in text or text.endswith("&") or "?&" in text or "&?" in text:
            messages.append("修改后链接的 & 符号位置疑似错误，请检查是否多写、漏写或放错位置。")
        if text.count("?") > 1:
            messages.append("修改后链接中出现多个未编码的 ?，请检查是否把嵌套链接里的 ? 直接写出来了。")

        parsed = urlparse(text)
        if not parsed.scheme:
            messages.append("修改后链接缺少协议头，例如 https:// 或 alipays://。")
        elif parsed.scheme in ["http", "https"] and not parsed.netloc:
            messages.append("修改后链接是 http/https 类型，但缺少域名。")
        elif parsed.scheme == "alipays" and (parsed.netloc != "platformapi" or not parsed.path.startswith("/startapp")):
            messages.append("修改后链接是 DP 类型，但不是标准 alipays://platformapi/startapp 结构。")

        link_type = self.detect_link_type(text)
        if link_type == "未知类型":
            messages.append("修改后链接没有识别出明确的链接类型，请检查链接开头和域名是否正确。")
        elif link_type in ["H5", "ULink"]:
            params = self.extract_params(text)
            has_scheme = any(key.lower().endswith("scheme") for key in params)
            if not has_scheme:
                messages.append("修改后链接是 H5/ULink 类型，但没有检测到 scheme 字段，唤端结构可能不完整。")
        elif link_type in ["曝光链接", "点击链接", "监测链接"]:
            params = self.extract_params(text)
            has_action = any(key.lower().endswith("action") for key in params)
            if not has_action:
                messages.append("修改后链接是监测链接，但没有检测到 action 字段，无法判断曝光或点击。")

        self.validate_query_structure(text, "外层链接", messages, 0)
        if original_link:
            self.validate_against_original(original_link, text, messages)
        return self.unique_messages(messages)

    def validate_query_structure(self, text, context, messages, depth):
        if depth > 4 or not text:
            return

        parsed = urlparse(text)
        query = parsed.query
        if not query and "=" in text and "&" in text:
            query = text

        if not query:
            return

        self.check_query_segments(query, context, messages)

        try:
            pairs = parse_qsl(query, keep_blank_values=True)
        except Exception:
            messages.append(f"{context}字段解析失败，请检查 &、=、% 编码是否被改坏。")
            return

        for key, value in pairs:
            decoded_value = self.decode_repeated(value)
            if self.should_parse_nested(decoded_value):
                child_context = f"{context} > {key}"
                self.validate_query_structure(decoded_value, child_context, messages, depth + 1)

    def check_query_segments(self, query, context, messages):
        segments = query.split("&")
        for index, segment in enumerate(segments, start=1):
            if segment == "":
                messages.append(f"{context}第 {index} 个字段为空，请检查是否多写了 &。")
                continue
            if "=" not in segment:
                messages.append(f"{context}第 {index} 个字段缺少等号：{segment}")
                continue
            key, value = segment.split("=", 1)
            if key == "":
                messages.append(f"{context}第 {index} 个字段缺少字段名，等号前面不能为空。")
            if "?" in key:
                messages.append(f"{context}第 {index} 个字段名中出现 ?：{key}，请检查 ? 是否放错位置。")
            if any(ch in key for ch in ["/", "\\", "#"]):
                messages.append(f"{context}第 {index} 个字段名疑似异常：{key}")
            if "=" in value and not self.value_can_safely_contain_equal(value):
                messages.append(
                    f"{context}第 {index} 个字段 {key} 的值里又出现了等号：{segment}。"
                    "这很可能是少写了 &，导致后面的字段被合并到了前一个字段里。"
                )

    def value_can_safely_contain_equal(self, value):
        """URL 参数值里理论上可以出现 =，但在本工具的广告监测链接里通常应被编码。
        这里保守放过明显的 Base64 补位和已经编码/嵌套的链接场景，其余给出疑似错误提醒。
        """
        text = value.strip()
        if not text:
            return True
        if "%3D" in text.upper() or "%253D" in text.upper():
            return True
        if text.startswith("http://") or text.startswith("https://") or text.startswith("alipays://"):
            return True
        # Base64 常见是末尾一个或两个 =，中间不应该再跟字段形态。
        if re.fullmatch(r"[A-Za-z0-9+/_-]+={1,2}", text):
            return True
        return False

    def validate_against_original(self, original_text, modified_text, messages):
        """校验修改后链接是否保持了原始链接的字段结构。"""
        self._validate_structure_pair(original_text, modified_text, "外层链接", messages, 0)

    def _validate_structure_pair(self, old_text, new_text, context, messages, depth):
        if depth > 4:
            return

        old_query = self.get_query_text(old_text)
        new_query = self.get_query_text(new_text)
        if not old_query or not new_query:
            return

        old_segments = self.parse_query_segments(old_query)
        new_segments = self.parse_query_segments(new_query)
        old_keys = [item["key"] for item in old_segments if item["key"]]
        new_keys = [item["key"] for item in new_segments if item["key"]]

        if old_keys != new_keys:
            missing = self.keys_missing_with_occurrence(old_keys, new_keys)
            extra = self.keys_missing_with_occurrence(new_keys, old_keys)
            if missing:
                messages.append(
                    f"{context}字段结构和原始链接不一致，修改后缺少字段：{', '.join(missing)}。"
                    "请重点检查是否漏写 &、删错字段名，或把这个字段合并到了前一个字段里。"
                )
            if extra:
                messages.append(
                    f"{context}字段结构和原始链接不一致，修改后多出字段：{', '.join(extra)}。"
                    "请检查是否误新增字段，或 &、= 位置是否写错。"
                )
            if len(old_keys) != len(new_keys):
                messages.append(
                    f"{context}字段数量发生变化：原始为 {len(old_keys)} 个，修改后为 {len(new_keys)} 个。"
                    "如果只是改字段值，字段数量一般不应该变化。"
                )

        # 对同名字段继续检查嵌套结构，例如 ugParams、scheme。
        paired_count = min(len(old_segments), len(new_segments))
        for index in range(paired_count):
            old_item = old_segments[index]
            new_item = new_segments[index]
            if old_item["key"] != new_item["key"]:
                continue
            old_value = self.decode_repeated(old_item["value"])
            new_value = self.decode_repeated(new_item["value"])
            if self.should_parse_nested(old_value) or self.should_parse_nested(new_value):
                self._validate_structure_pair(
                    old_value,
                    new_value,
                    f"{context} > {old_item['key']}",
                    messages,
                    depth + 1,
                )

    def keys_missing_with_occurrence(self, source_keys, target_keys):
        """按出现次数比较字段，兼容 pid、partnerId 这种重复字段。"""
        remaining = list(target_keys)
        missing = []
        for key in source_keys:
            if key in remaining:
                remaining.remove(key)
            else:
                missing.append(key)
        return missing

    def compare_links(self, old_link, new_link):
        """按“连续变化区域”展示差异。

        优先按 URL 字段结构比较；如果发现某个字段值改变，同时后面的字段被吞进来了，
        会合并成一行显示，方便直接看出是否漏删或漏加了 &。
        """
        differences = []

        old_decoded = self.decode_repeated(old_link.strip())
        new_decoded = self.decode_repeated(new_link.strip())
        old_base = self.get_base_from_text(old_decoded)
        new_base = self.get_base_from_text(new_decoded)
        if old_base and new_base and old_base != new_base:
            differences.append({"old": old_base, "new": new_base, "kind": "base"})

        segment_diffs = self.compare_text_as_query(old_link.strip(), new_link.strip(), 0)
        differences.extend(segment_diffs)

        # 如果字段层面没有差异，但字符串确实变了，再退回到整体连续区域比较。
        if not differences and old_decoded != new_decoded:
            for old_part, new_part in self.find_changed_regions(old_decoded, new_decoded):
                differences.append({"old": old_part, "new": new_part, "kind": "raw"})

        return differences[:120]

    def compare_text_as_query(self, old_text, new_text, depth):
        if depth > 4:
            return []

        old_query = self.get_query_text(old_text)
        new_query = self.get_query_text(new_text)
        if not old_query and not new_query:
            return []

        old_segments = self.parse_query_segments(old_query)
        new_segments = self.parse_query_segments(new_query)
        diffs = self.compare_segment_lists(old_segments, new_segments, depth)
        return self.merge_probable_missing_ampersand(diffs)

    def compare_segment_lists(self, old_segments, new_segments, depth):
        old_keys = [item["key"] for item in old_segments]
        new_keys = [item["key"] for item in new_segments]
        matcher = SequenceMatcher(None, old_keys, new_keys)
        diffs = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for offset in range(i2 - i1):
                    old_item = old_segments[i1 + offset]
                    new_item = new_segments[j1 + offset]
                    diffs.extend(self.compare_same_key_segment(old_item, new_item, depth))
            elif tag == "delete":
                for old_item in old_segments[i1:i2]:
                    diffs.append(self.make_delete_diff(old_item))
            elif tag == "insert":
                for new_item in new_segments[j1:j2]:
                    diffs.append(self.make_insert_diff(new_item))
            else:
                diffs.extend(self.compare_replaced_segment_block(old_segments[i1:i2], new_segments[j1:j2], depth))

        return diffs

    def compare_replaced_segment_block(self, old_block, new_block, depth):
        """处理一段字段块变化，尽量把同名字段先对齐。"""
        diffs = []
        used_new_indexes = set()

        for old_item in old_block:
            match_index = None
            for index, new_item in enumerate(new_block):
                if index in used_new_indexes:
                    continue
                if old_item["key"] == new_item["key"]:
                    match_index = index
                    break

            if match_index is not None:
                used_new_indexes.add(match_index)
                diffs.extend(self.compare_same_key_segment(old_item, new_block[match_index], depth))
            else:
                diffs.append(self.make_delete_diff(old_item))

        for index, new_item in enumerate(new_block):
            if index not in used_new_indexes:
                diffs.append(self.make_insert_diff(new_item))

        diffs.sort(key=lambda item: (
            999999 if item.get("old_index") is None else item.get("old_index"),
            999999 if item.get("new_index") is None else item.get("new_index"),
        ))
        return diffs

    def compare_same_key_segment(self, old_item, new_item, depth):
        old_value = self.decode_repeated(old_item["value"])
        new_value = self.decode_repeated(new_item["value"])
        if old_value == new_value:
            return []

        # 如果是 ugParams、scheme 这类嵌套字段，继续向里面拆，不直接展示一大串父字段。
        if self.should_parse_nested(old_value) or self.should_parse_nested(new_value):
            nested_diffs = self.compare_text_as_query(old_value, new_value, depth + 1)
            if nested_diffs:
                return nested_diffs

        return [{
            "key": old_item["key"],
            "old": old_value if old_value else "空",
            "new": new_value if new_value else "空",
            "kind": "value",
            "old_index": old_item["index"],
            "new_index": new_item["index"],
        }]

    def make_delete_diff(self, old_item):
        old_text = old_item["raw"] if old_item["raw"] else old_item["key"]
        return {
            "key": old_item["key"],
            "old": old_text if old_text else "空",
            "new": "空/已删除",
            "kind": "delete",
            "old_index": old_item["index"],
            "new_index": None,
        }

    def make_insert_diff(self, new_item):
        new_text = new_item["raw"] if new_item["raw"] else new_item["key"]
        return {
            "key": new_item["key"],
            "old": "空/新增前不存在",
            "new": new_text if new_text else "空",
            "kind": "insert",
            "old_index": None,
            "new_index": new_item["index"],
        }

    def merge_probable_missing_ampersand(self, diffs):
        """把“前一个字段值被改坏 + 后一个字段消失”合并成一行。

        例如：
        原始：cid=__CREATIVEID__&timestamp=__TS__
        现在：cid=__CREATIVEID__stamp=__TS__
        这比拆成 cid 改了、timestamp 删除了更符合人工排查习惯。
        """
        merged = []
        index = 0
        while index < len(diffs):
            current = diffs[index]
            nxt = diffs[index + 1] if index + 1 < len(diffs) else None

            if (
                nxt
                and current.get("kind") == "value"
                and nxt.get("kind") == "delete"
                and current.get("old_index") is not None
                and nxt.get("old_index") == current.get("old_index") + 1
                and self.looks_like_field_was_swallowed(current.get("new", ""), nxt.get("key", ""))
            ):
                merged.append({
                    "old": f"{current.get('key')}={current.get('old')}&{nxt.get('old')}",
                    "new": f"{current.get('key')}={current.get('new')}",
                    "kind": "structure",
                    "old_index": current.get("old_index"),
                    "new_index": current.get("new_index"),
                })
                index += 2
                continue

            merged.append(current)
            index += 1

        return merged

    def looks_like_field_was_swallowed(self, new_value, deleted_key):
        text = str(new_value)
        if "=" not in text:
            return False
        if deleted_key and deleted_key.lower() in text.lower():
            return True
        # 兼容 timestamp 被误改成 stamp=__TS__ 这种情况。
        if deleted_key and len(deleted_key) >= 4:
            suffix = deleted_key[-4:].lower()
            if re.search(rf"{re.escape(suffix)}\s*=", text.lower()):
                return True
        return bool(re.search(r"[A-Za-z_][A-Za-z0-9_-]{1,40}\s*=", text))

    def get_query_text(self, text):
        raw_text = str(text).strip()
        parsed = urlparse(raw_text)
        if parsed.scheme and parsed.query:
            return parsed.query

        decoded_text = self.decode_repeated(raw_text)
        parsed_decoded = urlparse(decoded_text)
        if parsed_decoded.scheme and parsed_decoded.query:
            return parsed_decoded.query

        if "=" in decoded_text and "&" in decoded_text:
            return decoded_text
        return ""

    def parse_query_segments(self, query):
        segments = []
        if not query:
            return segments
        for index, raw_segment in enumerate(query.split("&")):
            if "=" in raw_segment:
                key, value = raw_segment.split("=", 1)
            else:
                key, value = raw_segment, ""
            segments.append({
                "index": index,
                "raw": raw_segment,
                "key": key,
                "value": value,
                "has_equal": "=" in raw_segment,
            })
        return segments

    def get_base_from_text(self, text):
        parsed = urlparse(text)
        if parsed.scheme:
            return self.get_base_value(parsed)
        return ""

    def find_changed_regions(self, old_value, new_value):
        old_text = str(old_value)
        new_text = str(new_value)
        matcher = SequenceMatcher(None, old_text, new_text)
        changes = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            old_part = old_text[i1:i2] if i1 != i2 else "空/新增前不存在"
            new_part = new_text[j1:j2] if j1 != j2 else "空/修改后已删除"
            changes.append((old_part, new_part))

        if not changes and old_text != new_text:
            changes.append((old_text if old_text else "空", new_text if new_text else "空"))
        return changes

    def extract_params(self, link):
        result = {}
        self._extract_params_recursive(link.strip(), "", result, 0)
        return result

    def _extract_params_recursive(self, text, prefix, result, depth):
        if depth > 4 or not text:
            return

        decoded_text = self.decode_repeated(text)
        parsed = urlparse(decoded_text)
        if parsed.scheme:
            base_value = self.get_base_value(parsed)
            base_key = f"{prefix}.{self.BASE_KEY}" if prefix else self.BASE_KEY
            result[base_key] = base_value

        query = parsed.query
        if not query and "=" in decoded_text and "&" in decoded_text:
            query = decoded_text

        if not query:
            return

        try:
            pairs = parse_qsl(query, keep_blank_values=True)
        except Exception:
            return

        for key, value in pairs:
            clean_key = f"{prefix}.{key}" if prefix else key
            decoded_value = self.decode_repeated(value)
            if clean_key in result:
                result[clean_key] = result[clean_key] + "；" + decoded_value
            else:
                result[clean_key] = decoded_value

            if self.should_parse_nested(decoded_value):
                self._extract_params_recursive(decoded_value, clean_key, result, depth + 1)

    def should_parse_nested(self, value):
        decoded = self.decode_repeated(value)
        if decoded.startswith("http://") or decoded.startswith("https://") or decoded.startswith("alipays://"):
            return True
        return "=" in decoded and "&" in decoded

    def get_base_value(self, parsed):
        if parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        return f"{parsed.scheme}:{parsed.path}"

    def display_key(self, key):
        text = key.replace(self.BASE_KEY, "链接基础结构")
        return text.replace(".", " > ")

    def decode_repeated(self, text, max_rounds=5):
        current = text
        for _ in range(max_rounds):
            decoded = unquote(current)
            if decoded == current:
                break
            current = decoded
        return current

    def unique_messages(self, messages):
        result = []
        seen = set()
        for message in messages:
            if message not in seen:
                result.append(message)
                seen.add(message)
        return result

    def diff_line(self, old_text, new_text):
        return (
            "<p style='margin:8px 0; line-height:1.55;'>"
            "<span style='color:#222222; font-weight:bold;'>原始：</span>"
            f"<span style='color:#188038; font-family:Consolas, Microsoft YaHei;'> {self.safe(old_text)}</span>"
            "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
            "<span style='color:#222222; font-weight:bold;'>现在：</span>"
            f"<span style='color:#d93025; font-family:Consolas, Microsoft YaHei;'> {self.safe(new_text)}</span>"
            "</p>"
        )

    def green_line(self, text):
        return f"<p style='color:#188038; margin:6px 0;'>{text}</p>"

    def red_line(self, text):
        return f"<p style='color:#d93025; font-weight:bold; margin:6px 0;'>{text}</p>"

    def safe(self, text):
        return html.escape(str(text))
