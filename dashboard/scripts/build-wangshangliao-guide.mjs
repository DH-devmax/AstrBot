import { readFileSync, mkdirSync, writeFileSync, copyFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import MarkdownIt from 'markdown-it';

const markdown = new MarkdownIt({ html: false, linkify: false });
const output = fileURLToPath(new URL('../public/local-docs/', import.meta.url));
mkdirSync(output, { recursive: true });
mkdirSync(`${output}images`, { recursive: true });
copyFileSync(new URL('../../docs/zh/platform/images/wangshangliao-directory-labels.jpg', import.meta.url), `${output}images/wangshangliao-directory-labels.jpg`);
copyFileSync(new URL('../../docs/zh/platform/images/wangshangliao-group-labels.jpg', import.meta.url), `${output}images/wangshangliao-group-labels.jpg`);
copyFileSync(new URL('../../docs/zh/platform/images/wangshangliao-cards-narrow.jpg', import.meta.url), `${output}images/wangshangliao-cards-narrow.jpg`);
copyFileSync(new URL('../../docs/public/images/wangshangliao/architecture.svg', import.meta.url), `${output}architecture.svg`);
copyFileSync(new URL('../../docs/public/images/wangshangliao/architecture-layers.svg', import.meta.url), `${output}architecture-layers.svg`);
for (const language of ['zh', 'en']) {
  const source = readFileSync(new URL(`../../docs/${language}/platform/wangshangliao.md`, import.meta.url), 'utf8');
  // Dashboard-local guides omit VitePress-only image paths.
  const content = markdown.render(source.replace('/images/wangshangliao/architecture-layers.svg', 'architecture-layers.svg').replace('/images/wangshangliao/architecture.svg', 'architecture.svg').replace(/^!\[[^\]]*\]\(\/images\/[^\n]+\)\s*$/gm, ''));
  const title = language === 'zh' ? '旺商聊接入教程' : 'Wangshangliao setup guide';
  writeFileSync(`${output}wangshangliao${language === 'en' ? '-en' : ''}.html`, `<!doctype html>
<html lang="${language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${title}</title>
<style>body{font:17px/1.7 system-ui,sans-serif;max-width:900px;margin:32px auto;padding:0 20px;color:#202633}pre{overflow:auto;background:#f2f4f8;padding:16px;border-radius:8px}code{overflow-wrap:anywhere}a{color:#245bcc}table{border-collapse:collapse}td,th{border:1px solid #ddd;padding:8px}img{max-width:100%}</style></head><body><nav><a href="../#/platforms">AstrBot</a> · <a href="wangshangliao.html">中文</a> · <a href="wangshangliao-en.html">English</a></nav>${content}</body></html>`);
}
