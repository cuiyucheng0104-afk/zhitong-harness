/**
 * Drawing-unit gate. `$INSUNITS` 1/4/5/6 confirms the unit automatically;
 * otherwise the unit stays unconfirmed (millimetres assumed for navigation
 * only) until a person confirms it or a dimension check agrees.
 *
 * The dimension check compares each top-level DIMENSION's measured length
 * (group 42, drawing units) with the number it displays. Chinese building
 * drawings display millimetres, so a ratio of 1 means millimetre units and
 * 1000 means metre units. `DIMLFAC` scaling makes some samples disagree, which
 * is why agreement is reported and a threshold applies.
 *
 * Source of the `$INSUNITS` mapping and the ratio rule: tiangong-cad-viewer
 * `src/main.ts` (`deriveUnit`, `maybeFinishUnitCheck`).
 * @module @zhitong/tool-cad/core/unit
 */
import type { BuiltScene } from './sceneBuilder.ts'

/** Supported drawing units. */
export type UnitName = 'mm' | 'cm' | 'm' | 'in'

/** How the unit was established. */
export type UnitMethod = '$INSUNITS' | '人工确认' | '尺寸比对' | '待确认'

/** Millimetres per drawing unit. */
export const MM_PER_UNIT: Readonly<Record<UnitName, number>> = { mm: 1, cm: 10, m: 1000, in: 25.4 }

const INSUNITS_NAME: Readonly<Record<number, UnitName>> = { 1: 'in', 4: 'mm', 5: 'cm', 6: 'm' }

/** Unit state of one drawing. */
export interface UnitState {
  status: 'confirmed' | 'unconfirmed'
  unit: UnitName
  method: UnitMethod
  confirmedAt: string | null
  /** Free-text basis recorded with a manual confirmation. */
  basis: string | null
}

/** Evidence shown before a unit is confirmed. */
export interface UnitEvidence {
  insunits: number | null
  measurement: number | null
  /** Longest side of the drawing extent in drawing units. */
  extent: number
  dimensionSamples: number
  /** Median of shown ÷ measured over the samples, or null without samples. */
  ratioMedian: number | null
  /** Fraction of samples within 1% of the median ratio. */
  ratioAgreement: number
  /** Unit implied by the median ratio (1 → mm, 10 → cm, 1000 → m), when it is one of those. */
  suggestion: UnitName | null
  /** One-line summary for the model. */
  hint: string
}

/**
 * Initial unit state from the header.
 * @param scene - built scene.
 * @param now - confirmation timestamp source.
 * @returns confirmed from `$INSUNITS`, or unconfirmed millimetres.
 */
export function deriveUnit(scene: Pick<BuiltScene, 'header'>, now: () => Date = () => new Date()): UnitState {
  const iu = scene.header.insunits
  const named = iu !== null ? INSUNITS_NAME[iu] : undefined
  if (named !== undefined) {
    return { status: 'confirmed', unit: named, method: '$INSUNITS', confirmedAt: now().toISOString(), basis: `$INSUNITS=${iu}` }
  }
  return { status: 'unconfirmed', unit: 'mm', method: '待确认', confirmedAt: null, basis: null }
}

/**
 * Collect unit evidence.
 * @param scene - built scene.
 * @returns header values, extent, and the dimension ratio statistics.
 */
export function unitEvidence(scene: Pick<BuiltScene, 'header' | 'bbox' | 'dims'>): UnitEvidence {
  const extent = Math.max(scene.bbox.maxX - scene.bbox.minX, scene.bbox.maxY - scene.bbox.minY)
  const ratios = scene.dims
    .filter(d => d.measured > 0 && d.shown > 0)
    .map(d => d.shown / d.measured)
    .sort((a, b) => a - b)
  const ratioMedian = ratios.length > 0 ? ratios[Math.floor(ratios.length / 2)]! : null
  const ratioAgreement = ratioMedian !== null && ratios.length > 0
    ? ratios.filter(r => Math.abs(r / ratioMedian - 1) < 0.01).length / ratios.length
    : 0
  let suggestion: UnitName | null = null
  if (ratioMedian !== null) {
    if (Math.abs(ratioMedian - 1) < 0.01) suggestion = 'mm'
    else if (Math.abs(ratioMedian / 10 - 1) < 0.01) suggestion = 'cm'
    else if (Math.abs(ratioMedian / 1000 - 1) < 0.015) suggestion = 'm'
  }
  const parts = [`$INSUNITS=${scene.header.insunits ?? '缺失'}`]
  parts.push(extent > 20000 ? `图幅跨度约 ${(extent / 1000).toFixed(0)}k 单位，建筑图按惯例疑似 mm` : `图幅跨度约 ${extent.toFixed(0)} 单位`)
  if (ratioMedian !== null) {
    parts.push(`${ratios.length} 个尺寸标注的「显示值÷实测长度」中位数 ${ratioMedian.toFixed(3)}，一致率 ${(ratioAgreement * 100).toFixed(0)}%`
      + (suggestion !== null ? `，指向 ${suggestion}` : ''))
  } else {
    parts.push('没有可比对的尺寸标注')
  }
  return {
    insunits: scene.header.insunits,
    measurement: scene.header.measurement,
    extent,
    dimensionSamples: ratios.length,
    ratioMedian,
    ratioAgreement,
    suggestion,
    hint: parts.join('；'),
  }
}

/**
 * Decimal places for coordinates in a unit (1 mm resolution).
 * @param unit - drawing unit.
 * @returns decimal places.
 */
export function coordDecimals(unit: UnitName): number {
  return Math.max(0, Math.round(Math.log10(MM_PER_UNIT[unit])))
}
