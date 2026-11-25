#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_channel.py — Claude 中转渠道体检 + 上游形态判定（CCMax 池 / 官转 API / AWSB·Bedrock）

签名判定核心复用上层目录的 probe_thinking_signature.py（子进程调用，不重写解码逻辑）：
  1) 优先用它自带的 CLI 探测模式（thinking.type=enabled）
  2) 新代模型拒绝 enabled 时，本脚本改发 adaptive 请求拿签名，再调它 --decode-file 解码

阶段与成本（默认只跑便宜的 0/1，其余需显式开关）:
  0 体检      模型列表 + 逐模型连通性
  1 签名判定  平台位/身份位/message_id → AWSB vs first-party          [--deep 前最多每模型1-2次请求]
  2 回传检查  thinking 签名多轮回传 → 观察同渠道接受行为                [--deep]
  3 参数指纹  temperature/tool_choice/top_k/stop_sequences/system    [--deep]
  4 分词器对照 同文本跨模型数 token → 排除上游注入                    [--deep]
  5 1M 上下文 ~210k tokens 裸发(不带 context-1m beta 头)             [--big-context 模型名, 烧token]
  6 撞限流    RPM 突发 + TPM 推压 → 看有没有官转式墙                  [--load, 需用户明确授权]
  7 官方一致性 签名绑定/形态/验签 + 图片校验/计费公式/稳定性 + 响应形态 [--consistency [模型]]
              子进程调用 skill/channel_check.py（移植自 jiaoben/2.txt，~52-67 个请求）
  8 Gemini 真伪 9 个行为探针（角色白名单/protobuf 枚举/thinkingBudget/信封字段等） [--gemini [模型]]
              子进程调用 skill/gemini_verify.mjs（移植自 jiaoben/gemini-verify.mjs，需 node 18+）

用法:
  python3 probe_channel.py BASE_URL API_KEY
  python3 probe_channel.py BASE_URL API_KEY --models claude-opus-4-6,claude-sonnet-5
  python3 probe_channel.py BASE_URL API_KEY --deep
  python3 probe_channel.py BASE_URL API_KEY --deep --big-context claude-opus-4-6
  python3 probe_channel.py BASE_URL API_KEY --deep --load
  python3 probe_channel.py BASE_URL API_KEY --consistency            # +阶段7 官方一致性
  python3 probe_channel.py BASE_URL API_KEY --gemini                # +阶段8 Gemini 真伪核验
  python3 probe_channel.py BASE_URL API_KEY --deep --consistency claude-sonnet-4-6 --gemini gemini-4-argon
  （纯 Gemini 渠道：Claude 侧全不通时 --gemini 仍会单独完成核验；或直接跑
   node skill/gemini_verify.mjs BASE_URL API_KEY --model=MODEL）
