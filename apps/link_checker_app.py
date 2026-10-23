# -*- coding: utf-8 -*-
"""LoveToolbox 链接检测：六输入框 / 支持任意完整链接对 / 精简规则。

仅检查：链接基本类型/格式、vivo 渠道及曝光点击渠道一致、
字段前后变化、曝光点击 partnerId 删除与必须修改、HK 变化、三链接 taskId 对应。
DP 可以保持不变；同一根因的提示合并，不对其他业务字段作强制推断。
"""

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import html
import re
from urllib.parse import parse_qsl, unquote, urlsplit

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextOption
from PyQt6.QtWidgets import (
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLayout, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget,
)

LINK_TYPES = ("exp", "click", "dp")
LINK_NAMES = {"exp": "曝光链接", "click": "点击链接", "dp": "DP 链接"}
STATUS_COLORS = {"pass": "#188038", "error": "#c62828"}
HK_PATTERN = re.compile(r"HK[A-Za-z0-9_-]+")
INVALID_PERCENT = re.compile(r"%(?![0-9a-fA-F]{2})")


@dataclass
class Finding:
    group: str
    status: str
    title: str
    detail: str
    before: str = ""
    after: str = ""
    change: bool = False


def _parse(raw):
    try:
        url = urlsplit(raw)
        pairs = parse_qsl(url.query, keep_blank_values=True)
        return url, pairs
    except ValueError:
        return None, []


def _params(pairs):
    # Value is a list: repeated parameters cannot be silently overwritten.
    grouped = {}
    for key, value in pairs:
        normalized = key.lower()
        if normalized not in grouped:
            grouped[normalized] = {"name": key, "values": []}
        grouped[normalized]["values"].append(value)
    return grouped


def _same_values(left, right):
    return Counter(left) == Counter(right)


def _display(name, values):
    if not values:
        return "（不存在）"
    return "；".join(f"{name}={value}" for value in values)


def _decode(text):
    value = text
    for _ in range(4):
        next_value = unquote(value)
        if next_value == value:
            break
        value = next_value
    return value


def _hk(text):
    return Counter(HK_PATTERN.findall(_decode(text)))


def _nested(value, key):
    """Return (container location, parsed inner fields) for known structured parameters.

    The outer URL is parsed first: %26 inside a value must never become an outer &.
    Unknown keys (including typos) remain one atomic field, permitting rename matching.
    """
    key = key.lower()
    if key not in ("ugparams", "page", "scheme", "url", "redirecturl", "targeturl", "deeplink"):
        return None
    text = _decode(value)
    if key == "ugparams":
        query, base = text, ""
    elif "?" in text:
        base, query = text.split("?", 1)
    else:
        return None
    if "=" not in query:
        return None
    return base, _params(parse_qsl(query, keep_blank_values=True))


def _task_id(raw):
    # Task ID is used ONLY for three-link association, not for validating other ugParams keys.
    # Tolerates a misspelled *container name*, e.g. ugParms -> ugParams.
    url, pairs = _parse(raw)
    vals = []
    for key, value in pairs:
        if key.lower() == "taskid":
            vals.append(value)
        txt = _decode(value)
        vals.extend(re.findall(r"(?:^|[?&])taskId=([^&#]+)", txt, re.I))
    return list(dict.fromkeys(vals))


def _channel_fields(raw):
    """Read the actual channel fields without searching unrelated URL text.

    For monitoring URLs, requestFrom is the main source; for DP, media in
    a nested query value is used.  Values inside typo-named ugParams-like
    containers are still readable, avoiding cascading false positives.
    """
    url, pairs = _parse(raw)
    request_from = [v for k, v in pairs if k.lower() == "requestfrom"]
    media = []
    for key, value in pairs:
        if key.lower() == "media":
            media.append(value)
        decoded = _decode(value)
        media.extend(re.findall(r"(?:^|[?&])media=([^&#]*)", decoded, re.I))
    # Duplicate equal values are harmless for identification here; do not
    # enforce existence of any other ugParams key.
    request_from = list(dict.fromkeys(request_from))
    media = list(dict.fromkeys(media))
    return request_from, media


