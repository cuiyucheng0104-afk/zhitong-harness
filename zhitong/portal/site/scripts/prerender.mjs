import { readFile, writeFile, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { render } from '../.ssr/entry-server.js';

const output = new URL('../dist/index.html', import.meta.url);
const template = await readFile(output, 'utf8');
if (!template.includes('<!--app-html-->')) throw new Error('缺少预渲染插入点');
const html = await render();
if (!html.includes('智通数工') || !html.includes('feature-group-calculate'))
  throw new Error('首页预渲染内容不完整');
await writeFile(output, template.replace('<!--app-html-->', html));
await rm(new URL('../.ssr/', import.meta.url), { recursive: true, force: true });
console.log(`已预渲染中文首页：${fileURLToPath(output)}`);