只依赖 Python3 标准库（阶段8 需 node）。
"""
import argparse, json, os, re, shutil, subprocess, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
# 签名解码核心 probe_thinking_signature.py 双位置查找：
#   开发布局在 skill 上层目录（jiaoben/），安装布局随包捆绑在 skill 目录内
PROBE = os.path.abspath(os.path.join(HERE, '..', 'probe_thinking_signature.py'))
if not os.path.exists(PROBE):
    PROBE = os.path.join(HERE, 'probe_thinking_signature.py')
SENT = "The quick brown fox jumps over the lazy dog near the river bank every single quiet morning. "
SIGDIR = os.path.join(HERE, 'sigs')
CHECK = os.path.join(HERE, 'channel_check.py')   # 阶段7 官方一致性检测（移植自 jiaoben/2.txt）
GEMINI = os.path.join(HERE, 'gemini_verify.mjs') # 阶段8 Gemini 真伪核验（移植自 jiaoben/gemini-verify.mjs）

# 与 channel_check.py 的 LABELS / MISMATCH_VERDICTS 保持同步（子进程边界，无法直接 import 常量）
CHECK_LABELS = {"pass": "已测项目符合内置参考", "signature_pool": "发现重复签名摘要",
                "not_first_party": "签名不是官方直连形态", "model_mismatch": "签名模型与请求不符",
                "missing_f21": "签名缺签发时间 / 代际不符", "stale_signature": "签名不是本次签发的",
                "signature_not_verified": "篡改签名未被拒绝，需复核",
                "request_or_billing_modified": "请求或计费与官方不一致",
                "review": "需复核", "inconclusive": "无法判定", "unavailable": "渠道不可用"}
CHECK_MISMATCH = ("signature_pool", "not_first_party", "model_mismatch", "missing_f21",
                  "stale_signature", "signature_not_verified", "request_or_billing_modified")

# ---------------------------------------------------------------- 基础请求

def urls(base):
    b = base.rstrip('/')
    if b.endswith('/v1'):
        b = b[:-3]
    return b + '/v1/models', b + '/v1/messages'


def post(url, key, body, timeout=300, extra_hdr=None):
    hdr = {"x-api-key": key, "authorization": "Bearer " + key,
           "anthropic-version": "2023-06-01", "content-type": "application/json"}
    hdr.update(extra_hdr or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdr)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode('utf-8', 'replace'), int((time.time() - t0) * 1000)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace'), int((time.time() - t0) * 1000)
    except Exception as e:
        return 0, str(e), int((time.time() - t0) * 1000)


def get(url, key, timeout=30):
    req = urllib.request.Request(url, headers={"authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8', 'replace')
    except Exception as e:
        return 0, str(e)

# ---------------------------------------------------------------- 阶段 0 体检

def phase0(models_url, msg_url, key, models):
    print('=' * 72)
    print('[阶段0] 渠道体检 (%d 个模型)' % len(models))
    ok, adaptive_hint, dead = [], {}, {}
    for m in models:
        st, raw, ms = post(msg_url, key, {"model": m, "max_tokens": 16,
                                          "messages": [{"role": "user", "content": "Reply with exactly: OK"}]})
        if st == 200:
            ok.append(m); print('  PASS  %5dms  %s' % (ms, m))
        else:
            note = ''
            try: note = json.loads(raw).get('error', {}).get('message', '')[:110]
            except Exception: note = raw[:110]
            if 'adaptive' in note: adaptive_hint[m] = note
            print('  FAIL  %5dms  %s  | %s' % (ms, m, note))
            dead[m] = 'HTTP %s %s' % (st, note)
    return ok, adaptive_hint, dead

# ---------------------------------------------------------------- 阶段 1 签名判定

RESULT_RE = re.compile(r'^RESULT (.+)$', re.M)
VERDICT_RE = re.compile(r'^VERDICT: (.+)$', re.M)


def run_probe(args):
    p = subprocess.run([sys.executable, PROBE] + args, capture_output=True, text=True, timeout=360)
    out = p.stdout + p.stderr
    r = RESULT_RE.search(out); v = VERDICT_RE.search(out)
    return p.returncode, out, (r.group(1) if r else None), (v.group(1) if v else None)


def grab_sig(text):
    try:
        for c in json.loads(text).get('content', []):
            if c.get('type') == 'thinking' and c.get('signature'):
                return c['signature']
    except Exception:
        pass
    return None


def phase1(msg_url, key, models, adaptive_hint):
    print('=' * 72)
    print('[阶段1] 签名判定 — 核心解码来自 probe_thinking_signature.py')
    os.makedirs(SIGDIR, exist_ok=True)
    results = {}
    for m in models:
        rc, out, result, verdict = run_probe([msg_url.rsplit('/v1/messages', 1)[0], key, '--model', m])
        if result:  # enabled 模式直接拿到
            print('  [enabled ] %s' % m)
            print('    %s' % result)
            if verdict: print('    VERDICT: %s' % verdict)
            results[m] = {'mode': 'enabled', 'result': result, 'verdict': verdict}
            continue
        # 失败原因分类: 拒绝 enabled(要 adaptive) / 不吐 thinking / 其他
        body = out[out.find('HTTP'):]
        if 'adaptive' in out or m in adaptive_hint:
            st, raw, ms = post(msg_url, key, {"model": m, "max_tokens": 2048,
                                              "thinking": {"type": "adaptive"},
                                              "messages": [{"role": "user",
                                                            "content": "Think step by step carefully, then answer in one short sentence: 17*23+19=?"}]})
            sig = grab_sig(raw) if st == 200 else None
            if sig:
                f = os.path.join(SIGDIR, re.sub(r'[^a-zA-Z0-9._-]', '_', m) + '.sig')
                open(f, 'w').write(sig)
                rc2, out2, result2, verdict2 = run_probe(['--decode-file', f])
                print('  [adaptive] %s  (%dms)' % (m, ms))
                print('    %s' % result2)
                if verdict2: print('    VERDICT: %s' % verdict2)
                results[m] = {'mode': 'adaptive', 'result': result2, 'verdict': verdict2}
            else:
                print('  [adaptive] %s  拿不到 thinking 签名 (HTTP %s)' % (m, st))
                results[m] = {'mode': 'adaptive', 'result': None, 'verdict': '无法判定（不吐 thinking）'}
        else:
            tail = [l for l in out.splitlines() if l.strip()][-2:]
            print('  [skip    ] %s  %s' % (m, ' / '.join(tail)[:120]))
            results[m] = {'mode': 'n/a', 'result': None, 'verdict': '无签名'}
    return results

# ---------------------------------------------------------------- 阶段 2 回传验签

def roundtrip(msg_url, key, model, think):
    q1 = {"model": model, "max_tokens": 2048, "thinking": think,
          "messages": [{"role": "user", "content": "Think step by step carefully, then answer: 47*2.5=? Reply with just the number."}]}
    st, raw, _ = post(msg_url, key, q1)
    if st != 200:
        return 'FAIL 第一轮 HTTP %s' % st
    tb = next((c for c in json.loads(raw)['content'] if c['type'] == 'thinking'), None)
    tx = next((c for c in json.loads(raw)['content'] if c['type'] == 'text'), None)
    if not tb:
        return 'SKIP 不吐 thinking'
    q2 = {"model": model, "max_tokens": 1536, "thinking": think, "messages": [
        q1['messages'][0], {"role": "assistant", "content": [tb, tx]},
        {"role": "user", "content": "Now reply with exactly: BRAVO"}]}
    st2, raw2, _ = post(msg_url, key, q2)
    if st2 == 200:
        return 'PASS 同渠道接受原样回传（未独立验签，不能排除剥块/复签）'
    return 'FAIL 回传 HTTP %s: %s' % (st2, raw2[:160])


def phase2(msg_url, key, models):
    print('=' * 72)
    print('[阶段2] 同渠道原样回传（不证明生成来源）')
    done = {}
    for m in models[:3]:
        for think in ({"type": "enabled", "budget_tokens": 1024}, {"type": "adaptive"}):
            r = roundtrip(msg_url, key, m, think)
            if not r.startswith(('FAIL 第一轮', 'SKIP')):
                print('  %s: %s' % (m, r)); done[m] = r; break
        else:
            print('  %s: %s' % (m, r)); done[m] = r
    return done

# ---------------------------------------------------------------- 阶段 3 参数指纹

def phase3(msg_url, key, model):
    print('=' * 72)
    print('[阶段3] 参数指纹（官转全过 / CC 网关型池子会有限制）')
    tool = {"name": "get_weather", "description": "d", "input_schema": {"type": "object", "properties": {}}}
    tests = [
        ("temperature=0.7", {"model": model, "max_tokens": 16, "temperature": 0.7,
                             "messages": [{"role": "user", "content": "Say OK"}]}),
        ("top_k=5",         {"model": model, "max_tokens": 16, "top_k": 5,
                             "messages": [{"role": "user", "content": "Say OK"}]}),
        ("tool_choice=any", {"model": model, "max_tokens": 64, "tools": [tool],
                             "tool_choice": {"type": "any"},
                             "messages": [{"role": "user", "content": "Weather?"}]}),
        ("stop_sequences",  {"model": model, "max_tokens": 16, "stop_sequences": ["OK"],
                             "messages": [{"role": "user", "content": "Say OK twice"}]}),
        ("system_prompt",   {"model": model, "max_tokens": 16, "system": "You are a pirate.",
                             "messages": [{"role": "user", "content": "Say OK"}]}),
    ]
    restricted = []
    for name, body in tests:
        st, raw, _ = post(msg_url, key, body)
        if st == 200:
            print('  PASS  %s' % name)
        else:
            msg = ''
            try: msg = json.loads(raw).get('error', {}).get('message', '')[:100]
            except Exception: msg = raw[:100]
            print('  FAIL  %-16s | %s' % (name, msg)); restricted.append(name)
    return restricted

# ---------------------------------------------------------------- 阶段 4 分词器对照

def phase4(msg_url, key, models):
    print('=' * 72)
    print('[阶段4] 分词器对照（同文本 2000 句，看计数是否同代一致 / 有无固定增量注入）')
    base_m, counts = None, {}
    for m in models[:5]:
        st, raw, _ = post(msg_url, key, {"model": m, "max_tokens": 8,
                                         "messages": [{"role": "user", "content": SENT * 2000 + "\nReply: OK"}]})
        if st != 200:
            print('  %s: HTTP %s' % (m, st)); continue
        it = json.loads(raw)['usage']['input_tokens']
        counts[m] = it
        if base_m is None: base_m, base = m, it
    for m, it in counts.items():
        print('  %-24s input=%6d  (%.2fx vs %s)' % (m, it, it / counts[base_m], base_m))
    vals = sorted(set(counts.values()))
    print('  结论: %d 种计数 %s — 同代一致=分词器差异(良性); 每模型不同增量=疑似注入' %
          (len(vals), vals))
    return counts

# ---------------------------------------------------------------- 阶段 5 1M 上下文

def phase5(msg_url, key, model, target=210000):
    print('=' * 72)
    print('[阶段5] 1M 上下文测试（%s, 目标 ~%d tokens, 不带 context-1m beta 头, 烧 token）' % (model, target))
    st, raw, _ = post(msg_url, key, {"model": model, "max_tokens": 8,
                                     "messages": [{"role": "user", "content": SENT * 2000 + "\nReply: OK"}]})
    if st != 200:
        print('  校准失败 HTTP %s' % st); return None
    per = json.loads(raw)['usage']['input_tokens'] / 2000.0
    big = SENT * int(target / per)
    st2, raw2, ms2 = post(msg_url, key, {"model": model, "max_tokens": 16,
                                         "messages": [{"role": "user", "content": big + "\nReply with just: OK"}]}, timeout=600)
    r = {'beta': None, 'plain_status': st2}
    if st2 == 200:
        it = json.loads(raw2)['usage']['input_tokens']
        print('  裸发 ✅ HTTP 200, input_tokens=%d' % it)
        print('  注意: 2026-03 起 1M 已 GA(默认,免 beta 头,标准价),官转同样裸吃 >200k — 本结果无 CCMax/官转区分力,仅确认渠道开放 1M')
        r['plain_ok'] = True
        return r
    print('  裸发 ❌ HTTP %s:' % st2); print('    ' + raw2[:300])
    st3, raw3, _ = post(msg_url, key, {"model": model, "max_tokens": 16,
                                       "messages": [{"role": "user", "content": big + "\nReply with just: OK"}]},
                        timeout=600, extra_hdr={"anthropic-beta": "context-1m-2025-08-07"})
    if st3 == 200:
        print('  +beta头 ✅ HTTP 200 → GA 模型不应有 beta 门槛,上游是 pre-GA 式非标准部署(疑似旧网关/池子)')
        r['beta'] = 'gated-accepted'
    else:
        print('  +beta头 ❌ HTTP %s: %s' % (st3, raw3[:200])); r['beta'] = 'rejected'
    return r

# ---------------------------------------------------------------- 阶段 6 撞限流

def phase6(msg_url, key, model, waves=3, conc=8, tpm_reqs=4, tpm_tokens=100000):
    print('=' * 72)
    print('[阶段6] 撞限流（模型 %s）— 撞到第一堵墙立即收手' % model)
    walls = []

    def one(_):
        return post(msg_url, key, {"model": model, "max_tokens": 8,
                                   "messages": [{"role": "user", "content": "Say OK"}]}, timeout=120)

    print('  A. RPM 突发: %d 波 x %d 并发' % (waves, conc))
    for w in range(waves):
        with ThreadPoolExecutor(max_workers=conc) as ex:
            rs = list(ex.map(one, range(conc)))
        codes = [s for s, _, _ in rs]
        print('    wave%d: %s' % (w + 1, codes))
        for s, raw, _ in rs:
            if s not in (200, 0) or (s == 0):
                if s != 200:
                    print('    >>> 完整错误原文:'); print('    ' + raw[:500]); walls.append(('RPM', s, raw[:300])); break
        if walls: break
        time.sleep(2)

    if not walls:
        print('  B. TPM 推压: %d 并发 x ~%dk tokens (每请求加独立前缀防上游缓存少计 ITPM)' % (tpm_reqs, tpm_tokens // 1000))
        st, raw, _ = post(msg_url, key, {"model": model, "max_tokens": 8,
                                         "messages": [{"role": "user", "content": SENT * 2000 + "\nReply: OK"}]})
        if st == 200:
            per = json.loads(raw)['usage']['input_tokens'] / 2000.0
            big = SENT * int(tpm_tokens / per)
            t0 = time.time()
            with ThreadPoolExecutor(max_workers=tpm_reqs) as ex:
                rs = list(ex.map(lambda i: post(msg_url, key, {"model": model, "max_tokens": 8,
                    "messages": [{"role": "user", "content": "[probe %d] " % i + big + "\nReply: OK"}]}, timeout=600), range(tpm_reqs)))
            tot = sum(json.loads(rawx)['usage']['input_tokens'] for s, rawx, _ in rs if s == 200)
            dur = time.time() - t0
            print('    %d 秒送入 ~%d tokens (≈%.1fM/分钟)' % (dur, tot, tot / max(dur, 1) * 60 / 1e6))
            for s, rawx, _ in rs:
                if s != 200:
                    print('    >>> 完整错误原文:'); print('    ' + rawx[:500]); walls.append(('TPM', s, rawx[:300])); break
    if not walls:
        print('  结果: 未撞到任何墙')
        print('  注意: 现行官转 tier(Start 2M/Build 5M/Scale 10M ITPM)下此推压强度不足以区分官转与池子')
        print('        — 无墙≠池子证据。本阶段真正有价值的是"撞到墙时的错误原文"(订阅式 vs API 式文案)')
    return walls

# ---------------------------------------------------------------- 阶段 7 官方一致性检测

def phase7(base_url, key, model, timeout=2400):
    print('=' * 72)
    print('[阶段7] 官方一致性检测 — skill/channel_check.py（7 项，约 52-67 个请求）')
    if model != 'claude-sonnet-4-6':
        print('  模型: %s（注意: 图片计费公式与纯文本 "hi"=8 token 真值只对 claude-sonnet-4-6 建立，其它模型这两项只记录不判定）' % model)
    else:
        print('  模型: %s' % model)
    cmd = [sys.executable, CHECK, base_url, key, '--model', model, '--json']
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print('  超时（>%ss），未完成' % timeout)
        return None
    try:
        res = json.loads(p.stdout)
    except Exception:
        print('  输出无法解析（exit %s）: %s' % (p.returncode, (p.stdout + p.stderr)[:400]))
        return None
    steps = res.get('steps') or {}
    for k, label in (("digest", "① 签名绑定"), ("envelope", "② 签名形态"), ("replay", "③ 签名校验"),
                     ("image_validation", "④ 图片校验"), ("sizes", "⑤ 图片计费"),
                     ("stability", "⑥ 计费稳定"), ("shape", "⑦ 响应形态"), ("usage", "⑦ usage")):
        st = steps.get(k)
        if st:
            print('  %-10s %-26s %s' % (label, st.get('verdict'), st.get('reason', '')))
    for e in res.get('odd_requests') or []:
        print('    计费异常请求 %s %s %s input_tokens=%s x-oneapi-request-id=%s msg_id=%s'
              % (e.get('ts'), e.get('step'), e.get('model'), e.get('input_tokens'),
                 e.get('x-oneapi-request-id') or '-', e.get('msg_id') or '-'))
    v = res.get('verdict')
    print('  结论: %s（exit %s）—— %s' % (CHECK_LABELS.get(v, v), p.returncode, res.get('reason', '')))
    print('        完整 JSON / 留痕可直接跑: python3 skill/channel_check.py %s <KEY> --model %s --trace-out trace.jsonl' % (base_url, model))
    return res


# ---------------------------------------------------------------- 阶段 8 Gemini 真伪核验

def phase8(base_url, key, model='gemini-4-argon', timeout=900):
    print('=' * 72)
    print('[阶段8] Gemini 真伪核验 — skill/gemini_verify.mjs（9 个行为探针，需 node 18+）')
    print('  模型: %s' % model)
    if not shutil.which('node'):
        print('  未找到 node，跳过（阶段8 需要安装 Node.js 18+，或直接用其它工具核验）')
        return None
    cmd = ['node', GEMINI, '--base=' + base_url, '--key=' + key, '--model=' + model, '--json']
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print('  超时（>%ss），未完成' % timeout)
        return None
    try:
        res = json.loads(p.stdout)
    except Exception:
        print('  输出无法解析（exit %s）: %s' % (p.returncode, (p.stdout + p.stderr)[:400]))
        return None
    if res.get('error'):  # AUTH_FAILED / NETWORK_ERROR
        print('  %s —— %s' % (res.get('verdict'), res.get('detail', '')))
        return res
    print('  接口风格: %s' % res.get('style', ''))
    for r in res.get('results') or []:
        print('  %-4s %-36s %s' % (r.get('verdict'), r.get('name'), (r.get('detail') or '')[:100]))
    print('  结论: 通过 %s / 失败 %s / 未取到结论 %s —— %s'
          % (res.get('passed'), res.get('failed'), res.get('skipped'), res.get('verdict')))
    print('        行为指纹证据而非密码学证明；SKIP 项多为限流所致，不代表失败')
    return res


# ---------------------------------------------------------------- 汇总判定

def summarize(sig, rt, restricted, counts, ctx, walls, consistency=None, gemini=None):
    print('=' * 72)
    print('[汇总判定]')
    layouts = set()
    for m, r in (sig or {}).items():
        mm = re.search(r'layout=(\S+)', r.get('result') or '')
        if mm:
            layouts.add(mm.group(1))
    upstream = ('混合' if len(layouts) > 1 else
                'AWSB(Bedrock)' if layouts == {'BEDROCK'} else
                'first-party 形态' if layouts and layouts <= {'FIRST-PARTY', 'FIRST-PARTY'} else
                '证据不足' if not layouts else '/'.join(layouts))
    print('  观察签名形态  : %s' % upstream)
    if rt:
        ok = sum(1 for v in rt.values() if v.startswith('PASS'))
        print('  同渠道回传    : %d/%d 通过 %s' % (ok, len(rt), '→ 仅观察到接受，未独立验签' if ok else '→ 未取得成功对照，需复核'))
    if restricted is not None:
        print('  参数指纹      : %s' % ('全过 → 官转特征或宽松池子' if not restricted else '受限 %s → CC 网关型池子' % restricted))
    if ctx is not None:
        if ctx.get('plain_ok'):
            print('  上下文        : >200k 裸发通过 — GA 后官转亦默认 1M，无区分力，仅确认能力')
        elif ctx.get('beta') == 'gated-accepted':
            print('  上下文        : 200k 拒 + beta 放行 — GA 模型不应有此门槛，上游非标准部署（疑似旧网关/池子）')
        else:
            print('  上下文        : >200k 被拒 — 与 GA 政策不符或渠道自设上限，人工核查')
    if walls is not None:
        if not walls:
            print('  限流墙        : 未撞到 — 现行官转 tier 下此强度无区分力，不能作为池子证据')
        else:
            kind, st, body = walls[0]
            sub = '订阅式(5-hour/weekly/usage limit) → 订阅供给线索' if re.search(r'5.?hour|weekly|usage.?limit', body, re.I) else \
                  'API 式(rate_limit/per minute) → API 供给线索' if re.search(r'rate.?limit|per minute', body, re.I) else '未知形态,人工判读原文'
            print('  限流墙        : %s 墙 HTTP %s, 文案形态=%s' % (kind, st, sub))
    if consistency is not None:
        v = consistency.get('verdict')
        print('  一致性检测    : %s —— %s' % (CHECK_LABELS.get(v, v), consistency.get('reason', '')))
        for e in consistency.get('odd_requests') or []:
            print('    计费异常请求 %s %s input_tokens=%s x-oneapi-request-id=%s'
                  % (e.get('step'), e.get('model'), e.get('input_tokens'),
                     e.get('x-oneapi-request-id') or '-'))
    if gemini is not None:
        if gemini.get('error'):
            print('  Gemini 真伪  : %s（%s）' % (gemini.get('verdict'), (gemini.get('detail') or '')[:90]))
        else:
            print('  Gemini 真伪  : %s —— %s'
                  % ('通过 %s / 失败 %s / 未取到结论 %s' % (gemini.get('passed', 0),
                                                          gemini.get('failed', 0), gemini.get('skipped', 0)),
                     gemini.get('verdict', '')))
    print('  ——')
    if layouts == {'BEDROCK'}:
        final = 'Bedrock 签名形态（正文生成来源未独立验证）'
    elif 'BEDROCK' in layouts:
        final = '签名形态混用（含 Bedrock 形态，生成来源未独立验证）'
    elif layouts:
        sub_wall = walls and re.search(r'5.?hour|weekly|usage.?limit', walls[0][2], re.I)
        api_wall = walls and re.search(r'rate.?limit|per minute', walls[0][2], re.I)
        gated = ctx is not None and ctx.get('beta') == 'gated-accepted'
        if sub_wall:
            final = '订阅供给线索（first-party 形态 + 订阅式限流文案，尚非来源证明）'
        elif api_wall:
            final = '官转 API key 特征（first-party 上游 + API 式限流文案）'
        elif gated:
            final = 'first-party 非标准部署（GA 模型带 beta 门槛，疑似旧网关/池子）'
        else:
            final = ('first-party 形态确认；CCMax 池与官转未能区分 — '
                     '1M 与限流判据在 2026-03 GA/新 tier 下已无区分力，'
                     '需订阅式/API 式限流文案，或分销链元数据(request-id 层数/分组名)人工判读')
    else:
        final = '无法判定（无签名证据 — 检查模型是否吞 thinking）'
    if consistency is not None and consistency.get('verdict') in CHECK_MISMATCH:
        final += '；⚠ 官方一致性检测发现不一致: %s' % consistency.get('reason', '')
    elif consistency is not None and consistency.get('verdict') == 'review':
        final += '；官方一致性检测: %s' % consistency.get('reason', '')
    if gemini is not None and (gemini.get('failed') or 0) > 0:
        final += '；⚠ Gemini 核验存在失败项: %s' % gemini.get('verdict', '')
    final += '；同渠道结果不能排除剥块、复签或探针分流'
    print('  最终判定      : %s' % final)
    print('=' * 72)
    return final


def main():
    ap = argparse.ArgumentParser(description='渠道体检+上游形态判定')
    ap.add_argument('base_url'); ap.add_argument('api_key')
    ap.add_argument('--models', help='逗号分隔，默认取渠道模型列表全部')
    ap.add_argument('--deep', action='store_true', help='阶段2/3/4: 验签+指纹+分词器')
    ap.add_argument('--big-context', metavar='MODEL', help='阶段5: 1M 上下文测试（烧 token）')
    ap.add_argument('--load', action='store_true', help='阶段6: 撞限流（需明确授权，烧 token）')
    ap.add_argument('--consistency', metavar='MODEL', nargs='?', const='auto', default=None,
                    help='阶段7: 官方一致性检测（~52-67 请求；模型省略时优先 claude-sonnet-4-6）')
    ap.add_argument('--gemini', metavar='MODEL', nargs='?', const='gemini-4-argon', default=None,
                    help='阶段8: Gemini 真伪核验（需 node 18+；Claude 侧全不通时仍单独执行）')
    ap.add_argument('--load-model', default=None)
    a = ap.parse_args()

    models_url, msg_url = urls(a.base_url)
    print('渠道: %s' % msg_url)
    print('签名解码核心: %s' % PROBE)

    st, raw = get(models_url, a.api_key)
    if st != 200 and a.gemini:
        # 纯 Gemini 渠道（无 Claude /v1 侧）：跳过 Claude 阶段，直接做 Gemini 核验
        print('[提示] /v1/models 拉取失败 HTTP %s —— 该渠道可能没有 Claude 侧，仅执行阶段8 Gemini 核验' % st)
        gm = phase8(a.base_url, a.api_key, a.gemini)
        summarize({}, None, None, None, None, None, None, gm)
        return
    if st != 200:
        print('模型列表拉取失败 HTTP %s: %s' % (st, raw[:200])); sys.exit(1)
    models = a.models.split(',') if a.models else [m['id'] for m in json.loads(raw)['data']]
    print('模型(%d): %s' % (len(models), ', '.join(models)))

    ok, adaptive_hint, dead = phase0(models_url, msg_url, a.api_key, models)
    if not ok and not a.gemini:
        print('全部模型不通，终止'); sys.exit(2)

    sig = phase1(msg_url, a.api_key, ok, adaptive_hint) if ok else {}

    sig = phase1(msg_url, a.api_key, ok, adaptive_hint)
    rt = restricted = counts = ctx = walls = None
    if a.deep:
        rt = phase2(msg_url, a.api_key, ok)
        restricted = phase3(msg_url, a.api_key, ok[0])
        counts = phase4(msg_url, a.api_key, ok)
    if a.big_context:
        ctx = phase5(msg_url, a.api_key, a.big_context)
    if a.load:
        lm = a.load_model or ok[0]
        walls = phase6(msg_url, a.api_key, lm)
    consistency = None
    if a.consistency and ok:
        cm = a.consistency
        if cm == 'auto':
            cm = 'claude-sonnet-4-6' if 'claude-sonnet-4-6' in ok else ok[0]
        consistency = phase7(a.base_url, a.api_key, cm)
    elif a.consistency:
        print('[提示] Claude 侧无可用模型，阶段7 跳过（--consistency 需要 Claude 模型可用）')
    gemini = phase8(a.base_url, a.api_key, a.gemini) if a.gemini else None
    summarize(sig, rt, restricted, counts, ctx, walls, consistency, gemini)


if __name__ == '__main__':
    main()
