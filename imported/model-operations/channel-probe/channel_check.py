#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude 渠道一致性检测 —— 检查一个 Anthropic Messages API 端点的行为是否与官方一致

零第三方依赖，只用 Python 3 标准库。key 只从命令行参数或环境变量 CHANNEL_API_KEY 读，不打印、不落盘。
检查逻辑逐字来自 jiaoben/2.txt，只适配了本 skill 的传参方式（位置参数 BASE_URL API_KEY、
自动剥 /v1 尾巴、--model 默认 auto）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
七项检查
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ① 签名与内容绑定   8 段不同的 thinking 应产出 8 个不同的签名摘要
                     不同摘要数 / 不同内容数 < 0.80 → 签名不随内容变化

  ② 签名信封形态     thinking 签名是一个 protobuf，官方直连形态为：
                       header f2 平台位缺失、f11 身份位是 36 位 uuid
                     另检查：f6 模型名与请求一致；sonnet-4-6 / opus-4-7 / opus-4-8 /
                     5 代模型的签名应带 f21 签发时间且是刚签发的（不超过 300 秒）

  ③ 签名校验         拿本渠道刚签发的签名，翻转 1 个 bit 后回放、再回放空签名
                       官方：两者都返回 400（Invalid signature）
                       翻转后的签名被 200 接受 → 需复核剥块/转换/复签
                       只有空签名被 200 接受   → 网关在转发前去掉了空签名的 thinking 块

  ④ 图片输入校验     image/tiff、非法 base64、9000x9000 —— 官方全部返回 400

  ⑤ 图片计费公式     image_tokens = ceil(w/28) * ceil(h/28) + 4（claude-sonnet-4-6）
                     1x1/100x100/127x127/200x200/400x400/28x1400 → 5/20/29/68/229/54
                     计费只由像素尺寸决定，与图片格式、压缩率、内容复杂度无关
                       全部为 0          → 图片没有计入 input_tokens
                       各尺寸偏差相同≠0  → 计费口径与官方不同
                       各尺寸恒定 -1     → 另一套 +3 算法，需复核
                       部分尺寸 -1       → 部分请求落到 +3 算法，需复核
                     其它模型的真值未建立，只记录数值不判定

  ⑥ 计费稳定性       同一张 100x100 图重复 N 次（默认 20），input_tokens 应完全相同
                     出现两个值 → 请求被分到了计费口径不同的后端，需复核
                     （个别模型在官方渠道上也出现过 ±1，所以这一项只提示复核）

  ⑦ 响应形态         a) 小请求（无 system、max_tokens=8）与大请求（1 字符 system、
                        max_tokens=32）各发 2 次。官方两者的 id 都是 msg_01… 形态、
                        usage 字段完整；若形态不同 → 按请求大小分流到了不同上游
                     b) 本脚本从不发送 cache_control，usage 里却出现 cache token
                        → 请求在转发前被注入了内容；claude-sonnet-4-6 的纯文本 "hi"
                        应计 8 个 input token

  只记录、不参与判定：usage.iterations 字段、x-new-api-version 等响应头、
  签名里 f14/f17/f22 字段组的有无。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
请求留痕
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  --trace-out 写 JSONL，每条请求一行：检查项、UTC 时间、状态码、x-oneapi-request-id、
  x-request-id、msg_id、input_tokens。计费与预期不符的请求标 odd=true，
  可按 x-oneapi-request-id 在网关日志里查到它走的是哪个上游。不含 key、不含请求体。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
用法
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    python3 channel_check.py https://host sk-... --model claude-sonnet-4-6
    python3 channel_check.py ... --json --trace-out trace.jsonl
    python3 channel_check.py --selftest          # 不需要网络

  也可用原 2.txt 风格：--endpoint https://host + 环境变量 CHANNEL_API_KEY。
  BASE_URL 带 /v1 尾巴会自动剥掉（与 probe_channel.py 一致）。

  --model auto 会按 sonnet-4-6 → opus-4-7 → opus-4-8 → opus-5 → sonnet-5 → fable-5
  的顺序挑第一个可用的模型。图片计费公式只对 claude-sonnet-4-6 校验具体值，建议用它。

  请求量约 52~67 个（预检 1~2 + 签名类 18~33 + 图片 30 + 形态 4），
  除 thinking 请求外都是 max_tokens=8。

