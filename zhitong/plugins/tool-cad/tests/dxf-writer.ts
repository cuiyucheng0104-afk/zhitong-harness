/**
 * Minimal ASCII DXF writer for synthetic fixtures: HEADER, a LAYER table,
 * BLOCKS, and ENTITIES with LINE, closed LWPOLYLINE, TEXT, INSERT, DIMENSION,
 * and solid HATCH. Handles are assigned sequentially.
 */

type Pair = readonly [number, string | number]

export interface LayerDef { name: string; color: number; frozen?: boolean; off?: boolean }

export class DxfWriter {
  private handle = 0x100
  private readonly entities: Pair[][] = []
  private readonly blocks: Array<{ name: string; entities: Pair[][] }> = []
  private readonly layers = new Map<string, LayerDef>()

  constructor(private readonly header: { insunits?: number; acadver?: string; codepage?: string } = {}) {}

  private nextHandle(): string {
    return (this.handle++).toString(16).toUpperCase()
  }

  layer(def: LayerDef): this {
    this.layers.set(def.name, def)
    return this
  }

  private target(block?: string): Pair[][] {
    if (block === undefined) return this.entities
    let b = this.blocks.find(x => x.name === block)
    if (b === undefined) { b = { name: block, entities: [] }; this.blocks.push(b) }
    return b.entities
  }

  private ensureLayer(name: string): void {
    if (!this.layers.has(name)) this.layers.set(name, { name, color: 7 })
  }

  line(layer: string, x1: number, y1: number, x2: number, y2: number, block?: string): string {
    this.ensureLayer(layer)
    const h = this.nextHandle()
    this.target(block).push([[0, 'LINE'], [5, h], [8, layer], [10, x1], [20, y1], [30, 0], [11, x2], [21, y2], [31, 0]])
    return h
  }

  rect(layer: string, x1: number, y1: number, x2: number, y2: number, block?: string): string {
    return this.polyline(layer, [[x1, y1], [x2, y1], [x2, y2], [x1, y2]], true, block)
  }

  polyline(layer: string, pts: ReadonlyArray<readonly [number, number]>, closed: boolean, block?: string): string {
    this.ensureLayer(layer)
    const h = this.nextHandle()
    const pairs: Pair[] = [[0, 'LWPOLYLINE'], [5, h], [8, layer], [90, pts.length], [70, closed ? 1 : 0]]
    for (const [x, y] of pts) pairs.push([10, x], [20, y])
    this.target(block).push(pairs)
    return h
  }

  text(layer: string, x: number, y: number, height: number, value: string, options: { rot?: number; block?: string } = {}): string {
    this.ensureLayer(layer)
    const h = this.nextHandle()
    this.target(options.block).push([[0, 'TEXT'], [5, h], [8, layer], [10, x], [20, y], [30, 0], [40, height], [1, value], [50, options.rot ?? 0]])
    return h
  }

  insert(layer: string, name: string, x: number, y: number, options: { rot?: number; scale?: number; block?: string } = {}): string {
    this.ensureLayer(layer)
    const h = this.nextHandle()
    const s = options.scale ?? 1
    this.target(options.block).push([[0, 'INSERT'], [5, h], [8, layer], [2, name], [10, x], [20, y], [30, 0], [41, s], [42, s], [43, s], [50, options.rot ?? 0]])
    return h
  }

  /** A linear dimension whose anonymous block shows `shown` and whose group 42 is `measured`. */
  dimension(layer: string, x1: number, y: number, x2: number, measured: number, shown: string): string {
    this.ensureLayer(layer)
    const blockName = `*D${this.blocks.length + 1}`
    this.line(layer, x1, y, x2, y, blockName)
    this.text(layer, (x1 + x2) / 2, y + 100, 250, shown, { block: blockName })
    const h = this.nextHandle()
    this.entities.push([[0, 'DIMENSION'], [5, h], [8, layer], [2, blockName], [10, x2], [20, y], [30, 0], [11, (x1 + x2) / 2], [21, y + 100], [31, 0], [70, 32], [42, measured], [1, ''], [13, x1], [23, y], [33, 0], [14, x2], [24, y], [34, 0]])
    return h
  }

  /** A solid hatch with one external polyline boundary. */
  hatch(layer: string, pts: ReadonlyArray<readonly [number, number]>): string {
    this.ensureLayer(layer)
    const h = this.nextHandle()
    const pairs: Pair[] = [[0, 'HATCH'], [5, h], [8, layer], [10, 0], [20, 0], [30, 0], [2, 'SOLID'], [70, 1], [71, 0], [91, 1], [92, 3], [72, 0], [73, 1], [93, pts.length]]
    for (const [x, y] of pts) pairs.push([10, x], [20, y])
    pairs.push([97, 0], [75, 0], [76, 1], [98, 0])
    this.entities.push(pairs)
    return h
  }

  toString(): string {
    const out: string[] = []
    const emit = (pairs: readonly Pair[]): void => {
      for (const [code, value] of pairs) out.push(String(code).padStart(3, ' '), String(value))
    }
    emit([[0, 'SECTION'], [2, 'HEADER'], [9, '$ACADVER'], [1, this.header.acadver ?? 'AC1015']])
    if (this.header.insunits !== undefined) emit([[9, '$INSUNITS'], [70, this.header.insunits]])
    if (this.header.codepage !== undefined) emit([[9, '$DWGCODEPAGE'], [3, this.header.codepage]])
    emit([[0, 'ENDSEC']])
    emit([[0, 'SECTION'], [2, 'TABLES'], [0, 'TABLE'], [2, 'LAYER'], [70, this.layers.size]])
    for (const l of this.layers.values()) {
      emit([[0, 'LAYER'], [2, l.name], [70, l.frozen === true ? 1 : 0], [62, l.off === true ? -l.color : l.color], [6, 'CONTINUOUS']])
    }
    emit([[0, 'ENDTAB'], [0, 'ENDSEC']])
    emit([[0, 'SECTION'], [2, 'BLOCKS']])
    for (const b of this.blocks) {
      emit([[0, 'BLOCK'], [5, this.nextHandle()], [8, '0'], [2, b.name], [70, b.name.startsWith('*') ? 1 : 0], [10, 0], [20, 0], [30, 0], [3, b.name]])
      for (const e of b.entities) emit(e)
      emit([[0, 'ENDBLK'], [5, this.nextHandle()], [8, '0']])
    }
    emit([[0, 'ENDSEC']])
    emit([[0, 'SECTION'], [2, 'ENTITIES']])
    for (const e of this.entities) emit(e)
    emit([[0, 'ENDSEC'], [0, 'EOF']])
    return `${out.join('\n')}\n`
  }
}
