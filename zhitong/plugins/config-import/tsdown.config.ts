import { defineConfig } from 'tsdown'

/**
 * Desktop packaging build: bundle `src/` into `lib/index.js`, the entry the
 * packed manifest's `publishConfig` exports. Every bare import stays external
 * and resolves from the installed dependency tree.
 */
export default defineConfig({
  entry: ['src/index.ts'],
  outDir: 'lib',
  format: ['esm'],
  platform: 'node',
  target: 'es2024',
  fixedExtension: false,
  dts: false,
  clean: false,
  deps: { neverBundle: [/^[^./]/u] },
})
