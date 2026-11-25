import assert from 'node:assert/strict';
import { copyFile, mkdir, writeFile } from 'node:fs/promises';
import { posix } from 'node:path';
import { content, siteName } from './content.mjs';

const routes = {
  'zh-CN': { home: '', guide: 'guide/' },
  en: { home: 'en/', guide: 'en/guide/' },
};
const languages = Object.keys(routes);
const output = new URL('./dist/', import.meta.url);
const previewCommands = 'node build.mjs\npython3 -m http.server 4173 --bind 127.0.0.1 --directory dist';
const siteUrl = process.env.PROJECT_SITE_URL ? new URL(process.env.PROJECT_SITE_URL) : null;
if (siteUrl) {
  assert(['http:', 'https:'].includes(siteUrl.protocol) && !siteUrl.username && !siteUrl.password &&
    !siteUrl.search && !siteUrl.hash && siteUrl.pathname.endsWith('/'),
  'PROJECT_SITE_URL must be a credential-free HTTP(S) base URL ending in /.');
}

const entities = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const escape = value => value.replace(/[&<>"']/g, char => entities[char]);
const group = (items, render) => items.map(render).join('\n');
const relative = (from, to) => {
  const path = posix.relative(from || '.', to || '.');
  if (!path) return './';
  return !to || to.endsWith('/') ? path + '/' : path;
};

function renderHome(copy, href) {
  return `
<section class="hero wrap">
  <div class="hero-copy">
    <h1>${group(copy.homeTitle, line => `<span>${escape(line)}</span>`)}</h1>
    <p class="lead">${escape(copy.homeSummary)}</p>
    <div class="actions">
      <a class="button" href="${href('guide')}">${escape(copy.mainAction)}</a>
      <a class="quiet-link" href="#start">${escape(copy.start)} <span aria-hidden="true">↓</span></a>
    </div>
  </div>
  <nav class="site-map" aria-label="${escape(copy.mapTitle)}">
    <h2>${escape(copy.mapTitle)}</h2>
    <div class="map-branches">
      ${group(languages, (language, index) => `
        <div class="map-branch">
          <p class="map-language" lang="${language}">${escape(copy.mapLabels[index])}</p>
          ${group(['home', 'guide'], (kind, pageIndex) => `
            <a href="${href(kind, language)}"><span>${escape(copy.mapPages[pageIndex])}</span><code>${escape('/' + routes[language][kind])}</code></a>
          `)}
        </div>`)}
    </div>
  </nav>
</section>
<section class="workflow wrap" id="workflow" data-translated>
  <h2>${escape(copy.processTitle)}</h2>
  <ol class="steps">
    ${group(copy.process, ([title, detail]) => `<li><h3>${escape(title)}</h3><p>${escape(detail)}</p></li>`)}
  </ol>
</section>
<section class="quickstart" id="start" data-translated>
  <div class="wrap start-layout">
    <div><h2>${escape(copy.start)}</h2><p>${escape(copy.startSummary)}</p></div>
    <pre tabindex="0"><code>${escape(copy.prompt)}</code></pre>
  </div>
</section>`;
}

function renderGuide(copy) {
  const sections = Object.entries(copy.sections);
  return `
<div class="guide-layout wrap">
  <div class="guide-heading">
    <h1>${escape(copy.guideTitle)}</h1>
    <p class="lead">${escape(copy.guideSummary)}</p>
  </div>
  <aside><nav aria-label="${escape(copy.documentLabel)}">
    <p>${escape(copy.documentLabel)}</p>
    ${group(sections, ([id, [title]]) => `<a href="#${id}">${escape(title)}</a>`)}
  </nav></aside>
  <article class="guide-copy">
    ${group(sections, ([id, [title, detail]]) => `
      <section id="${id}" class="guide-section" data-translated>
        <h2>${escape(title)}</h2><p>${escape(detail)}</p>
        ${id === 'preview' ? `<pre tabindex="0"><code>${escape(previewCommands)}</code></pre>` : ''}
      </section>
    `)}
  </article>
</div>`;
}

function render(lang, kind) {
  const copy = content[lang];
  const path = routes[lang][kind];
  const href = (page, language = lang) => relative(path, routes[language][page]);
  const title = kind === 'home' ? copy.home : copy.guideTitle;
  const description = kind === 'home' ? copy.homeSummary : copy.guideSummary;
  const languageLinks = group(languages, language => `
    <a href="${href(kind, language)}" lang="${language}" hreflang="${language}"${language === lang ? ' aria-current="page"' : ' data-language-switch'}>${escape(content[language].language)}</a>`);
  const metadata = siteUrl ? `
  <link rel="canonical" href="${escape(new URL(path, siteUrl).href)}">
  ${group(languages, language => `<link rel="alternate" hreflang="${language}" href="${escape(new URL(routes[language][kind], siteUrl).href)}">`)}
  <link rel="alternate" hreflang="x-default" href="${escape(new URL(routes['zh-CN'][kind], siteUrl).href)}">` : '';

  return `<!doctype html>
<html lang="${lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escape(title)} | ${escape(siteName)}</title>
  <meta name="description" content="${escape(description)}">${metadata}
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="${relative(path, 'site.css')}">
  <script src="${relative(path, 'site.js')}" defer></script>
</head>
<body>
<a class="skip" href="#main">${escape(copy.skip)}</a>
<header class="site-header">
  <div class="topbar wrap">
    <a class="brand" href="${href('home')}"><span class="brand-mark" aria-hidden="true"></span>${escape(siteName)}</a>
    <nav class="main-nav" aria-label="${escape(copy.navLabel)}">
      <a href="${href('home')}"${kind === 'home' ? ' aria-current="page"' : ''}>${escape(copy.home)}</a>
      <a href="${href('guide')}"${kind === 'guide' ? ' aria-current="page"' : ''}>${escape(copy.guide)}</a>
    </nav>
    <nav class="language-switch" aria-label="${escape(copy.languageLabel)}">${languageLinks}</nav>
  </div>
</header>
<main id="main" tabindex="-1">${kind === 'home' ? renderHome(copy, href) : renderGuide(copy)}</main>
<footer class="footer wrap"><a href="${href('home')}">${escape(siteName)}</a><span>${escape(copy.footer)}</span></footer>
</body>
</html>
`;
}

const pages = new Map();
for (const lang of languages) {
  for (const [kind, path] of Object.entries(routes[lang])) {
    pages.set('/' + path, render(lang, kind));
  }
}

const attributeValues = (html, name) =>
  [...html.matchAll(new RegExp(`\\s${name}="([^"]*)"`, 'g'))].map(match => match[1]);
const translatedSections = html =>
  [...html.matchAll(/\sid="([^"]+)"[^>]*\sdata-translated(?=>|\s)/g)].map(match => match[1]);
for (const [path, html] of pages) {
  const links = [...attributeValues(html, 'href'), ...attributeValues(html, 'src')];
  const ids = attributeValues(html, 'id');
  assert.equal(new Set(ids).size, ids.length, `Duplicate ID in ${path}`);
  const translated = /\shref="([^"]+)" [^>]*data-language-switch/.exec(html);
  assert.ok(translated, `Missing language switch in ${path}`);
  const targetPath = new URL(translated[1], 'https://example.invalid' + path).pathname;
  const paired = pages.get(targetPath);
  assert.ok(path !== targetPath && paired, `Invalid language switch in ${path}`);
  const pairedIds = translatedSections(paired);
  for (const id of translatedSections(html)) {
    assert.ok(pairedIds.includes(id), `Missing paired anchor ${targetPath}#${id}`);
  }
  for (const link of links) {
    if (/^[a-z]+:/i.test(link)) continue;
    const { pathname, hash } = new URL(link, 'https://example.invalid' + path);
    if (['/site.css', '/site.js'].includes(pathname)) continue;
    assert.ok(pages.has(pathname), `Broken link in ${path}: ${link}`);
    assert.ok(!hash || attributeValues(pages.get(pathname), 'id').includes(hash.slice(1)),
      `Broken anchor in ${path}: ${link}`);
  }
}

await mkdir(output, { recursive: true });
for (const name of ['site.css', 'site.js']) {
  await copyFile(new URL(name, import.meta.url), new URL(name, output));
}
for (const [path, html] of pages) {
  const target = new URL('.' + path, output);
  await mkdir(target, { recursive: true });
  await writeFile(new URL('index.html', target), html);
}
console.log(`Built and checked ${pages.size} pages in ${output.pathname}`);
