import { readFileSync } from 'node:fs';
import { createSSRApp } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { describe, expect, it } from 'vitest';
import App from '../src/App.vue';

describe('静态预渲染首页', () => {
  it('无需执行客户端脚本即可读取全部中文正文与能力内容', async () => {
    const html = await renderToString(createSSRApp(App));
    const document = new DOMParser().parseFromString(html, 'text/html');
    expect(document.querySelectorAll('h1')).toHaveLength(1);
    expect(document.querySelectorAll('.feature-item')).toHaveLength(12);
    expect(document.querySelectorAll('.role-panel')).toHaveLength(3);
    expect(document.querySelectorAll('.faq-item')).toHaveLength(4);
    expect(document.body.textContent).toContain('读取的文件内容会作为对话上下文');
    expect(document.body.textContent).toContain('联系方式待配置');
    expect(document.querySelectorAll('dialog[open]')).toHaveLength(0);
  });

  it('入口保留无脚本可读样式和有效锚点', () => {
    const template = readFileSync('index.html', 'utf8');
    expect(template).toContain('<!--app-html-->');
    expect(template).toContain('.feature-group[hidden]');
    expect(template).toContain('启用 JavaScript 后');
  });
});
