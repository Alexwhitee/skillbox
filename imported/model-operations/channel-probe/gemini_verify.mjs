#!/usr/bin/env node
/**
 * Gemini 渠道真伪核验 —— 通用版
 *
 * 传入 key + base url + 模型 即可测试任意 Gemini 兼容端点。
 *
 * 用法（skill 集成版，另支持位置参数）：
 *   node gemini_verify.mjs --key=sk-xxx --base=https://api.example.com --model=gemini-4-argon
 *   node gemini_verify.mjs https://api.example.com sk-xxx --model=gemini-4-argon
 *
 * 参数：
 *   --key      API key（或位置参数第 2 个，或环境变量 GEMINI_KEY）
 *   --base     base url，如 https://api.example.com（或位置参数第 1 个；必填，可带或不带 /v1beta）
 *   --model    模型名（默认 gemini-4-argon）
 *   --retries  限流重试次数（默认 6）
 *   --style    auto | v1beta | vertex   接口风格（默认 auto 自动探测）
 *   --json     以 JSON 输出结果（便于程序处理）
 *
 * 退出码：0 = 全部通过；1 = 存在失败项；2 = 参数错误
 *
 * 原理：真实 Google Gemini 端点在「参数校验」上有一组非常稳定的特征报错
 *      （protobuf 枚举校验器、role 白名单、thinkingBudget 能力判定等）。
 *      套壳/逆向代理通常只实现正常路径，遇到边界参数会静默接受或返回自造泛化错误。
 *
 * 注意：本脚本给出的是「行为指纹」证据，不是密码学证明。
 *
 * 本文件移植自 jiaoben/gemini-verify.mjs：仅增加了位置参数 BASE_URL KEY 的支持，
 * 探针与判定逻辑逐字未改。
 */

/* ============================ 参数解析 ============================ */

const argv = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const m = a.match(/^--([^=]+)(?:=(.*))?$/);
    return m ? [m[1], m[2] === undefined ? true : m[2]] : [a, true];
  })
);
const positional = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const [posBase, posKey] = positional;

if (argv.help || (!argv.key && !posKey && !process.env.GEMINI_KEY)) {
  console.log(`
用法:
  node gemini_verify.mjs --key=<API_KEY> --base=<BASE_URL> [--model=<MODEL>] [--retries=<N>] [--json]
  node gemini_verify.mjs <BASE_URL> <API_KEY> [--model=<MODEL>] [--retries=<N>] [--json]

示例:
  node gemini_verify.mjs --key=sk-abc123 --base=https://api.example.com --model=gemini-4-argon
  node gemini_verify.mjs https://api.example.com sk-abc123
`);
  process.exit(argv.help ? 0 : 2);
}

const KEY     = String(argv.key || posKey || process.env.GEMINI_KEY);
const BASE    = String(argv.base || posBase || process.env.GEMINI_BASE || 'https://api.nexrouter.ai').replace(/\/+$/, '');
const MODEL   = String(argv.model || process.env.GEMINI_MODEL || 'gemini-4-argon');
const RETRIES = Number(argv.retries || 6);
const STYLE   = String(argv.style || 'auto');
const AS_JSON = !!argv.json;

/* ============================ 端点探测 ============================ */

// 去掉用户可能误填的路径后缀
const ROOT = BASE.replace(/\/v1beta\/?$/, '').replace(/\/v1\/?$/, '');

const STYLES = {
  v1beta: { path: (m, act) => `/v1beta/models/${m}:${act}`, name: 'v1beta (AI Studio 风格)' },
  vertex: { path: (m, act) => `/v1/publishers/google/models/${m}:${act}`, name: 'publishers (Vertex 风格)' },
};

/**
 * 认证三件套同时发：不同中转商认不同位置（?key= / x-goog-api-key / Authorization）
 * 同时发送是安全的，各家会忽略自己不认识的那个。
 */
function buildUrl(style, model, action) {
  const p = STYLES[style].path(model, action);
  return `${ROOT}${p}?key=${encodeURIComponent(KEY)}`;
}
const HEADERS = {
  'Content-Type': 'application/json',
  'x-goog-api-key': KEY,
  'Authorization': `Bearer ${KEY}`,
};

