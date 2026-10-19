/**
 * Types for the ES build of `@mlightcad/shx-parser`. The package has no
 * `exports` map and its `main` CommonJS build exports nothing under Node ESM,
 * so the plugin imports `dist/index.es.js`, which carries the same API as the
 * package root typings.
 */
declare module '@mlightcad/shx-parser/dist/index.es.js' {
  export * from '@mlightcad/shx-parser'
}
