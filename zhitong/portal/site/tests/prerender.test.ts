import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { render, routes, launchIssues } from '../src/entry-server';

describe('静态预渲染', () => {
  it('首页无需执行客户端脚本即可读取全部中文正文与能力内容', async () => {
    const { html, head, status, layout } = await render('/');
    expect(status).toBe(200);
    expect(layout).toBe('home');
    expect(head).toContain('<title>智通数工AI · 造价咨询公司的对话式工作台</title>');
    const document = new DOMParser().parseFromString(html, 'text/html');
    expect(document.querySelectorAll('h1')).toHaveLength(1);
    expect(document.querySelectorAll('.feature-item')).toHaveLength(12);
    expect(document.querySelectorAll('.role-panel')).toHaveLength(3);
    expect(document.querySelectorAll('.faq-item').length).toBeGreaterThanOrEqual(4);
    // 05 §2.2 模型说明。
    expect(document.body.textContent).toContain('对话中读取的文件内容（包括交给模型看的扫描页和图纸图片）会作为对话上下文发送给所配置的模型服务');
    expect(document.querySelectorAll('dialog[open]')).toHaveLength(0);
    expect(document.querySelector('.site-header')?.getAttribute('data-state')).toBe('top');
  });

  it('AC-01-23：首页只输出已填的电话，无任何占位字样', async () => {
    const { html } = await render('/');
    expect(html).not.toContain('联系方式待配置');
    expect(html).not.toContain('18201566868');
    expect(html).toContain('13355715800');
  });

  it('入口保留无脚本可读样式、预渲染插入点与 head 占位', () => {
    const template = readFileSync('index.html', 'utf8');
    expect(template).toContain('<!--app-html-->');
    expect(template).toContain('<!--app-head-->');
    expect(template).not.toContain('<title>');
    expect(template).toContain('.feature-group[hidden]');
    expect(template).toContain('启用 JavaScript 后');
  });

  it('上线检查：当前配置无阻断项', () => {
    const issues = launchIssues();
    expect(issues).toEqual([]);
    expect(routes).toContain('/privacy/');
  });
});
