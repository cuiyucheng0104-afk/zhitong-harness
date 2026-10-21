import { defineConfig } from 'vitest/config';
import vue from '@vitejs/plugin-vue';
import { docsPlugin } from './build/docs-plugin';

export default defineConfig({
  base: '/',
  // 文档正文 .md 由 docsPlugin（06 章 §3.3）编译成 SFC，再交给 vue 插件。
  plugins: [...docsPlugin(), vue({ include: [/\.vue$/, /\.md$/] })],
  build: {
    target: 'es2022',
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['tests/setup.ts'],
    include: ['tests/**/*.test.ts'],
    restoreMocks: true,
  },
});
