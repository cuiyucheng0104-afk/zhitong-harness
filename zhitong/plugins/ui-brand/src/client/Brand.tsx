/**
 * 智通数工AI artwork: the brand mark of `zhitong/brand/brand-mark.svg` (blue gradient rounded square, white cross,
 * green dashes) drawn inline, and a text wordmark. The mark carries its own fixed colors and needs no asset URL, so
 * it renders the same in the browser, the packaged desktop app, and both themes. The wordmark draws with the
 * `--dsw-alias-label-primary` theme token, so each theme gets a readable color without a second asset.
 */
import { useId } from 'react'
import type { TranslateNS } from '@deepseek-ai/dsh-client-ui-slots'
import type { BrandNamespace } from './index.ts'

/** Mark presentation requested by the hosting slot. */
export interface BrandMarkProps {
  /** Requested square edge in pixels. */
  size: number
  /** Host class preserving the surrounding mark geometry (conversation hero only). */
  className?: string | undefined
}

/** Wordmark presentation; the sidebar passes no owner values. */
export interface BrandNameProps {
  /** Brand dictionary seat. */
  t: TranslateNS<BrandNamespace>
}

/**
 * Render the brand mark. Each instance owns its gradient id: the sidebar draws the mark twice (expanded and
 * collapsed rails), and a `url(#id)` reference resolving into a hidden duplicate would paint nothing.
 * @param props - requested size and optional host class.
 * @returns an SVG mark sized to the request.
 */
export function ZhitongBrandMark({ size, className }: BrandMarkProps) {
  const gradient = `zhitong-brand-${useId().replace(/[^A-Za-z0-9_-]/g, '')}`
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
          <stop stopColor="#00B3EC" />
          <stop offset="1" stopColor="#0666F5" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="17" fill={`url(#${gradient})`} />
      <g transform="rotate(-43 32 32)" strokeLinecap="round">
        <path d="M15 32h10m14 0h10M32 15v10m0 14v10" stroke="#FFF" strokeWidth="7.5" />
        <path d="M17 19h5m20 0h5M17 45h5m20 0h5" stroke="#12D99F" strokeWidth="5" />
      </g>
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
