/**
 * Release manifest (`public/downloads/releases.json`): which installers the portal offers.
 *
 * The site imports the manifest at build time and renders a download link only for a platform whose `file` is set;
 * `zhitong/portal/deploy/release-manifest.mjs` fills `file`, `sha256` and `size` from a built installer and checks
 * the files before upload. Both read it through `parseReleaseManifest`, so a manifest that names a file under any
 * other name, or a file without its checksum, fails the build and the upload instead of producing a broken link.
 */

/** Manifest format version this module reads. */
export const RELEASE_MANIFEST_SCHEMA = 1;

/** Platforms the portal offers, in display order. */
export const RELEASE_PLATFORMS = /** @type {const} */ (['mac-arm64', 'win-x64']);

/** Published file name suffix per platform; the version precedes it. */
const FILE_SUFFIX = {
  'mac-arm64': 'mac-arm64.dmg',
  'win-x64': 'win-x64-setup.exe',
};

const VERSION = /^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const SHA256 = /^[0-9a-f]{64}$/;

/**
 * Published installer name for one platform and version, e.g. `ztsgai-1.0.0-mac-arm64.dmg`.
 * @param {import('./release-manifest.mjs').ReleasePlatform} platform - Platform id.
 * @param {string} version - Product version from the manifest.
 * @returns {string} File name under `/downloads/`.
 */
export function releaseFileName(platform, version) {
  return `ztsgai-${version}-${FILE_SUFFIX[platform]}`;
}

/**
 * Throw a manifest error naming the offending field.
 * @param {string} path - Field path.
 * @param {string} message - What is wrong.
 * @returns {never}
 */
function fail(path, message) {
  throw new Error(`releases.json: ${path} ${message}`);
}

/**
 * @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Read one platform entry.
 * @param {unknown} value - Entry from `platforms`.
 * @param {import('./release-manifest.mjs').ReleasePlatform} platform - Its key.
 * @param {string} version - Manifest version the file name must carry.
 * @returns {import('./release-manifest.mjs').PlatformRelease}
 */
function parsePlatform(value, platform, version) {
  const path = `platforms.${platform}`;
  if (!isRecord(value)) fail(path, 'must be an object');
  const notes = value.notes ?? null;
  if (notes !== null && typeof notes !== 'string')
    fail(`${path}.notes`, 'must be a string or null');
  const { file, sha256, size } = value;
  if (file === null || file === undefined) {
    if ((sha256 ?? null) !== null || (size ?? null) !== null) {
      fail(path, 'has sha256 or size without a file');
    }
    return { file: null, sha256: null, size: null, notes };
  }
  const expected = releaseFileName(platform, version);
  if (file !== expected) fail(`${path}.file`, `must be ${expected} for version ${version}`);
  if (typeof sha256 !== 'string' || !SHA256.test(sha256)) {
    fail(`${path}.sha256`, 'must be 64 lowercase hexadecimal characters');
  }
  if (typeof size !== 'number' || !Number.isSafeInteger(size) || size <= 0) {
    fail(`${path}.size`, 'must be a positive byte count');
  }
  return { file: expected, sha256, size, notes };
}

/**
 * Validate a parsed `releases.json`.
 * @param {unknown} value - JSON value.
 * @returns {import('./release-manifest.mjs').ReleaseManifest} The manifest with every platform present.
 * @throws {Error} When a field is missing, malformed, or names a file other than the expected one.
 */
export function parseReleaseManifest(value) {
  if (!isRecord(value)) fail('root', 'must be an object');
  if (value.schema !== RELEASE_MANIFEST_SCHEMA)
    fail('schema', `must be ${RELEASE_MANIFEST_SCHEMA}`);
  const { product, version, date, base, notes, platforms } = value;
  if (typeof product !== 'string' || product === '') fail('product', 'must be a non-empty string');
  if (typeof version !== 'string' || !VERSION.test(version)) fail('version', 'must be x.y.z');
  if (date !== null && (typeof date !== 'string' || !DATE.test(date))) {
    fail('date', 'must be YYYY-MM-DD or null');
  }
  if (base !== undefined && typeof base !== 'string') fail('base', 'must be a string');
  if (notes !== undefined && (!Array.isArray(notes) || notes.some((n) => typeof n !== 'string'))) {
    fail('notes', 'must be an array of strings');
  }
  if (!isRecord(platforms)) fail('platforms', 'must be an object');
  for (const key of Object.keys(platforms)) {
    if (!RELEASE_PLATFORMS.includes(/** @type {never} */ (key)))
      fail(`platforms.${key}`, 'is not a known platform');
  }
  /** @type {Record<string, import('./release-manifest.mjs').PlatformRelease>} */
  const parsed = {};
  for (const platform of RELEASE_PLATFORMS) {
    parsed[platform] = parsePlatform(platforms[platform] ?? {}, platform, version);
  }
  return {
    schema: RELEASE_MANIFEST_SCHEMA,
    product,
    version,
    date,
    base: base ?? null,
    notes: notes ?? [],
    platforms: /** @type {import('./release-manifest.mjs').ReleaseManifest['platforms']} */ (
      parsed
    ),
  };
}
