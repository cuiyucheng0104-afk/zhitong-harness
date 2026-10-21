import { describe, expect, it, vi } from 'vitest';
import { flushPromises } from '@vue/test-utils';
import { createMemoryHistory } from 'vue-router';
import { render } from '../src/entry-server';
import { createPortalApp } from '../src/create-app';

describe('预渲染页水合（01 §13 首次载入不播放过渡）', () => {
  it.each(['/', '/docs/install/', '/privacy/', '/__not_found__/'])('%s 水合无不匹配警告', async (path) => {
    const { html } = await render(path);
    document.body.innerHTML = `<div id="app">${html}</div>`;
    const warn = vi.spyOn(console, 'warn');
    const error = vi.spyOn(console, 'error');
    const { app, router } = createPortalApp(createMemoryHistory(), true);
    await router.push(path);
    await router.isReady();
    app.mount('#app');
    await flushPromises();
    const msgs = [...warn.mock.calls, ...error.mock.calls].map((a) => String(a[0]));
    expect(msgs.filter((m) => /hydrat/i.test(m))).toEqual([]);
    app.unmount();
  });
});
