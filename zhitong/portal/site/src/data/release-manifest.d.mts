/** Types for `release-manifest.mjs`, which Node deploy scripts import without a TypeScript step. */

export type ReleasePlatform = 'mac-arm64' | 'win-x64';

/** One platform's installer; `file` is null until an installer is staged. */
export type PlatformRelease =
  | { file: null; sha256: null; size: null; notes: string | null }
  | { file: string; sha256: string; size: number; notes: string | null };

export interface ReleaseManifest {
  schema: 1;
  product: string;
  version: string;
  /** Release date `YYYY-MM-DD`, or null before the first installer is staged. */
  date: string | null;
  /** DeepSeek Harness version the installers are built from, which the app reports as its own version. */
  base: string | null;
  notes: string[];
  platforms: Record<ReleasePlatform, PlatformRelease>;
}

export const RELEASE_MANIFEST_SCHEMA: 1;
export const RELEASE_PLATFORMS: readonly ReleasePlatform[];
export function releaseFileName(platform: ReleasePlatform, version: string): string;
export function parseReleaseManifest(value: unknown): ReleaseManifest;
