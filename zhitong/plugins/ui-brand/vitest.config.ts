import { fileURLToPath } from 'node:url'
import tsconfigPaths from 'vite-tsconfig-paths'
import { defineConfig } from 'vitest/config'

// Workspace imports resolve to upstream sources through the root tsconfig `paths`, as in the repository suite.
const baseTsconfig = fileURLToPath(new URL('../../../tsconfig.base.json', import.meta.url))

export default defineConfig({
  plugins: [tsconfigPaths({ projects: [baseTsconfig] })],
  test: {
    include: ['tests/**/*.spec.{ts,tsx}'],
    pool: 'forks',
  },
})