def _effective_change(before, after):
    """A field/base change counts, while whitespace or parameter reordering doesn't."""
    old_url, old_pairs = _parse(before)
    new_url, new_pairs = _parse(after)
    if not old_url or not new_url:
        return before != after
    if (old_url.scheme, old_url.netloc, old_url.path, old_url.fragment) != (new_url.scheme, new_url.netloc, new_url.path, new_url.fragment):
        return True
    return Counter(old_pairs) != Counter(new_pairs)


def _link_type(raw):
    url, pairs = _parse(raw)
    if url is None:
        return "无法解析"
    if url.scheme.lower() == "alipays" and url.netloc.lower() == "platformapi" and url.path.lower() == "/startapp":
        return "dp"
    if (url.scheme.lower() in ("http", "https") and url.netloc.lower() == "ugapi.alipay.com"
            and url.path.rstrip("/").lower() == "/monitor"):
        acts = [v.lower() for k, v in pairs if k.lower() == "action"]
        if acts == ["expose"]:
            return "exp"
        if acts == ["click"]:
            return "click"
        return "监测链接(action不正确)"
    return "其他类型"


def _type_label(value):
    return {"exp": "曝光", "click": "点击", "dp": "DP"}.get(value, value)


def _format_issues(raw):
    url, pairs = _parse(raw)
    issues = []
    if not raw.strip():
        return ["链接为空"]
    if url is None:
        return ["URL 无法正常解析"]
    if any(c.isspace() for c in raw):
        issues.append("存在空格、换行或制表符")
    if INVALID_PERCENT.search(raw):
        issues.append("% 编码不完整")
    if any(x in raw for x in "＆？＝＃"):
        issues.append("存在中文全角 URL 分隔符")
    if not url.scheme:
        issues.append("缺少协议")
    if url.scheme.lower() in ("http", "https") and not url.netloc:
        issues.append("缺少域名")
    if raw.count("?") > 1:
        issues.append("存在未编码的多个问号")
    if not url.query:
        issues.append("缺少 URL 查询参数")
    if url.query.startswith("&") or url.query.endswith("&") or "&&" in url.query:
        issues.append("& 分隔符位置异常")
    for s in url.query.split("&"):
        if s and "=" not in s:
            issues.append("存在缺少 = 的参数")
        elif s.startswith("="):
            issues.append("存在空字段名")
    return list(dict.fromkeys(issues))


