#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe_thinking_signature.py — 触发 extended thinking，解出签名里的平台位 / 身份位

用法：
  python3 probe_thinking_signature.py <BASE_URL> <API_KEY> [--model claude-opus-4-8]
  python3 probe_thinking_signature.py --decode '<base64 signature>'
  python3 probe_thinking_signature.py --decode-file sig.txt

只依赖 Python 3 标准库。被测模型需支持 thinking，建议各跑一次：
  claude-opus-4-8 / claude-opus-5  -> full header，有 workspace uuid 或 AWS 账号
  claude-opus-5-5                  -> compact header，只有平台位，无 identity
"""
import argparse, base64, json, re, sys, time, urllib.request, urllib.error

UUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
ACCT = re.compile(r'^\d{12}$')


def vi(b, i):
    v = s = 0
    while i < len(b):
        c = b[i]; i += 1
        v |= (c & 0x7f) << s
        if not c & 0x80:
            return v, i
        s += 7
        if s > 63:
            return None, i
    return None, i


def pbf(b):
    """解一段 protobuf -> [(field_no, wire_type, bytes|None, varint|None)]"""
    i, out = 0, []
    while i < len(b):
        tag, i = vi(b, i)
        if tag is None: return None
        n, t = tag >> 3, tag & 7
        if n == 0: return None
        if t == 0:
            x, i = vi(b, i)
            if x is None: return None
            out.append((n, t, None, x))
        elif t in (1, 5):
            ln = 8 if t == 1 else 4
            if i + ln > len(b): return None
            out.append((n, t, b[i:i + ln], None)); i += ln
        elif t == 2:
            ln, i = vi(b, i)
            if ln is None or i + ln > len(b): return None
            out.append((n, t, b[i:i + ln], None)); i += ln
        else:
            return None
    return out


def ascii_(v):
    return v.decode() if v and len(v) <= 128 and all(32 <= c < 127 for c in v) else ''


def decode(sig):
    d = dict(ok=False, err='', b64=len(sig), raw=0, prefix=sig[:4], version=None,
             platform=None, model='', marker='', ident='', digest=0, iat=None,
             extra=[], fields=[], uuids=[], accts=[], inner=[])
    try:
        raw = base64.b64decode(sig, validate=False)
    except Exception as e:
        d['err'] = 'base64 解码失败: %s' % e; return d
    d['raw'] = len(raw)
    top = pbf(raw)
    if top is None:
        d['err'] = '顶层不是合法 protobuf'; return d
    env = next((v for n, t, v, _ in top if n == 2 and t == 2 and v), None)
    if not env:
        d['err'] = '缺少顶层 field 2 (envelope)'; return d
    inner = pbf(env) or []
    d['inner'] = [(n, len(v) if t == 2 else None) for n, t, v, _ in inner]
    hdr = next((v for n, t, v, _ in inner if n == 1 and t == 2 and v), None)
    if not hdr:
        d['err'] = '缺少 envelope field 1 (header)'; return d
    hf = pbf(hdr)
    if hf is None:
        d['err'] = 'header 解析失败'; return d
    for n, t, v, x in hf:
        d['fields'].append((n, 'varint' if t == 0 else 'bytes:%d' % len(v)))
        if n == 1 and t == 0: d['version'] = x
        elif n == 2 and t == 0: d['platform'] = x
        elif n == 5 and t == 2: d['digest'] = len(v)
        elif n == 6 and t == 2: d['model'] = ascii_(v)
        elif n == 8 and t == 2: d['marker'] = ascii_(v)
        elif n == 11 and t == 2: d['ident'] = ascii_(v)
        elif n == 21 and t == 0: d['iat'] = x
        elif n not in (1, 2, 3, 5, 6, 7, 8, 11, 21): d['extra'].append(n)
        if t == 2 and v:
            s = ascii_(v)
            if UUID.match(s): d['uuids'].append((n, s))
            if ACCT.match(s): d['accts'].append((n, s))
    d['ok'] = True
    return d


def verdict(d, mid):
    plat, ident = d['platform'], d['ident']
    layout = ('BEDROCK' if plat == 1 else 'FIRST-PARTY' if plat is None else 'UNKNOWN(%r)' % plat)
    if not (d['model'] or ident): layout += ' compact'
    claim = 'aws' if mid.startswith('msg_bdrk_') else 'anthropic' if mid.startswith('msg_01') else \
            'vertex' if mid.startswith('msg_vrtx_') else '?'
    ok = (plat == 1) if claim == 'aws' else (plat is None) if claim == 'anthropic' else None
    return layout, claim, ok


def post(url, key, payload, timeout=240):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method='POST')
    for k, v in (('content-type', 'application/json'), ('x-api-key', key),
                 ('authorization', 'Bearer ' + key), ('anthropic-version', '2023-06-01')):
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get('content-type', ''), r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get('content-type', ''), e.read().decode('utf-8', 'replace')


def extract(ctype, text):
    mid = model = ''
    sigs, blocks = [], []

    def eat(o):
        nonlocal mid, model
        if not isinstance(o, dict): return
        m = o.get('message')
        if isinstance(m, dict):
            mid = mid or m.get('id', ''); model = model or m.get('model', '')
        if o.get('type') == 'message' and o.get('id'):
            mid = mid or o['id']; model = model or o.get('model', '')
        if o.get('type') == 'content_block_start':
            c = o.get('content_block') or {}
            blocks.append(c.get('type', '?'))
            if c.get('type') == 'thinking' and c.get('signature'): sigs.append(c['signature'])
        for c in o.get('content') or []:
            if isinstance(c, dict):
                blocks.append(c.get('type', '?'))
                if c.get('type') == 'thinking' and c.get('signature'): sigs.append(c['signature'])
        dl = o.get('delta') or {}
        if dl.get('type') == 'signature_delta' and dl.get('signature'): sigs.append(dl['signature'])

    if 'event-stream' in ctype or text.lstrip().startswith('event:'):
        for line in text.splitlines():
            if line.startswith('data:'):
                try: eat(json.loads(line[5:].strip()))
                except Exception: pass
        sig = ''.join(sigs)          # SSE 的 signature 是分片
    else:
        try: eat(json.loads(text))
        except Exception: pass
        sig = sigs[0] if sigs else ''
    return mid, model, sig, list(dict.fromkeys(blocks))


def report(d, mid, blocks):
    lay, claim, ok = verdict(d, mid)
    print('=' * 64)
    print('[1] 签名特征')
    print('  长度        : base64 %d / 原始 %d 字节' % (d['b64'], d['raw']))
    print('  前缀        : %s' % d['prefix'])
    print('  布局        : %s' % ('compact header' if not (d['model'] or d['ident']) else 'full header'))
    print('  header 版本 : f1=%s' % d['version'])
    print('  平台位 f2   : %s' % ('缺失' if d['platform'] is None else d['platform']))
    print('  字段        : %s' % ', '.join('f%d(%s)' % f for f in d['fields']))
    print('[2] 解出来的信息')
    print('  平台位      : %s' % ('缺失' if d['platform'] is None else d['platform']))
    print('  模型 f6     : %s' % (d['model'] or '(无)'))
    print('  标记 f8     : %s' % (d['marker'] or '(无)'))
    print('  摘要 f5     : %s' % ('%d 字节' % d['digest'] if d['digest'] else '(无)'))
    print('  签发 f21    : %s' % (time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(d['iat'])) if d['iat'] else '(无)'))
    print('  额外字段    : %s' % (d['extra'] or '(无)'))
    print('  密文长度    : %d 字节' % next((l for n, l in d['inner'] if n == 5), 0))
    print('[3] 身份')
    if UUID.match(d['ident']):
        print('  ★ workspace uuid / trace id : %s   (f11)' % d['ident'])
    elif ACCT.match(d['ident']):
        print('  ★ 12 位 AWS 账号            : %s   (f11，Bedrock 形态)' % d['ident'])
    elif d['ident']:
        print('  ★ 身份位 f11                : %s' % d['ident'])
    else:
        print('  ✗ 无身份位（compact，只有平台位可判）')
    if d['uuids'] or d['accts']:
        print('  扫到的身份值: %s' % (d['uuids'] + d['accts']))
    print('[4] 判定')
    print('  签名形态    : %s' % lay)
    print('  message_id  : %s  (前缀声称: %s)' % (mid or '-', claim))
    if mid:
        print('  一致性      : %s' % ('✅ 一致' if ok else '❌ 矛盾 —— 就是要查的形态' if ok is False else '? 前缀不认识'))
    if d['platform'] == 1:
        print('  Bedrock UUID: 无（真 Bedrock 不签发 workspace uuid）')
        print('  Bedrock 账号: %s' % (d['ident'] if ACCT.match(d['ident']) else '(无 12 位账号，数据不完整)'))
        print('  说明        : f11 是 12 位 AWS 账号；f6 可能是代号(honey/quince/saffron/fir)，代号≠官转')
    elif d['platform'] is None and UUID.match(d['ident']):
        print('  说明        : 无平台位 + 36 位 uuid = first-party / CCMax 形态，不是 Bedrock')
    elif d['platform'] is None:
        print('  说明        : 无平台位无身份位，只能说明不是 Bedrock 形态，没有 trace id')
    print('  响应块      : %s' % (blocks or '-'))
    print('=' * 64)
    print('RESULT layout=%s platform=%s identity=%s message_id=%s consistent=%s'
          % (lay, '-' if d['platform'] is None else d['platform'], d['ident'] or '-', mid or '-', ok))
    if not d['ok']:
        print('解析失败: %s' % d['err'])
    if not d['ok']:
        v = '无法判定（签名解析失败）'
    elif d['platform'] == 1:
        v = 'Bedrock 签名形态' + ('（12 位账号 %s）' % d['ident'] if ACCT.match(d['ident']) else '（缺账号）')
    elif d['platform'] is None:
        if UUID.match(d['ident']):
            v = 'first-party 签名形态（UUID；仅凭格式无法细分 CCMax 与 API）'
        elif not (d['model'] or d['ident']):
            v = 'compact 签名（无身份位，格式信息不足以确认或排除供应来源）'
        else:
            v = '无平台位的签名形态（无身份位，来源未验证）'
    else:
        v = '无法判定（平台位=%r 未知）' % d['platform']
    if ok is False:
        v += '  ⚠ message_id 前缀与签名矛盾，警惕拼接/伪装'
    print('VERDICT: %s；仅解码格式，未独立验签，不能证明正文来源或排除复签' % v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base_url', nargs='?')
    ap.add_argument('api_key', nargs='?')
    ap.add_argument('--model', default='claude-opus-4-8')
    ap.add_argument('--max-tokens', type=int, default=2048)
    ap.add_argument('--budget', type=int, default=1024)
    ap.add_argument('--decode'); ap.add_argument('--decode-file')
    a = ap.parse_args()
    if a.decode or a.decode_file:
        sig = a.decode or open(a.decode_file).read().strip()
        report(decode(sig), '', []); return
    if not a.base_url or not a.api_key:
        ap.error('需要 BASE_URL 和 API_KEY，或 --decode <signature>')
    b = a.base_url.rstrip('/')
    url = b if b.endswith('/messages') else b + '/messages' if b.endswith('/v1') else b + '/v1/messages'
    body = {'model': a.model, 'max_tokens': a.max_tokens,
            'thinking': {'type': 'enabled', 'budget_tokens': a.budget},
            'messages': [{'role': 'user', 'content': 'Think step by step, then answer in one short sentence: 17*23+19=?'}]}
    print('POST %s  model=%s' % (url, a.model))
    st, ct, txt = post(url, a.api_key, body)
    print('HTTP %s  content-type=%s  %d bytes' % (st, ct, len(txt)))
    if st >= 400:
        print(txt[:800]); sys.exit(1)
    mid, model, sig, blocks = extract(ct, txt)
    if not sig:
        print('没有 thinking signature。块类型=%s' % blocks)
        print('排查: 模型是否支持 thinking / budget 是否 < max_tokens / 网关是否吞了 thinking 块')
        print(txt[:600]); sys.exit(2)
    if model: print('响应 model: %s' % model)
    report(decode(sig), mid, blocks)


if __name__ == '__main__':
    main()
