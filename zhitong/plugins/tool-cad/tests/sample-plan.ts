/**
 * Synthetic building drawing in millimetres: an A1 sheet border at 1:100 with
 * a title block, a ground-floor plan with two rooms, doors and windows (one
 * window nested in a block), a door/window schedule, six dimensions, a solid
 * hatch, a frozen note layer, and a second plan cluster outside the sheet.
 */
import { DxfWriter } from './dxf-writer.ts'

/** Facts the tests assert against. */
export const PLAN = {
  sheet: { x1: 0, y1: 0, x2: 84100, y2: 59400 },
  room1: { name: '卧室', textM2: 30, geomM2: 30 },
  room2: { name: '厨房', textM2: 19.5, geomM2: 20 },
  doors: 3,
  windowsTop: 2,
  windowsNested: 1,
  table: { x1: 45000, y1: 43000, x2: 66000, y2: 46000 },
} as const

/**
 * Build the sample drawing.
 * @param insunits - `$INSUNITS` value, or undefined to omit it.
 * @returns DXF text.
 */
export function samplePlanDxf(insunits?: number): string {
  const w = new DxfWriter(insunits !== undefined ? { insunits } : {})
  w.layer({ name: 'TK', color: 7 })
  w.layer({ name: 'WALL', color: 7 })
  w.layer({ name: 'WINDOW', color: 4 })
  w.layer({ name: 'TXTROOM', color: 3 })
  w.layer({ name: 'HIDDEN_NOTE', color: 1, frozen: true })

  // Sheet border (outer, A1 at 1:100) and inner border.
  w.rect('TK', 0, 0, 84100, 59400)
  w.rect('TK', 2500, 1000, 83100, 58400)
  // Title block.
  w.text('PUB_TEXT', 60000, 5000, 800, '一层平面图')
  w.text('PUB_TEXT', 68000, 5000, 500, '1:100')
  w.text('PUB_TEXT', 60000, 3000, 350, '工程名称')
  w.text('PUB_TEXT', 63000, 3000, 350, '某小区一期 1#楼')
  w.text('PUB_TEXT', 75000, 3000, 350, '图号')
  w.text('PUB_TEXT', 77000, 3000, 350, '建施-03')

  // Plan walls.
  w.rect('WALL', 10000, 15000, 40000, 30000)
  for (let x = 12000; x < 40000; x += 2000) w.line('WALL', x, 15000, x, 20000)
  // Rooms: closed boundaries, names on TXTROOM, area texts.
  w.rect('ROOM', 10000, 15000, 16000, 20000)
  w.text('TXTROOM', 13000, 17500, 300, PLAN.room1.name)
  w.text('PUB_TEXT', 13000, 16800, 250, '30.00')
  w.rect('ROOM', 16000, 15000, 20000, 20000)
  w.text('TXTROOM', 18000, 17500, 300, PLAN.room2.name)
  w.text('PUB_TEXT', 18000, 16800, 250, '19.50')
  w.hatch('HATCH', [[10500, 15500], [11500, 15500], [11500, 16500], [10500, 16500]])

  // Door and window blocks.
  w.line('0', 0, 0, 1000, 0, 'M1021')
  w.line('0', 0, 0, 0, 1000, 'M1021')
  w.line('0', 0, 0, 1500, 0, 'C1518')
  w.line('0', 0, 100, 1500, 100, 'C1518')
  w.insert('WINDOW', 'C1518', 0, 0, { block: 'UNIT' })
  w.line('0', 0, 0, 2000, 0, 'UNIT')
  for (const [x, y] of [[11000, 20000], [17000, 20000], [25000, 20000]] as const) {
    w.insert('DOOR', 'M1021', x, y)
    w.text('WINDOW_TEXT', x + 200, y + 300, 250, 'M1021')
  }
  for (const [x, y] of [[30000, 30000], [34000, 30000]] as const) {
    w.insert('WINDOW', 'C1518', x, y)
    w.text('WINDOW_TEXT', x + 200, y + 300, 250, 'C1518')
  }
  w.insert('WALL', 'UNIT', 36000, 22000)

  // Dimensions: shown value equals the measured length (millimetre drawing).
  const dims: Array<[number, number]> = [[10000, 16000], [16000, 20000], [20000, 26000], [26000, 32000], [32000, 36000], [36000, 40000]]
  for (const [a, b] of dims) w.dimension('DIM', a, 13500, b, b - a, String(b - a))

  // Door/window schedule.
  const xs = [45000, 49000, 55000, 58000, 62000, 66000]
  const ys = [46000, 45000, 44000, 43000]
  for (const y of ys) w.line('TABLE', xs[0]!, y, xs[xs.length - 1]!, y)
  for (const x of xs) w.line('TABLE', x, ys[ys.length - 1]!, x, ys[0]!)
  w.text('TABLE_TEXT', 52000, 46500, 500, '门窗表')
  const rows = [
    ['设计编号', '洞口尺寸', '数量', '图集', '备注'],
    ['M1021', '1000×2100', '3', '12J609', ''],
    ['C1518', '1500×1800', '2', '', '断桥铝'],
  ]
  rows.forEach((row, r) => row.forEach((cell, c) => {
    if (cell !== '') w.text('TABLE_TEXT', xs[c]! + 300, ys[r]! - 700, 300, cell)
  }))

  // Frozen layer content.
  w.text('HIDDEN_NOTE', 30000, 25000, 300, '冻结图层说明')

  // Second plan cluster outside the sheet.
  w.rect('WALL', 150000, 15000, 180000, 30000)
  for (let x = 152000; x < 180000; x += 2000) w.line('WALL', x, 15000, x, 22000)
  w.text('PUB_TEXT', 160000, 12000, 700, '二层平面图')
  w.text('PUB_TEXT', 167000, 12000, 450, '1:100')
  return w.toString()
}