class LinkAuditEngine:
    """Only output actual edits and independent, actionable problems; no cascade warnings."""

    def __init__(self):
        self.findings = []

    def _add(self, kind, status, title, before, after, detail="", change=False):
        self.findings.append(Finding(LINK_NAMES[kind] if kind in LINK_NAMES else kind,
                                     status, title, detail, str(before), str(after), change))

    def audit(self, links):
        self.findings = []
        active = [kind for kind in LINK_TYPES
                  if links.get(f"old_{kind}", "").strip()
                  and links.get(f"new_{kind}", "").strip()]
        if not active:
            return self.findings
        for kind in active:
            before, after = links.get(f"old_{kind}", "").strip(), links.get(f"new_{kind}", "").strip()
            self._compare(before, after, kind)
            self._basic(before, after, kind)
            self._check_required_edit(before, after, kind)
        self._check_channels(links, active)
        self._check_taskid(links, active)
        return self.findings

    def _basic(self, before, after, kind):
        old_type, new_type = _link_type(before), _link_type(after)
        if old_type != kind or new_type != kind:
            description = f"链接类型不正确：原始{_type_label(old_type)}、修改后{_type_label(new_type)}；应为{_type_label(kind)}。"
            relevant = [f for f in self.findings if f.group == LINK_NAMES[kind] and f.change
                        and ("action=" in (f.before + f.after).lower() or f.title == "链接地址变化")]
            if relevant:
                relevant[0].detail += " " + description
            else:
                self._add(kind, "error", "链接类型错误",
                          f"原始：{_type_label(old_type)}", f"修改后：{_type_label(new_type)}",
                          description)

        old_format, new_format = _format_issues(before), _format_issues(after)
        if old_format or new_format:
            self._add(kind, "error", "URL 格式异常",
                      "；".join(old_format) if old_format else "格式正常",
                      "；".join(new_format) if new_format else "格式正常",
                      "检查 URL 协议、域名、编码、特殊字符和参数分隔符。")


    def _check_required_edit(self, before, after, kind):
        """On exp/click, original partnerId must be removed; DP may be unchanged.

        Combine an unmodified link with the missing partnerId deletion into
        a *single* actionable row, never two alarms for one oversight.
        """
        if kind == "dp":
            return
        _, old_pairs = _parse(before)
        _, new_pairs = _parse(after)
        original = [v for k, v in old_pairs if k.lower() == "partnerid"]
        current = [v for k, v in new_pairs if k.lower() == "partnerid"]
        changed = _effective_change(before, after)
        if original and current:
            # A partnerId value edit was already reported by field comparison:
            # annotate it rather than printing a second row.
            relevant = [f for f in self.findings if f.group == LINK_NAMES[kind] and f.change
                        and "partnerid" in (f.before + f.after).lower()]
            msg = "原始链接中的 partnerId 需要完整删除，修改后仍存在。"
            if not changed:
                msg += " 曝光/点击链接也没有发生有效修改，请检查是否粘贴错误。"
            if relevant:
                f = relevant[0]
                f.detail += " " + msg
                f.status = "error"
            else:
                self._add(kind, "error", "partnerId 未删除",
                          _display("partnerId", original), _display("partnerId", current), msg)
            return
        if not changed:
            self._add(kind, "error", "曝光/点击链接未修改",
                      "没有有效的字段变化", "没有有效的字段变化",
                      "曝光和点击链接必须经过修改；检查是否直接粘贴了原始链接。"
                      + (" 原始链接没有 partnerId，请确认该任务是否需要其他修改。" if not original else ""))
        # If source had no partnerId, don't claim it *had* to be removed;
        # extra fields still show as ordinary red changes.

    def _check_channels(self, links, active):
        """Identify Vivo and check exposure/click requestFrom + optional media.

        One error per channel root cause, not one per inner business field.
        Old data is shown for context; the *final* configuration is what
        drives consistency errors. A pre-existing and unresolved mismatch
        must still be reported.
        """
        values = {}
        for kind in active:
            before, after = links.get(f"old_{kind}", ""), links.get(f"new_{kind}", "")
            old_req, old_media = _channel_fields(before)
            new_req, new_media = _channel_fields(after)
            values[kind] = (old_req, old_media, new_req, new_media)

            # Prefer requestFrom for monitoring links and media for DP.
            old_signal = old_req if kind in ("exp", "click") else old_media or old_req
            new_signal = new_req if kind in ("exp", "click") else new_media or new_req
            if len(old_signal) == 1 and old_signal[0].lower().startswith("vivo") and len(new_signal) == 1 and new_signal[0].lower().startswith("vivo"):
                continue
            def show(sig):
                return ", ".join(sig) if sig else "（缺少可识别渠道标识）"
            msg = "无法确认是 vivo 渠道；曝光/点击检查 requestFrom，DP 检查可用的 media。"
            match = [f for f in self.findings if f.group == LINK_NAMES[kind] and f.change
                     and ("requestfrom" in (f.before + f.after).lower()
                          or "media" in (f.before + f.after).lower())]
            if match:
                match[0].detail += " " + msg
                match[0].status = "error"
            else:
                self._add(kind, "error", "vivo 渠道异常", show(old_signal), show(new_signal), msg)

        old_exp, old_click = values.get("exp"), values.get("click")
        def one(xs):
            return xs[0] if len(xs) == 1 else None
        before_exp = one(old_exp[0]) if old_exp else None
        after_exp = one(old_exp[2]) if old_exp else None
        before_click = one(old_click[0]) if old_click else None
        after_click = one(old_click[2]) if old_click else None
        # A missing requestFrom is already covered by the basic Vivo check;
        # avoid another alert with the same cause.
        different_requests = (after_exp is not None and after_click is not None and after_exp != after_click)
        media_issues = []
        for kind, data in (("exp", old_exp), ("click", old_click)):
            if data is None:
                continue
            req, media = one(data[2]), one(data[3])
            if req is not None and media is not None and req != media:
                media_issues.append((kind, req, media))
        if not different_requests and not media_issues:
            return
        explanations = []
        if different_requests:
            explanations.append("曝光与点击的 requestFrom 不一致")
        for kind, req, media in media_issues:
            explanations.append(f"{_type_label(kind)}内部 requestFrom={req} 与 media={media} 不一致")
        reason = "；".join(explanations) + "。请核对渠道标识。"
        # If the same field was edited, fold the channel warning into that
        # changed field row. Otherwise show exactly one dedicated row.
        affected = ("exp", "click") if different_requests else tuple(x[0] for x in media_issues)
        matching = [f for f in self.findings if f.change and f.group in [LINK_NAMES[k] for k in affected]
                    and ("requestfrom" in (f.before + f.after).lower()
                         or "media" in (f.before + f.after).lower())]
        if matching:
            matching[0].detail += " " + reason
            matching[0].status = "error"
        else:
            def label(req, media):
                return f"requestFrom={req or '缺失'}" + (f"；media={media}" if media is not None else "")
            if different_requests:
                before_label = (f"曝光：{label(before_exp, one(old_exp[1]))}；"
                                f"点击：{label(before_click, one(old_click[1]))}")
                after_label = (f"曝光：{label(after_exp, one(old_exp[3]))}；"
                               f"点击：{label(after_click, one(old_click[3]))}")
                self._add("曝光/点击", "error", "vivo 渠道标识不一致", before_label, after_label, reason)
            elif len(media_issues) == 1:
                kind = media_issues[0][0]
                data = values[kind]
                self._add(kind, "error", "渠道内部标识不一致",
                          label(one(data[0]), one(data[1])), label(one(data[2]), one(data[3])), reason)
            else:
                def both(stage):
                    return "；".join(
                        f"{_type_label(k)}：{label(one(values[k][0 if stage == 'old' else 2]), one(values[k][1 if stage == 'old' else 3]))}"
                        for k in ("exp", "click")
                    )
                self._add("曝光/点击", "error", "渠道内部标识不一致",
                          both("old"), both("new"), reason)

    def _compare(self, before, after, kind):
        old_url, old_pairs = _parse(before)
        new_url, new_pairs = _parse(after)
        if old_url is None or new_url is None:
            if before != after:
                self._add(kind, "error", "无法解析的链接发生变化", "原始链接", "修改后的链接",
                          "URL 格式异常，无法安全逐字段比较。")
            return

        old_base = (old_url.scheme, old_url.netloc, old_url.path, old_url.fragment)
        new_base = (new_url.scheme, new_url.netloc, new_url.path, new_url.fragment)
        if old_base != new_base:
            def base(u):
                return f"{u.scheme}://{u.netloc}{u.path}" + ("#" + u.fragment if u.fragment else "")
            self._add(kind, "error", "链接地址变化", base(old_url), base(new_url),
                      "协议、域名、路径或片段被修改，请核对。", change=True)

        old, new = _params(old_pairs), _params(new_pairs)
        same = set(old) & set(new)
        removed, added = set(old) - same, set(new) - same
        renames = []
        # Find one-to-one key renames BEFORE classifying addition/removal.
        # Identical parameter value + similar key names means a *single rename*.
        # This is crucial for ugParms -> ugParams and prevents 10+ false alerts.
        for a in sorted(removed):
            candidates = []
            for b in added:
                key_similarity = SequenceMatcher(None, a, b).ratio()
                value_equal = _same_values(old[a]["values"], new[b]["values"])
                value_similarity = SequenceMatcher(None, "|".join(old[a]["values"]),
                                                   "|".join(new[b]["values"])).ratio()
                if (value_equal and key_similarity >= 0.65) or (key_similarity >= 0.85 and value_similarity >= 0.65):
                    candidates.append((key_similarity + value_similarity, b))
            if candidates:
                _, b = max(candidates)
                renames.append((a, b))
                added.remove(b)
        removed.difference_update(a for a, _ in renames)

        # Detect obvious missing '&' by recognizing a now-embedded former field.
        # Report a single merged-field issue rather than a changed value + deleted key.
        merged_parents, merged_removals = {}, set()
        for key in same:
            ov, nv = old[key]["values"], new[key]["values"]
            if len(ov) != 1 or len(nv) != 1 or ov == nv:
                continue
            joined = []
            for missing in removed:
                marker = old[missing]["name"] + "="
                if marker in nv[0] and marker not in ov[0]:
                    joined.append(missing)
            if joined:
                merged_parents[key] = joined
                merged_removals.update(joined)

        # Standard leaf-level comparison for unchanged container names.
        for key in old:
            if key not in same:
                continue
            if key in merged_parents:
                others = merged_parents[key]
                name = old[key]["name"]
                before_merged = _display(name, old[key]["values"])
                for lost in others:
                    before_merged += "&" + _display(old[lost]["name"], old[lost]["values"])
                self._add(kind, "error", "疑似漏写 &", before_merged,
                          _display(new[key]["name"], new[key]["values"]),
                          "原来独立的字段疑似被拼进前一字段，可能漏写了 &。", change=True)
                continue
            ov, nv = old[key]["values"], new[key]["values"]
            label = old[key]["name"]
            new_label = new[key]["name"]
            if label != new_label:
                if _same_values(ov, nv):
                    self._add(kind, "error", "字段名称变化", label, new_label,
                              "字段名称大小写发生变化，请核对。", change=True)
                else:
                    self._add(kind, "error", "字段名称及取值变化",
                              _display(label, ov), _display(new_label, nv),
                              "字段名称和取值均变化，请核对。", change=True)
                continue
            if _same_values(ov, nv):
                continue
            if len(ov) == len(nv) == 1:
                nested_old, nested_new = _nested(ov[0], key), _nested(nv[0], key)
                if nested_old is not None and nested_new is not None:
                    old_base, old_children = nested_old
                    new_base, new_children = nested_new
                    if old_base != new_base:
                        self._add(kind, "error", "内层地址变化", f"{label}={old_base}", f"{label}={new_base}",
                                  "内层页面或链接地址改变，请核对。", change=True)
                    self._compare_children(kind, label, old_children, new_children)
                    continue
            self._add(kind, "error", "参数值变化", _display(label, ov), _display(new[key]["name"], nv),
                      "字段值发生变化，请核对是否为预期修改。", change=True)

        for a, b in renames:
            ov, nv = old[a]["values"], new[b]["values"]
            changed_values = not _same_values(ov, nv)
            if changed_values:
                self._add(kind, "error", "字段名称及取值变化",
                          _display(old[a]["name"], ov), _display(new[b]["name"], nv),
                          "字段名称及内容均发生变化，请核对。", change=True)
            else:
                self._add(kind, "error", "字段名称变化", old[a]["name"], new[b]["name"],
                          "字段名称发生变化，内部取值未变，请核对字段名是否正确。", change=True)
        # In normal cases just show one row for each added or removed parameter.
        for key in old:
            if key not in removed:
                continue
            if key in merged_removals:
                continue
            label, values = old[key]["name"], old[key]["values"]
            approved = kind in ("exp", "click") and key == "partnerid" and len(values) == 1
            display = _display(label, values)
            if approved:
                display = "&" + display
            self._add(kind, "pass" if approved else "error", "删除字段", display, "（已删除）",
                      "正常删除 partnerId。" if approved else "删除了其他字段，请确认是否误删。", change=True)
        for key in new:
            if key not in added:
                continue
            self._add(kind, "error", "新增字段", "（不存在）", _display(new[key]["name"], new[key]["values"]),
                      "新增了原始链接中没有的字段，请核对。", change=True)

        # HK is a separate safety check, but folds into a corresponding changed row.
        # Do not print both a 'benefit changed' row AND an 'HK changed' row.
        hk_before, hk_after = _hk(before), _hk(after)
        if hk_before != hk_after:
            candidates = [f for f in self.findings if f.group == LINK_NAMES[kind] and f.change
                          and (_hk(f.before) != _hk(f.after))]
            if candidates:
                first = candidates[0]
                first.detail += " HK 标识或出现次数发生变化，请重点核对。"
                first.status = "error"
            else:
                self._add(kind, "error", "HK 变化", str(dict(hk_before)), str(dict(hk_after)),
                          "HK 内容或出现次数变化，请核对。", change=True)

    def _compare_children(self, kind, prefix, old, new):
        shared = set(old) & set(new)
        removed = set(old) - shared
        added = set(new) - shared
        renames = []
        for a in sorted(removed):
            options = []
            for b in added:
                sim = SequenceMatcher(None, a, b).ratio()
                if sim >= 0.65 and _same_values(old[a]["values"], new[b]["values"]):
                    options.append((sim, b))
            if options:
                _, b = max(options)
                renames.append((a, b))
                added.remove(b)
        removed.difference_update(a for a, _ in renames)
        for key in old:
            if key not in shared:
                continue
            a, b = old[key], new[key]
            old_name, new_name = f"{prefix} → {a['name']}", f"{prefix} → {b['name']}"
            if a["name"] != b["name"] or not _same_values(a["values"], b["values"]):
                self._add(kind, "error", "内层字段变化",
                          _display(old_name, a["values"]), _display(new_name, b["values"]),
                          "内层字段发生变化，请核对。", change=True)
        for a, b in renames:
            self._add(kind, "error", "内层字段名称变化", f"{prefix} → {old[a]['name']}",
                      f"{prefix} → {new[b]['name']}", "内层字段名称被修改，请核对。", change=True)
        for key in old:
            if key in removed:
                a = old[key]
                self._add(kind, "error", "内层字段删除", _display(f"{prefix} → {a['name']}", a["values"]),
                          "（已删除）", "内层字段被删除，请核对。", change=True)
        for key in new:
            if key in added:
                b = new[key]
                self._add(kind, "error", "内层字段新增", "（不存在）", _display(f"{prefix} → {b['name']}", b["values"]),
                          "内层新增字段，请核对。", change=True)

    def _check_taskid(self, links, active):
        # 单组不做跨组关联检测；两组或三组才比对 taskId。
        if len(active) < 2:
            return
        old = {kind: _task_id(links.get(f"old_{kind}", "")) for kind in active}
        new = {kind: _task_id(links.get(f"new_{kind}", "")) for kind in active}
        def aligned(v):
            return all(len(v[k]) == 1 for k in active) and len({v[k][0] for k in active}) == 1
        scope = "、".join(_type_label(k) for k in active)
        label = f"{len(active)}组链接"
        if aligned(new):
            return
        # A single taskId edit can be the reason for an association mismatch;
        # attach that fact to the actual change instead of generating a second row.
        matching = [f for f in self.findings if f.change and "taskid" in (f.before + f.after).lower()]
        if matching:
            for f in matching:
                f.detail += f" 修改后已填写的链接组（{scope}）taskId 不一致，请确认是否串用了其他任务的链接。"
                f.status = "error"
            return
        def show(d):
            return "；".join(f"{_type_label(k)}：{','.join(d[k]) if d[k] else '缺失'}" for k in active)
        self._add(scope, "error", f"{label} taskId 不一致", show(old), show(new),
                  f"修改后已填写的链接组（{scope}）taskId 缺失或不一致，请确认属于同一任务。")