const isRateLimited = (t) =>
  /high demand|overloaded|RESOURCE_EXHAUSTED|rate.?limit|quota exceeded|当前没有可用|暂不可用/i.test(t) ||
  /"code"\s*:\s*429/.test(t);

async function request(body, { style, model = MODEL, retries = RETRIES, action = 'generateContent' } = {}) {
  let last = { status: 0, json: null, text: '' };
  for (let i = 0; i <= retries; i++) {
    let res;
    try {
      res = await fetch(buildUrl(style, model, action), {
        method: 'POST', headers: HEADERS, body: JSON.stringify(body),
      });
    } catch (e) {
      last = { status: 0, json: null, text: 'NETWORK: ' + String(e.message ?? e) };
      if (i < retries) { await sleep(800 * (i + 1)); continue; }
      return { ...last, networkError: true };
    }
    const text = await res.text();
    let json = null;
    try { json = JSON.parse(text); } catch { /* 非 JSON */ }

    if (isRateLimited(text)) {
      last = { status: res.status, json, text };
      if (i < retries) { await sleep(1200 * (i + 1)); continue; }
      return { ...last, rateLimited: true };
    }
    return { status: res.status, json, text };
  }
  return { ...last, rateLimited: true };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 自动探测接口风格 */
async function detectStyle() {
  for (const style of ['v1beta', 'vertex']) {
    const r = await request({ contents: [{ role: 'user', parts: [{ text: 'hi' }] }] },
                            { style, retries: 1 });
    if (r.rateLimited) continue;                     // 限流说明端点存在，换下一个再试
    if (r.networkError) continue;
    if (!r.json) continue;                           // HTML / 非 JSON，风格不对
    const t = r.text;
    if (/Invalid URL|不支持的路径|Unsupported path|not found.*path/i.test(t)) continue;
    if (r.json.error || r.json.candidates) return style;
  }
  return 'v1beta';
}

/* ============================ 探针 ============================ */

const hi = () => ({ contents: [{ role: 'user', parts: [{ text: 'hi' }] }] });
const msgOf = (r) => {
  if (!r.json) return (r.text || '').slice(0, 240);
  const e = r.json.error;
  if (!e) return '';
  return typeof e === 'string' ? e : (e.message || JSON.stringify(e));
};
const isErr = (r) => !!(r.json && r.json.error) || r.status >= 400;

const P = (id, name, why, run) => ({ id, name, why, run });

const PROBES = [
  P('role', '非法 role 被拒', '官方只接受 user/model', async (style) => {
    const r = await request({ contents: [{ role: 'banana', parts: [{ text: 'hi' }] }] }, { style });
    if (r.rateLimited) return skip();
    const m = msgOf(r);
    const ok = isErr(r) && /valid role|role.*not supported|not supported.*role/i.test(m);
    return ok ? pass(short(m)) : fail(m);
  }),

  P('empty', '空输入被拒', '官方对空 parts 返回 cannot be empty', async (style) => {
    const r = await request({ contents: [{ role: 'user', parts: [] }] }, { style });
    if (r.rateLimited) return skip();
    const m = msgOf(r);
    const ok = isErr(r) && /cannot be empty|empty input|input.*empty|has empty/i.test(m);
    return ok ? pass(short(m)) : fail(m);
  }),

  P('enum_tool', 'protobuf 枚举校验 (toolConfig.mode)', '官方回 "Invalid value at tool_config..." + protobuf 类型 URL', async (style) => {
    const b = hi();
    b.tools = [{ codeExecution: {} }];
    b.toolConfig = { functionCallingConfig: { mode: 'TOTALLY_BOGUS_MODE' } };
    const r = await request(b, { style });
    if (r.rateLimited) return skip();
    const m = msgOf(r);
    const ok = isErr(r) && /Invalid value at .tool_config/i.test(m);
    return ok ? pass(short(m)) : fail(m);
  }),

  P('enum_safety', 'protobuf 枚举校验 (safetySettings.threshold)', '官方回 "Invalid value at safety_settings..."', async (style) => {
    const b = hi();
    b.safetySettings = [{ category: 'HARM_CATEGORY_HARASSMENT', threshold: 'TOTALLY_BOGUS_THRESHOLD' }];
    const r = await request(b, { style });
    if (r.rateLimited) return skip();
    const m = msgOf(r);
    const ok = isErr(r) && /Invalid value at .safety_settings/i.test(m);
    return ok ? pass(short(m)) : fail(m);
  }),

  P('thinking', 'thinkingBudget 能力判定', '该模型只支持 thinkingLevel，官方会明确拒绝 thinkingBudget', async (style) => {
    const b = hi();
    b.generationConfig = { thinkingConfig: { thinkingBudget: 1024 } };
    const r = await request(b, { style });
    if (r.rateLimited) return skip();
    if (!isErr(r)) return fail('非法参数被静默接受（官方应拒绝）');
    const m = msgOf(r);
    const ok = /thinking budget is not supported|thinking level instead/i.test(m);
    return ok ? pass(short(m)) : fail(m);
  }),

  P('cached', 'cachedContent 名称解析', '官方会解析缓存资源名并报 Not found / Could not parse', async (style) => {
    const b = hi();
    b.cachedContent = 'projects/bogus/locations/bogus/cachedContents/bogus-id';
    const r = await request(b, { style });
    if (r.rateLimited) return skip();
    const m = msgOf(r);
    const ok = isErr(r) && /cached ?content|cachedcontent/i.test(m) &&
               /not found|could not parse|invalid|不存在|无法解析/i.test(m);
    return ok ? pass(short(m)) : fail(m);
  }),

  P('envelope', '响应信封字段', '官方响应必带 modelVersion + responseId', async (style) => {
    const r = await request(hi(), { style });
    if (r.rateLimited) return skip();
    if (!r.json || r.json.error) return fail('无功性响应：' + short(msgOf(r)));
    const o = r.json;
    const req = ['modelVersion', 'responseId'].filter((k) => !o[k]);
    if (req.length) return fail('缺必备字段：' + req.join(', '));
    const opt = ['createTime'].filter((k) => !o[k]);
    return pass(`modelVersion=${o.modelVersion}` + (opt.length ? '（无 createTime，Vertex 端点特征）' : ''));
  }),

  P('usage', 'usageMetadata 字段集', '官方带 promptTokensDetails + candidatesTokensDetails', async (style) => {
    const r = await request(hi(), { style });
    if (r.rateLimited) return skip();
    if (!r.json || r.json.error) return fail('无功性响应');
    const um = r.json.usageMetadata || {};
    const keys = Object.keys(um);
    const hasDetails = keys.includes('promptTokensDetails') && keys.includes('candidatesTokensDetails');
    if (!hasDetails) return fail('缺 *TokensDetails；实际：' + keys.join(', '));
    const hasTraffic = keys.includes('trafficType');
    return pass(keys.join(', ') + (hasTraffic ? '' : '（无 trafficType，Vertex 端点特征）'));
  }),

  P('badmodel', '不存在的模型被拒', '不存在的模型必须报错，不能编造回答', async (style) => {
    const r = await request(hi(), { style, model: 'gemini-9-nonexistent-xyz', retries: 2 });
    if (r.rateLimited) return skip();
    if (!isErr(r)) {
      const n = (r.json?.candidates || []).length;
      return fail(`不存在的模型却返回了 ${n} 个候选答案`);
    }
    const m = msgOf(r);
    // 若被上游或网关的模型/价格目录拦下，这项没真正探到模型，不当证据
    if (/price not configured|价格未配置|No available channel|没有可用|model_not_found/i.test(m)) {
      return skip('被模型/价格目录拦截，未触达模型：' + short(m));
    }
    return pass(short(m));
  }),
];

const pass = (d) => ({ verdict: 'PASS', detail: d });
const fail = (d) => ({ verdict: 'FAIL', detail: d });
const skip = (d = '限流或无法判定，未取到结论') => ({ verdict: 'SKIP', detail: d });
const short = (s) => String(s || '').replace(/\s+/g, ' ').slice(0, 200);

/* ============================ 执行 ============================ */

const C = { r: '\x1b[0m', b: '\x1b[1m', d: '\x1b[2m',
            red: '\x1b[31m', grn: '\x1b[32m', yel: '\x1b[33m', cyn: '\x1b[36m' };
const paint = (v) => v === 'PASS' ? `${C.grn}✓ PASS${C.r}`
                    : v === 'FAIL' ? `${C.red}✗ FAIL${C.r}`
                    : `${C.yel}? SKIP${C.r}`;

const style = STYLE === 'auto' ? await detectStyle() : STYLE;

/* 预检：认证失败 / 端点不可达时直接退出，避免把 401 当成「套壳」判据 */
{
  const pre = await request(hi(), { style, retries: 1 });
  const m = msgOf(pre);
  const authProblem = /invalid token|invalid api key|unauthorized|authentication|api key not valid|无权限|鉴权/i.test(m)
                   || pre.status === 401 || pre.status === 403;
  if (authProblem) {
    const out = { base: ROOT, model: MODEL, style: STYLES[style].name,
                  error: 'AUTH_FAILED', detail: short(m), verdict: '无法核验：认证失败' };
    if (AS_JSON) console.log(JSON.stringify(out, null, 2));
    else {
      console.error(`${C.red}认证失败，无法进行核验${C.r}`);
      console.error(`  ${C.d}${short(m)}${C.r}`);
      console.error(`  ${C.d}请检查 --key 是否正确、是否有该模型权限。${C.r}`);
    }
    process.exit(2);
  }
  if (pre.networkError) {
    const out = { base: ROOT, model: MODEL, error: 'NETWORK_ERROR', detail: short(m),
                  verdict: '无法核验：端点不可达' };
    if (AS_JSON) console.log(JSON.stringify(out, null, 2));
    else {
      console.error(`${C.red}端点不可达：${ROOT}${C.r}`);
      console.error(`  ${C.d}${short(m)}${C.r}`);
    }
    process.exit(2);
  }
}

if (!AS_JSON) {
  console.log(`${C.b}Gemini 渠道真伪核验${C.r}`);
  console.log(`  base  : ${ROOT}`);
  console.log(`  model : ${MODEL}`);
  console.log(`  接口  : ${STYLES[style].name}`);
  console.log(`  时间  : ${new Date().toISOString()}`);
  console.log('');
}

const results = [];
for (const probe of PROBES) {
  if (!AS_JSON) process.stdout.write(`  ${probe.name} ... `);
  let r;
  try {
    r = await probe.run(style);
  } catch (e) {
    r = skip('请求异常：' + short(e.message ?? e));
  }
  results.push({ id: probe.id, name: probe.name, why: probe.why, ...r });
  if (!AS_JSON) {
    console.log(paint(r.verdict));
    console.log(`    ${C.d}${r.detail}${C.r}`);
  }
}

const nPass = results.filter((x) => x.verdict === 'PASS').length;
const nFail = results.filter((x) => x.verdict === 'FAIL').length;
const nSkip = results.filter((x) => x.verdict === 'SKIP').length;

let verdict;
if (nFail === 0 && nPass >= 7)      verdict = '行为与官方 Google Gemini 端点一致，未发现套壳迹象';
else if (nFail === 0 && nPass >= 5) verdict = '主要行为与官方一致（部分项限流未取到结论，建议稍后重跑）';
else if (nFail <= 2)                verdict = '存在个别偏离项，建议结合失败明细复核供给来源';
else                               verdict = '多项偏离官方行为，高度疑似套壳/逆向代理，不建议作为官方供给使用';

if (AS_JSON) {
  console.log(JSON.stringify({
    base: ROOT, model: MODEL, style: STYLES[style].name,
    passed: nPass, failed: nFail, skipped: nSkip,
    verdict, results,
  }, null, 2));
} else {
  console.log(`\n${C.b}========== 汇总 ==========${C.r}`);
  console.log(`  通过 ${nPass} / 失败 ${nFail} / 未取到结论 ${nSkip}（共 ${results.length} 项）\n`);
  for (const r of results.filter((x) => x.verdict === 'FAIL')) {
    console.log(`  ${C.red}✗ ${r.name}${C.r}`);
    console.log(`    ${C.d}${r.detail}${C.r}`);
    console.log(`    ${C.d}期望：${r.why}${C.r}`);
  }
  if (nFail) console.log('');
  console.log(`${C.b}结论：${C.r}${verdict}\n`);
  console.log(C.d + '说明：本脚本判定的是「行为指纹」，不是密码学证明；' + C.r);
  console.log(C.d + '多项探针同时与官方一致时，可认为该端点确实接到真实 Google Gemini。' + C.r);
  console.log(C.d + 'SKIP 项通常由上游限流导致，不代表失败。' + C.r);
}

process.exit(nFail === 0 ? 0 : 1);
