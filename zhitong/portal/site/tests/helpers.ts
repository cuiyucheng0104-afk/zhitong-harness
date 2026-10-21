/** 测试工具：带真实路由（内存 history）挂载组件或整站。 */
import { mount, flushPromises } from '@vue/test-utils';
import type { Component } from 'vue';
import { createMemoryHistory } from 'vue-router';
import App from '../src/App.vue';
import { createAppRouter } from '../src/router';
import { vMagnetic } from '../src/composables/useMagnetic';
import { vSpotlight } from '../src/composables/useSpotlight';

/**
 * 在给定路径上挂载组件（默认整站 App）。
 * @param path - 初始路径。
 * @param component - 要挂载的组件。
 * @param options - 透传给 mount 的 props。
 * @returns wrapper 与 router。
 */
export async function mountAt(path = '/', component: Component = App, props: Record<string, unknown> = {}) {
  const router = createAppRouter(createMemoryHistory());
  await router.push(path);
  await router.isReady();
  const wrapper = mount(component, {
    props,
    attachTo: document.body,
    global: { plugins: [router], directives: { magnetic: vMagnetic, spotlight: vSpotlight } },
  });
  await flushPromises();
  return { wrapper, router };
}