class LinkCheckerApp(QWidget):
    """LoveToolbox 兼容入口；界面与检测引擎均在这一个文件中。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("链接检测")
        self.resize(1100, 780)
        self.setMinimumSize(620, 450)
        self.inputs = {}
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet("""
            QWidget { font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; }
            QGroupBox { font-weight: 600; border: 1px solid #dce2e9;
                        border-radius: 9px; margin-top: 12px; background: white; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px;
                               padding: 0 7px; color: #263445; }
            QTextEdit { border: 1px solid #cbd5e1; background: #fcfdff;
                        border-radius: 7px; padding: 6px; font-size: 12px; }
            QTextEdit:focus { border: 2px solid #1677ff; }
            QTextBrowser { border: 1px solid #dce2e9; border-radius: 8px;
                           background: #ffffff; padding: 8px; font-size: 12px; }
            QPushButton { border-radius: 8px; padding: 9px 16px; font-size: 14px; }
            QScrollArea { border: 0; background: transparent; }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll the whole page when the available height is insufficient.
        # The input group maintains its natural size and each edit retains
        # all four borders in normal/maximized/small window states.
        self.page_scroll = QScrollArea(self)
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        outer.addWidget(self.page_scroll)
        page = QWidget()
        self.page_scroll.setWidget(page)
        root = QVBoxLayout(page)
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        root.setContentsMargins(18, 14, 18, 18)
        root.setSpacing(12)

        title = QLabel("链接检测")
        title.setFont(QFont("Microsoft YaHei", 17, QFont.Weight.Bold))
        title.setStyleSheet("color: #172b4d;")
        root.addWidget(title)

        input_box = QGroupBox("链接输入（至少填写一组修改前和修改后）")
        input_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QGridLayout(input_box)
        layout.setContentsMargins(13, 22, 13, 15)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(12)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        for col, heading in enumerate(("修改前 · 原始链接", "修改后 · 待投放链接")):
            label = QLabel(heading)
            label.setFont(QFont("Microsoft YaHei", 11, QFont.Weight.Bold))
            label.setStyleSheet("color: #23415c;")
            layout.addWidget(label, 0, col)
        for row, kind in enumerate(LINK_TYPES, 1):
            for col, stage in enumerate(("old", "new")):
                key = f"{stage}_{kind}"
                cell = QWidget()
                cell.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                v = QVBoxLayout(cell)
                v.setContentsMargins(2, 2, 2, 3)  # Keep borders away from cell edges.
                v.setSpacing(6)
                label = QLabel(f"{row}. {LINK_NAMES[kind]}")
                label.setStyleSheet("color: #475569; font-size: 12px; font-weight: 600;")
                edit = QTextEdit()
                edit.setAcceptRichText(False)
                edit.setPlaceholderText(f"粘贴{'原始' if stage == 'old' else '修改后'}{LINK_NAMES[kind]}…")
                edit.setMinimumHeight(92)
                edit.setFixedHeight(92)
                edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
                v.addWidget(label)
                v.addWidget(edit)
                layout.addWidget(cell, row, col)
                self.inputs[key] = edit
        root.addWidget(input_box)

        controls = QHBoxLayout()
        controls.setSpacing(12)
        self.check_btn = QPushButton("一键检测")
        self.check_btn.setMinimumHeight(52)
        self.check_btn.setStyleSheet("""
            QPushButton { color: white; background: #1677ff; font-weight: 700; }
            QPushButton:hover { background: #0966db; }
            QPushButton:pressed { background: #0757be; }
        """)
        self.check_btn.clicked.connect(self.run_check)
        self.clear_btn = QPushButton("清空全部")
        self.clear_btn.setMinimumHeight(52)
        self.clear_btn.setStyleSheet("""
            QPushButton { background: #f1f5f9; color: #415266;
                          border: 1px solid #dce2e9; font-weight: 600; }
            QPushButton:hover { background: #e7edf4; }
        """)
        self.clear_btn.clicked.connect(self.clear_all)
        controls.addWidget(self.check_btn, 1)
        controls.addWidget(self.clear_btn, 1)
        root.addLayout(controls)

        # One compact result table: ALL actual edits (even allowed edits),
        # plus warning/error rows. No expandable cards or second detail pane.
        results = QGroupBox("检测结果")
        results.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        res_layout = QVBoxLayout(results)
        res_layout.setContentsMargins(12, 22, 12, 14)
        res_layout.setSpacing(10)
        self.summary = QLabel("至少填写一组修改前、修改后链接，点击“一键检测”。")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("color: #58677d; font-weight: 600; padding: 3px;")
        res_layout.addWidget(self.summary)
        self.result_view = QTextBrowser()
        self.result_view.setOpenExternalLinks(False)
        self.result_view.setReadOnly(True)
        self.result_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.result_view.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.result_view.setMinimumHeight(92)
        self.result_view.setFixedHeight(110)
        self.result_view.setHtml(self._empty_html())
        res_layout.addWidget(self.result_view)
        note = QLabel("说明：空白链接组将跳过，只填写一侧会提示补全；所有实际变化都会显示；曝光/点击须删除原始 partnerId 且有效修改，DP 允许不改。绿色为正常修改，红色为错误或需核对。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #768398; font-size: 11px;")
        res_layout.addWidget(note)
        root.addWidget(results)
        root.addStretch(1)

    @staticmethod
    def _empty_html():
        return (
            "<p style='color:#64748b'>检测后按行显示所有实际修改（包括正常修改），"
            "以及需要确认或不通过的项目。</p>"
        )

    def clear_all(self):
        for edit in self.inputs.values():
            edit.clear()
        self.summary.setText("至少填写一组修改前、修改后链接，点击“一键检测”。")
        self.summary.setStyleSheet("color: #58677d; font-weight: 600; padding: 3px;")
        self.result_view.setHtml(self._empty_html())
        self.result_view.setFixedHeight(110)
        self.result_view.verticalScrollBar().setValue(0)

    def run_check(self):
        links = {key: edit.toPlainText().strip() for key, edit in self.inputs.items()}
        incomplete = []
        complete = []
        for kind in LINK_TYPES:
            old = bool(links[f"old_{kind}"])
            new = bool(links[f"new_{kind}"])
            if old != new:
                incomplete.append(f"{LINK_NAMES[kind]}（缺少{'修改后' if old else '修改前'}）")
            elif old:
                complete.append(kind)
        if incomplete:
            QMessageBox.warning(self, "链接未成对填写", "请补全以下链接组：\n" + "\n".join(incomplete))
            return
        if not complete:
            QMessageBox.warning(self, "缺少链接", "请至少填写一组完整的修改前和修改后链接。")
            return
        engine = LinkAuditEngine()
        findings = engine.audit(links)
        self._render_findings(findings, links)

    @staticmethod
    def _escaped(text):
        return html.escape(str(text), quote=True).replace("\n", "<br>")

    @staticmethod
    def _link_type_label(finding):
        return {"曝光链接": "曝光", "点击链接": "点击", "DP 链接": "DP"}.get(finding.group, finding.group)

    def _render_findings(self, findings, links):
        order = {"曝光": 0, "点击": 1, "DP": 2, "曝光/点击/DP": 3}
        rows = sorted(findings, key=lambda f: order.get(self._link_type_label(f), 4))
        edits = sum(f.change for f in rows)
        green = sum(f.change and f.status == "pass" for f in rows)
        errors = sum(f.status == "error" for f in rows)
        if errors:
            summary = f"检测完成：发现 {edits} 处变化，其中 {green} 处正常删除；另有 {errors} 项需要核对或存在错误。"
            color = STATUS_COLORS["error"]
        else:
            summary = f"检测完成：共 {edits} 处变化（正常删除 {green} 处），未发现其他异常。"
            color = STATUS_COLORS["pass"]
        self.summary.setText(summary)
        self.summary.setStyleSheet(f"color:{color};font-weight:700;padding:3px;font-size:13px;")
        if not rows:
            self.result_view.setHtml("<p style='color:#188038'>✓ 没有发现异常；DP 未修改属于正常情况。</p>")
            self.result_view.setFixedHeight(92)
            return
        parts = [
            "<html><body style='font-family:Microsoft YaHei,PingFang SC,sans-serif;font-size:12px'>",
            "<table width='100%' border='1' cellspacing='0' cellpadding='6' style='border-color:#dbe3ed;border-collapse:collapse'>",
            "<thead><tr bgcolor='#edf3f9'>",
            "<th width='12%' align='left'>链接类型</th>",
            "<th width='28%' align='left'>修改前</th>",
            "<th width='28%' align='left'>修改后</th>",
            "<th width='32%' align='left'>说明</th>",
            "</tr></thead><tbody>",
        ]
        for i, f in enumerate(rows):
            label = self._link_type_label(f)
            shade = "#fff" if i % 2 == 0 else "#f8fafc"
            color = STATUS_COLORS[f.status]
            reason = ("正常修改｜" if f.status == "pass" else "需要核对｜") + f.detail
            parts.append(
                f"<tr bgcolor='{shade}'>"
                f"<td valign='top'><b>{self._escaped(label)}</b></td>"
                f"<td valign='top'><span style='color:{color};font-family:Consolas,monospace'>{self._escaped(f.before)}</span></td>"
                f"<td valign='top'><span style='color:{color};font-family:Consolas,monospace'>{self._escaped(f.after)}</span></td>"
                f"<td valign='top'><span style='color:{color}'>{self._escaped(reason)}</span></td>"
                "</tr>"
            )
        parts.append("</tbody></table></body></html>")
        self.result_view.setHtml("".join(parts))
        self.result_view.setFixedHeight(min(320, max(125, 45 + len(rows) * 58)))
        self.result_view.verticalScrollBar().setValue(0)


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    window = LinkCheckerApp()
    window.show()
    sys.exit(app.exec())
