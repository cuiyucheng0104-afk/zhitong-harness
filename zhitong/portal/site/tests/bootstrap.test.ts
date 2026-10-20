import { expect, it, vi } from 'vitest';

it('开发入口中仅含预渲染注释时正常挂载，不触发水合错误', async () => {
  document.body.innerHTML = '<div id="app"><!--app-html--></div>';
  const warn = vi.spyOn(console, 'warn');
  const error = vi.spyOn(console, 'error');
  await import('../src/main');
  expect(document.querySelector('h1')?.textContent).toContain('造价咨询公司的');
  expect(warn.mock.calls.some((args) => String(args[0]).includes('Hydration'))).toBe(false);
  expect(error.mock.calls.some((args) => String(args[0]).includes('Hydration'))).toBe(false);
  const root = document.getElementById('app') as HTMLElement & {
    __vue_app__?: { unmount: () => void };
  };
  root.__vue_app__?.unmount();
});
