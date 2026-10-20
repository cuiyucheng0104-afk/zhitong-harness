import { clientBundle } from '../../../packages/client/tsdown.client.ts'

/**
 * Desktop packaging and development build: the shared Client preset emits the empty Node half as `lib/index.js`
 * and the browser half as `lib/client.js`, which the client module registry serves for this row.
 */
export default clientBundle(import.meta.dirname, ['src/index.ts'])