退出码：0=全部与官方一致  1=有不一致项  2=错误  3=需复核 / 无法判定 / 渠道不可用
"""

import argparse
import base64
import collections
import concurrent.futures as cf
import hashlib
import json
import math
import os
import re
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib

EXIT_PASS, EXIT_MISMATCH, EXIT_ERROR, EXIT_REVIEW = 0, 1, 2, 3
DEFAULT_TIMEOUT = 90
DEFAULT_RETRIES = 2

DIGEST_MIN_RATIO = 0.80
DIGEST_MIN_CONTENTS = 6
DIGEST_ROUNDS = 8
DIGEST_PROMPTS = [
    "Think briefly, then answer: what is 17*23?",
    "Think briefly, then answer: what is 41*19?",
    "Think briefly, then answer: name three primes above 50.",
    "Think briefly, then answer: how many minutes in 3.5 hours?",
    "Think briefly, then answer: reverse the word 'channel'.",
    "Think briefly, then answer: what is 2^10?",
    "Think briefly, then answer: list two colors of the sky at sunset.",
    "Think briefly, then answer: what is 144/12?",
]

# 这些模型的签名应带 f21 签发时间
F21_REQUIRED_MODELS = ("claude-opus-4-8", "claude-opus-5", "claude-sonnet-5",
                       "claude-sonnet-4-6", "claude-opus-4-7", "claude-fable-5")
MODEL_PROBE_ORDER = ("claude-sonnet-4-6", "claude-opus-4-7", "claude-opus-4-8",
                     "claude-opus-5", "claude-sonnet-5", "claude-fable-5")
CAIS_FIELDS = (1, 3, 7, 8)          # 5.5 代签名格式的字段集
F21_STALE_SECONDS = 300
ISSUANCE_GROUP = {14, 17, 22}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
AWS_ACCOUNT_RE = re.compile(r"^[0-9]{12}$")

IMAGE_PROMPT = "hi"
SIZE_CASES = ((1, 1), (100, 100), (127, 127), (200, 200), (400, 400), (28, 1400))
FORMULA_MODELS = ("claude-sonnet-4-6",)
TEXT_BASE_EXPECTED = {"claude-sonnet-4-6": 8}

# ======================================================================
# 一、protobuf wire format（只读）
# ======================================================================


def _varint(buf, i):
    shift = val = 0
    while True:
        if i >= len(buf) or shift > 63:
            raise ValueError("bad varint")
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not b & 0x80:
            return val, i
        shift += 7


def wire_fields(buf):
    """逐字段扫一层，产出 (field_number, wire_type, value, span)。"""
    out, i, n = [], 0, len(buf)
    while i < n:
        tag, i = _varint(buf, i)
        fn, wt = tag >> 3, tag & 7
        if fn <= 0:
            raise ValueError("bad field number")
        if wt == 0:
            val, j = _varint(buf, i)
            out.append((fn, wt, val, (i, j)))
            i = j
        elif wt == 2:
            ln, j = _varint(buf, i)
            end = j + ln
            if end > n:
                raise ValueError("truncated")
            out.append((fn, wt, memoryview(buf)[j:end], (j, end)))
            i = end
        elif wt == 5:
            out.append((fn, wt, bytes(buf[i:i + 4]), (i, i + 4)))
            i += 4
        elif wt == 1:
            out.append((fn, wt, bytes(buf[i:i + 8]), (i, i + 8)))
            i += 8
        else:
            raise ValueError("unsupported wire type %d" % wt)
    return out


def _first(fields, num, wt):
    for fn, w, val, span in fields:
        if fn == num and w == wt:
            return val, span
    return None, None


def _text(v):
    try:
        return bytes(v).decode("utf-8", "replace") if v is not None else ""
    except Exception:
        return ""


def parse_envelope(sig_b64):
    out = {"parsed": False, "platform": None, "identity": "", "fields": [], "digest": "",
           "model": "", "issued_at": None, "_raw": None, "_digest_abs": None}
    try:
        raw = base64.b64decode(sig_b64, validate=True)
    except Exception:
        try:
            raw = base64.b64decode(sig_b64)
        except Exception:
            return out
    if not raw or len(raw) > 16 * 1024:
        return out
    try:
        inner, ispan = _first(wire_fields(raw), 2, 2)
        if inner is None:
            return out
        inner_off = ispan[1] - len(inner)
        hdr, hspan = _first(wire_fields(inner), 1, 2)
        if hdr is None:
            return out
        hdr_off = inner_off + hspan[1] - len(hdr)
        fields = wire_fields(hdr)
    except ValueError:
        return out
    plat, _ = _first(fields, 2, 0)
    issued, _ = _first(fields, 21, 0)
    ident, _ = _first(fields, 11, 2)
    model, _ = _first(fields, 6, 2)
    digest, dspan = _first(fields, 5, 2)
    out.update({
        "parsed": True, "platform": plat, "identity": _text(ident), "model": _text(model),
        "fields": sorted({fn for fn, _w, _v, _s in fields}), "issued_at": issued,
        "digest": bytes(digest).hex() if digest is not None else "", "_raw": raw,
        "_digest_abs": (hdr_off + dspan[1] - len(digest), hdr_off + dspan[1])
                       if (dspan and digest is not None) else None})
    return out


def tamper_digest(sig_b64):
    """把签名 header 里 f5 摘要翻 1 个 bit，长度不变。"""
    env = parse_envelope(sig_b64)
    raw, span = env.get("_raw"), env.get("_digest_abs")
    if not raw or not span or span[0] >= len(raw):
        return None
    buf = bytearray(raw)
    buf[span[0]] ^= 0x01
    return base64.b64encode(bytes(buf)).decode()


# ======================================================================
# 二、HTTP + 留痕
# ======================================================================

TRACE_HEADERS = ("x-oneapi-request-id", "x-request-id", "request-id")
INFO_HEADERS = ("x-new-api-version",)

_LOCK = threading.Lock()
_REQUESTS = {"n": 0}
_TRACE = []
_USAGES = []
_INFO = collections.defaultdict(set)
_STEP = {"name": ""}


def _step(name):
    _STEP["name"] = name


def _looks_like_api(raw):
    s = raw.lstrip()
    if s.startswith("event:") or s.startswith("data:"):
        return True
    try:
        doc = json.loads(s)
    except Exception:
        return False
    return isinstance(doc, dict) and doc.get("type") == "message"


def _hdrs(obj):
    try:
        return {k.lower(): v for k, v in obj.items()}
    except Exception:
        return {}


def _record(resp, body):
    msg_id, usage = "", None
    try:
        doc = json.loads(resp.get("raw") or "")
        if isinstance(doc, dict) and doc.get("type") == "message":
            msg_id, usage = doc.get("id") or "", doc.get("usage") or {}
    except Exception:
        pass
    hdr = resp.get("headers") or {}
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "step": _STEP["name"],
             "model": body.get("model"), "status": resp.get("status"), "msg_id": msg_id,
             "input_tokens": (usage or {}).get("input_tokens")}
    for h in TRACE_HEADERS:
        entry[h] = hdr.get(h, "")
    with _LOCK:
        _TRACE.append(entry)
        if usage is not None and resp.get("status") == 200:
            _USAGES.append(usage)
        for h in INFO_HEADERS:
            if hdr.get(h):
                _INFO[h].add(hdr[h][:80])
    return entry


def _post(endpoint, api_key, body, timeout, retries, auth="x-api-key"):
    """4xx 不重试、5xx/429 重试；200 但不是 Messages API 响应记为 -2。"""
    with _LOCK:
        _REQUESTS["n"] += 1
    url = endpoint.rstrip("/") + "/v1/messages"
    headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
    if auth == "bearer":
        headers["Authorization"] = "Bearer " + api_key
    else:
        headers["x-api-key"] = api_key
    data = json.dumps(body).encode()
    resp = None
    for attempt in range(max(1, retries)):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                h = _hdrs(r.headers)
                if r.status == 200 and not _looks_like_api(raw):
                    resp = {"status": -2, "raw": "non-API 200 response: " + raw[:120], "headers": h}
                else:
                    resp = {"status": r.status, "raw": raw, "headers": h}
                break
        except urllib.error.HTTPError as exc:
            resp = {"status": exc.code, "raw": exc.read().decode("utf-8", "replace"),
                    "headers": _hdrs(exc.headers or {})}
            if exc.code < 500 and exc.code != 429:
                break
        except Exception as exc:
            resp = {"status": -1, "raw": "%s: %s" % (type(exc).__name__, exc), "headers": {}}
        if attempt + 1 < max(1, retries):
            time.sleep(1.5 * (attempt + 1))
    resp = resp or {"status": -1, "raw": "no response", "headers": {}}
    resp["_trace"] = _record(resp, body)
    return resp


def _input_tokens(resp):
    if resp["status"] != 200:
        return None
    try:
        return (json.loads(resp["raw"]).get("usage") or {}).get("input_tokens")
    except Exception:
        return None


def _thinking_block(raw):
    """取第一段 thinking（兼容 JSON 与 SSE）。"""
    doc = None
    try:
        doc = json.loads(raw)
    except Exception:
        blocks = []
        for line in raw.splitlines():
            if not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except Exception:
                continue
            if ev.get("type") == "message_start":
                doc = ev.get("message") or {}
            elif ev.get("type") == "content_block_start":
                blocks.append(ev.get("content_block") or {})
        if doc is not None and not doc.get("content"):
            doc = dict(doc, content=blocks)
    if not isinstance(doc, dict):
        return None
    for block in doc.get("content") or []:
        if block.get("type") == "thinking" and block.get("signature"):
            return {"signature": block["signature"], "thinking": block.get("thinking") or ""}
    return None


THINK_BODY = {"max_tokens": 2000, "messages": [{"role": "user", "content": "Think briefly: 3*7=?"}]}
THINK_SHAPES = ({"type": "enabled", "budget_tokens": 1024}, {"type": "adaptive"})


def _think(endpoint, key, model, timeout, retries, auth, errors, body=None):
    for shape in THINK_SHAPES:
        b = dict(body or THINK_BODY, model=model, thinking=shape)
        resp = _post(endpoint, key, b, timeout, retries, auth)
        if resp["status"] != 200:
            errors.append("HTTP%s" % resp["status"])
            continue
        block = _thinking_block(resp["raw"])
        if block:
            return block
        errors.append("no-thinking")
    return None


def resolve_model(endpoint, key, timeout, retries, auth):
    tried = []
    for m in MODEL_PROBE_ORDER:
        r = _post(endpoint, key, {"model": m, "max_tokens": 8,
                                  "messages": [{"role": "user", "content": "hi"}]}, timeout, retries, auth)
        tried.append("%s=HTTP%s" % (m, r["status"]))
        if r["status"] == 200:
            return m, tried
    return None, tried


# ======================================================================
# 三、① 签名与内容绑定 / ② 信封 / ③ 签名校验
# ======================================================================

def probe_digest(endpoint, key, model, timeout, retries, auth):
    rows, errors = [], []
    for idx in range(DIGEST_ROUNDS):
        body = {"max_tokens": 2600, "messages": [{"role": "user", "content": DIGEST_PROMPTS[idx]}]}
        block = _think(endpoint, key, model, timeout, retries, auth, errors, body)
        if not block:
            continue
        env = parse_envelope(block["signature"])
        if not env["parsed"] or not env["digest"]:
            errors.append("bad-envelope")
            continue
        rows.append({"digest": env["digest"],
                     "content": hashlib.sha256(block["thinking"].encode()).hexdigest()[:16]
                                if block["thinking"] else "prompt#%d" % idx})
    contents, digests = {r["content"] for r in rows}, {r["digest"] for r in rows}
    out = {"samples": len(rows), "contents": len(contents), "digests": len(digests),
           "error_kinds": sorted(set(errors))}
    if len(contents) < DIGEST_MIN_CONTENTS:
        return dict(out, verdict="inconclusive",
                    reason="可用样本不足（%d 个不同内容，需 >= %d）；失败原因：%s"
                           % (len(contents), DIGEST_MIN_CONTENTS, "、".join(out["error_kinds"]) or "未知"))
    ratio = len(digests) / float(len(contents))
    out["ratio"] = ratio
    if ratio < DIGEST_MIN_RATIO:
        return dict(out, verdict="signature_pool",
                    reason="%d 个不同内容只产出 %d 个不同签名摘要（%.2f < %.2f）—— 签名不随内容变化"
                           % (len(contents), len(digests), ratio, DIGEST_MIN_RATIO))
    return dict(out, verdict="content_bound",
                reason="%d 个不同内容产出 %d 个不同签名摘要（%.2f）" % (len(contents), len(digests), ratio))


def envelope_form(rec):
    f = set(rec["fields"])
    if f and f <= set(CAIS_FIELDS):
        return "cais"
    if rec["platform"] == 1 and AWS_ACCOUNT_RE.match(rec["identity"] or ""):
        return "bedrock"
    if rec["platform"] is None and UUID_RE.match(rec["identity"] or ""):
        return "first_party"
    return "odd"


def judge_envelope(recs, model, errors=()):
    forms = [envelope_form(r) for r in recs]
    kinds, n = set(forms), len(recs)
    f21_required = (model or "").startswith(F21_REQUIRED_MODELS)
    issued = [r["issued_delta"] for r in recs if r.get("issued_delta") is not None]
    mismatch = sorted({"%s!=%s" % (r["model"], model) for r in recs
                       if r.get("model") and model and r["model"] != model})
    fp = [r for r, f in zip(recs, forms) if f == "first_party"]
    with_group = sum(1 for r in fp if ISSUANCE_GROUP <= set(r["fields"]))
    group = ("unknown" if not fp else "present" if with_group == len(fp)
             else "absent" if with_group == 0 else "mixed")
    out = {"samples": n, "forms": forms, "f21_present": len(issued), "f21_deltas": issued,
           "model_mismatch": mismatch, "error_kinds": sorted(set(errors)),
           "fieldsets": sorted({tuple(r["fields"]) for r in recs}), "f14_f17_f22": group}
    if not n:
        return dict(out, verdict="inconclusive",
                    reason="拿不到可解析的签名；失败原因：%s" % ("、".join(out["error_kinds"]) or "未知"))
    if kinds == {"bedrock"}:
        v, why = "bedrock_form", "%d/%d 条签名是 AWS Bedrock 形态（f2=1 + 12 位账号），不是官方直连" % (n, n)
    elif "bedrock" in kinds:
        v, why = "mixed_form", "签名形态混用 %s —— 后面不止一个来源" % dict(collections.Counter(forms))
    elif mismatch:
        v, why = "model_mismatch", "签名里的模型与请求不符：%s" % "、".join(mismatch[:3])
    elif "cais" in kinds and f21_required:
        v, why = "cross_generation", "请求 %s 却返回 5.5 代格式的签名" % model
    elif kinds == {"cais"}:
        v, why = "cais_form", "5.5 代格式签名，该代际本就没有平台位/身份/f21"
    elif "odd" in kinds:
        v, why = "odd_form", "出现未知的签名形态 %s，不下结论" % dict(collections.Counter(forms))
    elif f21_required and len(issued) < n * 0.5:
        v, why = "missing_f21", "%s 的签名应带 f21 签发时间，这里 %d/%d 条没有" % (model, n - len(issued), n)
    elif any(d > F21_STALE_SECONDS for d in issued):
        v, why = "stale_signature", "签名签发自 %d 秒前（> %d）—— 不是本次请求签发的" % (max(issued), F21_STALE_SECONDS)
    else:
        v, why = "first_party_form", "%d/%d 条签名是官方直连形态（f2 缺失 + uuid）" % (n, n)
        if f21_required:
            why += "，f21 %d/%d" % (len(issued), n)
    return dict(out, verdict=v, reason=why)


def probe_envelope(endpoint, key, model, samples, timeout, retries, auth):
    recs, errors = [], []
    for _ in range(samples):
        sent = int(time.time())
        block = _think(endpoint, key, model, timeout, retries, auth, errors)
        if not block:
            continue
        env = parse_envelope(block["signature"])
        if not env["parsed"]:
            errors.append("bad-envelope")
            continue
        recs.append({"fields": env["fields"], "platform": env["platform"], "identity": env["identity"],
                     "model": (env.get("model") or "").strip(),
                     "issued_delta": env["issued_at"] - sent if env["issued_at"] else None})
    return judge_envelope(recs, model, errors)


def judge_replay(control, tampered, empty):
    """三个参数都是 (status, raw)。"""
    def rejected(s):
        return s[0] in (400, 422) and "signature" in (s[1] or "").lower()
    out = {"control_status": control[0], "tampered_status": tampered[0], "empty_status": empty[0]}
    if tampered[0] == 200:
        return dict(out, verdict="not_verified",
                    reason="翻转 1 bit 的签名被 200 接受%s —— 未观察到拒绝，需复核剥块/转换/复签"
                           % ("（空签名也被接受）" if empty[0] == 200 else ""))
    if control[0] != 200 or not rejected(tampered):
        return dict(out, verdict="inconclusive",
                    reason="回放结果不完整（原签名=%s 翻转=%s 空签名=%s）" % (control[0], tampered[0], empty[0]))
    if empty[0] == 200:
        return dict(out, verdict="strips_empty",
                    reason="翻转的签名被拒，但空签名被 200 接受 —— 可能剥块或转换，需复核")
    note = "" if rejected(empty) else "（空签名返回 %s、报错没提 signature，但没被接受）" % empty[0]
    return dict(out, verdict="verified", reason="同渠道原签名通过，翻转的签名被拒%s；未独立验签，不能排除复签" % note)


def probe_replay(endpoint, key, model, timeout, retries, auth):
    errors = []
    block = _think(endpoint, key, model, timeout, retries, auth, errors)
    if not block:
        return {"verdict": "inconclusive", "reason": "拿不到本渠道签发的签名（%s）" % "、".join(errors)}
    tampered = tamper_digest(block["signature"])
    if not tampered:
        return {"verdict": "inconclusive", "reason": "签名里没有可翻转的摘要字段"}

    def replay(sig):
        body = {"model": model, "max_tokens": 256, "messages": [
            {"role": "user", "content": "Think briefly: 3*7=?"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": block["thinking"], "signature": sig},
                {"type": "text", "text": "21"}]},
            {"role": "user", "content": "And 4*8?"}]}
        r = _post(endpoint, key, body, timeout, retries, auth)
        return r["status"], r["raw"]

    return judge_replay(replay(block["signature"]), replay(tampered), replay(""))


# ======================================================================
# 四、④ 图片输入校验 / ⑤ 计费公式 / ⑥ 稳定性
# ======================================================================

def _png(w, h, rgb=(255, 0, 0)):
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = (b"\x00" + bytes(rgb) * w) * h
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _tiff():
    ifd = struct.pack("<H", 1) + struct.pack("<HHII", 256, 3, 1, 1) + struct.pack("<I", 0)
    return b"II*\x00" + struct.pack("<I", 8) + ifd


def _image_body(model, data_b64, media_type="image/png"):
    return {"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data_b64}},
        {"type": "text", "text": IMAGE_PROMPT}]}]}


def probe_image_validation(endpoint, key, model, timeout, retries, auth):
    cases = (("tiff", _image_body(model, base64.b64encode(_tiff()).decode(), "image/tiff")),
             ("bad_base64", _image_body(model, "!!!notbase64!!!")),
             ("oversize", _image_body(model, base64.b64encode(_png(9000, 9000)).decode())))
    st = {name: _post(endpoint, key, body, timeout, retries, auth)["status"] for name, body in cases}
    out = {"statuses": st}
    accepted = sorted(k for k, v in st.items() if v == 200)
    if accepted:
        return dict(out, verdict="accepts_invalid", reason="官方必拒的图片输入被 200 接受：%s" % "、".join(accepted))
    if all(v in (400, 422) for v in st.values()):
        return dict(out, verdict="rejects_invalid", reason="tiff / 非法 base64 / 9000x9000 全部被拒")
    return dict(out, verdict="inconclusive", reason="状态码不符合预期：%s" % st)


def expected_image_tokens(w, h):
    return math.ceil(w / 28.0) * math.ceil(h / 28.0) + 4


def _size_key(w, h):
    return "%dx%d" % (w, h)


def judge_sizes(model, deltas):
    got = {k: v for k, v in deltas.items() if v is not None}
    exp = {k: expected_image_tokens(*map(int, k.split("x"))) for k in got}
    offsets = {k: got[k] - exp[k] for k in got}
    out = {"deltas": deltas, "expected": exp, "offsets": offsets}
    if len(got) < 4:
        return dict(out, verdict="inconclusive", reason="只有 %d 个尺寸取到样本（至少 4 个）" % len(got))
    if all(v == 0 for v in got.values()):
        return dict(out, verdict="no_image_billing", reason="%d 个尺寸的图片 token 全部为 0 —— 图片没有计入" % len(got))
    if model not in FORMULA_MODELS:
        return dict(out, verdict="unverified", reason="%s 的图片真值未建立，只记录：%s" % (model, got))
    distinct = set(offsets.values())
    if distinct == {0}:
        return dict(out, verdict="formula_ok", reason="%d 个尺寸全部等于 ceil(w/28)*ceil(h/28)+4" % len(got))
    if distinct == {-1}:
        return dict(out, verdict="alt_formula", reason="每个尺寸都少 1（+3 算法），与官方 +4 不同，需复核")
    if len(distinct) == 1:
        return dict(out, verdict="constant_offset", reason="每个尺寸都偏 %+d —— 计费口径与官方不同" % distinct.pop())
    if distinct <= {0, -1}:
        bad = sorted(k for k, v in offsets.items() if v)
        return dict(out, verdict="partial_drift", reason="%s 少 1，其余正确 —— 部分请求落到 +3 算法，需复核" % "、".join(bad))
    return dict(out, verdict="wrong_formula", reason="与公式不符，偏差 %s" % offsets)


def probe_sizes(endpoint, key, model, timeout, retries, auth):
    base = _input_tokens(_post(endpoint, key, {"model": model, "max_tokens": 8,
                                               "messages": [{"role": "user", "content": IMAGE_PROMPT}]},
                               timeout, retries, auth))
    if base is None:
        return {"verdict": "inconclusive", "reason": "纯文本基线请求失败"}, None
    deltas, entries = {}, {}
    for w, h in SIZE_CASES:
        r = _post(endpoint, key, _image_body(model, base64.b64encode(_png(w, h)).decode()), timeout, retries, auth)
        tok = _input_tokens(r)
        deltas[_size_key(w, h)] = None if tok is None else tok - base
        entries[_size_key(w, h)] = r["_trace"]
    out = judge_sizes(model, deltas)
    if model in FORMULA_MODELS:
        for k, off in out.get("offsets", {}).items():
            if off:
                entries[k]["odd"] = True
    out["base_tokens"] = base
    return out, base


def judge_stability(values):
    vals = [v for v in values if v is not None]
    out = {"values": dict(collections.Counter(vals)), "samples": len(vals)}
    if len(vals) < 5:
        return dict(out, verdict="inconclusive", reason="可用样本只有 %d 次" % len(vals))
    if len(set(vals)) > 1:
        return dict(out, verdict="unstable", reason="同一张 100x100 图 %d 次得到 %s，需复核" % (len(vals), out["values"]))
    return dict(out, verdict="stable", reason="%d 次全部为 %d" % (len(vals), vals[0]))


def probe_stability(endpoint, key, model, repeats, timeout, retries, auth):
    body = _image_body(model, base64.b64encode(_png(100, 100)).decode())
    with cf.ThreadPoolExecutor(2) as ex:
        resps = list(ex.map(lambda _: _post(endpoint, key, body, timeout, retries, auth), range(repeats)))
    out = judge_stability([_input_tokens(r) for r in resps])
    if out["verdict"] == "unstable":
        mode = max(out["values"], key=out["values"].get)
        for r in resps:
            tok = _input_tokens(r)
            if tok is not None and tok != mode:
                r["_trace"]["odd"] = True
    return out


# ======================================================================
# 五、⑦ 响应形态 / usage
# ======================================================================

def id_shape(msg_id):
    if re.match(r"^msg_[0-9a-f]{32}$", msg_id or ""):
        return "hex32"
    if (msg_id or "").startswith("msg_bdrk_"):
        return "bdrk"
    if re.match(r"^msg_01[0-9A-Za-z]{20,}$", msg_id or ""):
        return "base62"
    return "other" if msg_id else "none"


def judge_shape(recs):
    small = [r for r in recs if r["kind"] == "small"]
    big = [r for r in recs if r["kind"] == "big"]
    out = {"small": [(r["id_shape"], len(r["usage_keys"])) for r in small],
           "big": [(r["id_shape"], len(r["usage_keys"])) for r in big]}
    if not small or not big:
        return dict(out, verdict="inconclusive", reason="小/大请求有一侧没拿到 200")
    s_shapes, b_shapes = {r["id_shape"] for r in small}, {r["id_shape"] for r in big}
    trimmed = any(len(r["usage_keys"]) <= 2 for r in small) and all(len(r["usage_keys"]) > 2 for r in big)
    if s_shapes != b_shapes or trimmed:
        return dict(out, verdict="split_by_size",
                    reason="小请求 id=%s、大请求 id=%s%s —— 按请求大小分流到了不同上游"
                           % (sorted(s_shapes), sorted(b_shapes), "，小请求 usage 字段被裁剪" if trimmed else ""))
    if s_shapes == {"base62"}:
        return dict(out, verdict="standard_ids", reason="大小请求都是 msg_01… 形态，usage 完整")
    return dict(out, verdict="nonstandard_ids", reason="msg id 形态 %s，不是官方的 msg_01…" % sorted(s_shapes))


def probe_shape(endpoint, key, model, timeout, retries, auth):
    bodies = {"small": {"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]},
              "big": {"model": model, "max_tokens": 32, "system": ".",
                      "messages": [{"role": "user", "content": "hi"}]}}
    recs = []
    for _ in range(2):
        for kind, body in bodies.items():
            r = _post(endpoint, key, body, timeout, retries, auth)
            if r["status"] != 200:
                continue
            try:
                doc = json.loads(r["raw"])
            except Exception:
                continue
            recs.append({"kind": kind, "id_shape": id_shape(doc.get("id")),
                         "usage_keys": sorted((doc.get("usage") or {}).keys())})
    return judge_shape(recs)


def judge_usage(usages, model, base_text):
    out = {"samples": len(usages), "iterations_seen": sum(1 for u in usages if "iterations" in u),
           "base_text_tokens": base_text}
    if not usages:
        return dict(out, verdict="inconclusive", reason="没有可用的 usage")
    flags = []
    cached = [u for u in usages if (u.get("cache_creation_input_tokens") or 0) > 0
              or (u.get("cache_read_input_tokens") or 0) > 0]
    if cached:
        top = max(max(u.get("cache_creation_input_tokens") or 0, u.get("cache_read_input_tokens") or 0)
                  for u in cached)
        flags.append("请求不带 cache_control，却有 %d/%d 条响应计了 cache token（最大 %d）—— 转发前被注入了内容"
                     % (len(cached), len(usages), top))
    exp = TEXT_BASE_EXPECTED.get(model)
    if exp is not None and base_text is not None and base_text != exp:
        flags.append("纯文本 \"hi\" 计 %d 个 input token（官方 %d）" % (base_text, exp))
    if flags:
        return dict(out, verdict="usage_modified", reason="；".join(flags))
    return dict(out, verdict="usage_ok", reason="未见注入内容或文本计数异常")


# ======================================================================
# 六、合成
# ======================================================================

MISMATCH_VERDICTS = ("signature_pool", "not_first_party", "model_mismatch", "missing_f21",
                     "stale_signature", "signature_not_verified", "request_or_billing_modified")
LABELS = {"pass": "已测项目符合内置参考", "signature_pool": "发现重复签名摘要",
          "not_first_party": "签名不是官方直连形态", "model_mismatch": "签名模型与请求不符",
          "missing_f21": "签名缺签发时间 / 代际不符", "stale_signature": "签名不是本次签发的",
          "signature_not_verified": "篡改签名未被拒绝，需复核",
          "request_or_billing_modified": "请求或计费与官方不一致",
          "review": "需复核", "inconclusive": "无法判定", "unavailable": "渠道不可用"}


def classify(s):
    v = {k: (s.get(k) or {}).get("verdict") for k in
         ("digest", "envelope", "replay", "image_validation", "sizes", "stability", "shape", "usage")}
    why = lambda k: (s.get(k) or {}).get("reason", "")
    if v["digest"] == "signature_pool":
        return "signature_pool", why("digest")
    if v["envelope"] in ("bedrock_form", "mixed_form"):
        return "not_first_party", why("envelope")
    if v["envelope"] == "model_mismatch":
        return "model_mismatch", why("envelope")
    if v["envelope"] in ("missing_f21", "cross_generation"):
        return "missing_f21", why("envelope")
    if v["envelope"] == "stale_signature":
        return "stale_signature", why("envelope")
    if v["replay"] == "not_verified":
        return "signature_not_verified", why("replay")
    mod = []
    if v["image_validation"] == "accepts_invalid":
        mod.append(why("image_validation"))
    if v["sizes"] in ("no_image_billing", "constant_offset", "wrong_formula"):
        mod.append(why("sizes"))
    if v["usage"] == "usage_modified":
        mod.append(why("usage"))
    if mod:
        return "request_or_billing_modified", "；".join(mod)
    rev = [why(k) for k, bad in (("replay", "strips_empty"), ("stability", "unstable"),
                                 ("sizes", "partial_drift"), ("sizes", "alt_formula"),
                                 ("shape", "split_by_size"), ("shape", "nonstandard_ids")) if v[k] == bad]
    if rev:
        return "review", "；".join(rev)
    need = {"digest": ("content_bound",), "envelope": ("first_party_form", "cais_form"),
            "replay": ("verified",), "image_validation": ("rejects_invalid",),
            "sizes": ("formula_ok", "unverified"), "stability": ("stable",),
            "shape": ("standard_ids",), "usage": ("usage_ok",)}
    missing = [k for k, ok in need.items() if v[k] not in ok]
    if missing:
        return "inconclusive", "这些检查没出结论：%s" % "、".join("%s=%s" % (k, v[k]) for k in missing)
    note = "（图片公式未校验：该模型真值未建立）" if v["sizes"] == "unverified" else ""
    return "pass", "七项检查符合内置参考；未独立验证生成来源，不能排除复签" + note


# ======================================================================
# 七、自检（不需要网络）
# ======================================================================

def _varint_bytes(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | 0x80 if v else b)
        if not v:
            return bytes(out)


def _fld(fn, wt, payload):
    if wt == 0:
        return _varint_bytes(fn << 3) + _varint_bytes(payload)
    return _varint_bytes((fn << 3) | 2) + _varint_bytes(len(payload)) + payload


def _build_envelope(platform, identity):
    hdr = (_fld(2, 0, platform) if platform is not None else b"") + _fld(5, 2, bytes(range(64)))
    hdr += _fld(6, 2, b"claude-test") + _fld(8, 2, b"thinking") + _fld(11, 2, identity)
    return base64.b64encode(_fld(2, 2, _fld(1, 2, hdr))).decode()


def run_selftest():
    ok = [True]

    def check(name, cond):
        print("  %-44s %s" % (name, "OK" if cond else "FAIL"))
        ok[0] = ok[0] and bool(cond)

    fp_sig = _build_envelope(None, b"5a70736a-dba5-474b-a996-112a6aa90e22")
    br_sig = _build_envelope(1, b"123456789012")
    check("解析: 官方形态 f2 缺失 + uuid", envelope_form(parse_envelope(fp_sig)) == "first_party")
    check("解析: Bedrock 形态 f2=1 + 账号", envelope_form(parse_envelope(br_sig)) == "bedrock")
    t = tamper_digest(fp_sig)
    check("翻转: 长度不变且只差 1 字节",
          t and sum(a != b for a, b in zip(base64.b64decode(t), base64.b64decode(fp_sig))) == 1)
    check("API 响应: HTML 不算", not _looks_like_api("<html></html>"))

    off = lambda vals: {_size_key(w, h): v for (w, h), v in zip(SIZE_CASES, vals)}
    S = "claude-sonnet-4-6"
    check("公式: 5/20/29/68/229/54 → formula_ok", judge_sizes(S, off([5, 20, 29, 68, 229, 54]))["verdict"] == "formula_ok")
    check("公式: 恒定 -3 → constant_offset", judge_sizes(S, off([2, 17, 26, 65, 226, 51]))["verdict"] == "constant_offset")
    check("公式: 恒定 -1 → alt_formula", judge_sizes(S, off([4, 19, 28, 67, 228, 53]))["verdict"] == "alt_formula")
    check("公式: 部分 -1 → partial_drift", judge_sizes(S, off([5, 19, 29, 67, 228, 53]))["verdict"] == "partial_drift")
    check("公式: 全 0 → no_image_billing", judge_sizes(S, off([0] * 6))["verdict"] == "no_image_billing")

    sig = (400, "Invalid signature in thinking block")
    check("回放: 200/200/200 → not_verified", judge_replay((200, ""), (200, ""), (200, ""))["verdict"] == "not_verified")
    check("回放: 200/400/200 → strips_empty", judge_replay((200, ""), sig, (200, ""))["verdict"] == "strips_empty")
    check("回放: 200/400/400 → verified", judge_replay((200, ""), sig, sig)["verdict"] == "verified")

    check("id: hex32", id_shape("msg_d0f2936c69e44dbe9583d763d6b83dd8") == "hex32")
    check("id: base62", id_shape("msg_011CgreEGc4aySPvW5MRZ7oP") == "base62")
    full = ["cache_creation_input_tokens", "cache_read_input_tokens", "input_tokens", "output_tokens"]
    split = [{"kind": "small", "id_shape": "hex32", "usage_keys": ["input_tokens", "output_tokens"]},
             {"kind": "big", "id_shape": "base62", "usage_keys": full}]
    check("形态: 按大小分流 → split_by_size", judge_shape(split)["verdict"] == "split_by_size")
    check("usage: 注入 cache → usage_modified",
          judge_usage([{"input_tokens": 3, "cache_read_input_tokens": 6400}], S, 3)["verdict"] == "usage_modified")
    check("usage: 正常 → usage_ok", judge_usage([{"input_tokens": 8}], S, 8)["verdict"] == "usage_ok")

    rec = lambda s, m="claude-test", d=2: dict(parse_envelope(s), issued_delta=d, model=m)
    check("信封: 官方 → first_party_form", judge_envelope([rec(fp_sig)] * 3, "claude-test")["verdict"] == "first_party_form")
    check("信封: 混用 → mixed_form", judge_envelope([rec(fp_sig), rec(br_sig)], "claude-test")["verdict"] == "mixed_form")

    good = {"digest": "content_bound", "envelope": "first_party_form", "replay": "verified",
            "image_validation": "rejects_invalid", "sizes": "formula_ok", "stability": "stable",
            "shape": "standard_ids", "usage": "usage_ok"}
    c = lambda **kw: classify({k: {"verdict": v, "reason": v} for k, v in dict(good, **kw).items()})[0]
    check("合成: 全过 → pass", c() == "pass")
    check("合成: 未校验签名 → signature_not_verified", c(replay="not_verified") == "signature_not_verified")
    check("合成: 计费偏移 → request_or_billing_modified", c(sizes="constant_offset") == "request_or_billing_modified")
    check("合成: 稳定性波动 → review", c(stability="unstable") == "review")
    check("合成: 某项无结论 → inconclusive", c(digest="inconclusive") == "inconclusive")
    print("\nSELFTEST %s" % ("OK" if ok[0] else "FAILED"))
    return 0 if ok[0] else 1


# ======================================================================
# 八、入口（适配 skill 传参：位置参数 BASE_URL API_KEY，兼容 --endpoint + 环境变量）
# ======================================================================

STEP_LINES = (("digest", "① 签名绑定"), ("envelope", "② 签名形态"), ("replay", "③ 签名校验"),
              ("image_validation", "④ 图片校验"), ("sizes", "⑤ 图片计费"),
              ("stability", "⑥ 计费稳定"), ("shape", "⑦ 响应形态"), ("usage", "⑦ usage"))


def run(args, key):
    a, t, r, au = (args.endpoint, key), args.timeout, args.retries, args.auth
    if args.model == "auto":
        _step("resolve_model")
        picked, tried = resolve_model(*a, t, r, au)
        if not picked:
            return {"endpoint": args.endpoint, "model": "auto", "verdict": "unavailable",
                    "reason": "候选模型全部不可用：%s" % "、".join(tried), "requests": _REQUESTS["n"],
                    "elapsed_sec": 0, "info_headers": {}, "odd_requests": [], "steps": {}}
        args.model = picked
    m = args.model
    _step("preflight")
    for attempt in range(2):
        pre = _post(*a, {"model": m, "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]}, t, r, au)
        if pre["status"] == 200:
            break
        if attempt == 0:
            time.sleep(5)
    else:
        return {"endpoint": args.endpoint, "model": m, "verdict": "unavailable",
                "reason": "预检 2 次都失败（HTTP%s）：%s" % (pre["status"], pre["raw"][:200]),
                "requests": _REQUESTS["n"], "elapsed_sec": 0, "info_headers": {}, "odd_requests": [],
                "steps": {}}
    t0 = time.time()
    steps = {}
    _step("digest")
    steps["digest"] = probe_digest(*a, m, t, r, au)
    _step("envelope")
    steps["envelope"] = probe_envelope(*a, m, args.envelope_samples, t, r, au)
    _step("replay")
    steps["replay"] = probe_replay(*a, m, t, r, au)
    _step("image_validation")
    steps["image_validation"] = probe_image_validation(*a, m, t, r, au)
    _step("sizes")
    steps["sizes"], base = probe_sizes(*a, m, t, r, au)
    _step("stability")
    steps["stability"] = probe_stability(*a, m, args.repeats, t, r, au)
    _step("shape")
    steps["shape"] = probe_shape(*a, m, t, r, au)
    steps["usage"] = judge_usage(list(_USAGES), m, base)
    verdict, reason = classify(steps)
    return {"endpoint": args.endpoint, "model": m, "verdict": verdict, "reason": reason,
            "elapsed_sec": round(time.time() - t0, 1), "requests": _REQUESTS["n"],
            "info_headers": {k: sorted(v) for k, v in _INFO.items()},
            "odd_requests": [e for e in _TRACE if e.get("odd")], "steps": steps}


def _normalize_endpoint(ep):
    """与 probe_channel.py 的 urls() 一致：剥掉结尾的 /v1。"""
    ep = (ep or "").rstrip("/")
    if ep.endswith("/v1"):
        ep = ep[:-3]
    return ep.rstrip("/")


def main(argv):
    ap = argparse.ArgumentParser(description="Claude 渠道一致性检测（官方行为对照）")
    ap.add_argument("base_url", nargs="?", default="", help="如 https://host（不带 /v1/messages；带 /v1 也能自动剥）")
    ap.add_argument("api_key", nargs="?", default="", help="key 只从这里或环境变量 CHANNEL_API_KEY 读，不打印、不落盘")
    ap.add_argument("--endpoint", default="", help="等价于 base_url（原 2.txt 风格）")
    ap.add_argument("--model", default="auto", help="建议 claude-sonnet-4-6；auto 自动挑可用模型")
    ap.add_argument("--repeats", type=int, default=20, help="⑥ 计费稳定性的重复次数")
    ap.add_argument("--envelope-samples", type=int, default=6)
    ap.add_argument("--auth", choices=("x-api-key", "bearer"), default="x-api-key")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--trace-out", default="", help="每条请求一行 JSONL（含请求 ID，不含 key）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return run_selftest()
    endpoint = _normalize_endpoint(args.endpoint or args.base_url)
    key = args.api_key or os.environ.get("CHANNEL_API_KEY", "")
    if not endpoint:
        sys.stderr.write("ERROR: 需要 BASE_URL（或 --endpoint）和 key（参数或 CHANNEL_API_KEY）\n")
        return EXIT_ERROR
    if not key:
        sys.stderr.write("ERROR: 缺 key —— 传 API_KEY 参数，或先 export CHANNEL_API_KEY=<key>\n")
        return EXIT_ERROR
    args.endpoint = endpoint

    result = run(args, key)
    if args.trace_out:
        fd = os.open(args.trace_out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in _TRACE))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("端点: %s   模型: %s\n" % (result["endpoint"], result["model"]))
        for k, label in STEP_LINES:
            st = result["steps"].get(k)
            if st:
                print("%-10s %-24s %s" % (label, st.get("verdict"), st.get("reason", "")))
        for e in result["odd_requests"]:
            print("  计费异常请求 %s %s %s input_tokens=%s x-oneapi-request-id=%s msg_id=%s"
                  % (e["ts"], e["step"], e["model"], e["input_tokens"],
                     e.get("x-oneapi-request-id") or "-", e["msg_id"] or "-"))
        print("\n结论: %s —— %s" % (LABELS.get(result["verdict"], result["verdict"]), result["reason"]))
        print("耗时: %.1fs   请求数: %d" % (result["elapsed_sec"], result["requests"]))
    if result["verdict"] == "pass":
        return EXIT_PASS
    if result["verdict"] in MISMATCH_VERDICTS:
        return EXIT_MISMATCH
    return EXIT_REVIEW


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
