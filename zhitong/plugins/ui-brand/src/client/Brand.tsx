/**
 * Placeholder 智通数工AI artwork: a rounded square carrying one glyph, and a text wordmark. Both draw with theme
 * alias tokens, so the light and dark themes each get their own colors without a second asset. A designer replaces
 * the two components below (and the matching static files in `assets/`) with final artwork.
 */
import type { TranslateNS } from '@deepseek-ai/dsh-client-ui-slots'
import type { BrandNamespace } from './index.ts'

/** Mark presentation requested by the hosting slot. */
export interface BrandMarkProps {
  /** Requested square edge in pixels. */
  size: number
  /** Host class preserving the surrounding mark geometry (conversation hero only). */
  className?: string | undefined
  /** Brand dictionary seat. */
  t: TranslateNS<BrandNamespace>
}

/** Wordmark presentation; the sidebar passes no owner values. */
export interface BrandNameProps {
  /** Brand dictionary seat. */
  t: TranslateNS<BrandNamespace>
}

/**
 * Render the square mark.
 * @param props - requested size, optional host class, and the brand dictionary.
 * @returns an SVG mark sized to the request.
 */
export function ZhitongBrandMark({ size, className, t }: BrandMarkProps) {
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <rect x="0" y="0" width="24" height="24" rx="6" style={{ fill: 'var(--dsw-alias-brand-primary)' }} />
      <text
        x="12" y="17.2" textAnchor="middle" fontSize="15" fontWeight="700"
        style={{ fill: 'var(--dsw-alias-brand-primary-invert)' }}
      >{t('markGlyph')}</text>
    </svg>
  )
}

/**
 * Render the text wordmark without the independently slotted mark.
 * @param props - the brand dictionary.
 * @returns an SVG wordmark 24 pixels high.
 */
export function ZhitongBrandName({ t }: BrandNameProps) {
  return (
    <svg width="104" height="24" viewBox="0 0 104 24" aria-hidden="true" focusable="false">
      <text
        x="0" y="18" fontSize="17" fontWeight="600" textLength="102" lengthAdjust="spacingAndGlyphs"
        style={{ fill: 'var(--dsw-alias-label-primary)' }}
      >{t('name')}</text>
    </svg>
  )
}
