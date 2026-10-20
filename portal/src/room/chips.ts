import type { Box, RoomSize } from '../run'

/** The sizes the chips are drawn at. The component and the fit check read the same numbers. */
export const CHIP_TYPE: Readonly<Record<RoomSize, { readonly text: number; readonly line: number; readonly from: number; readonly fromLine: number }>> = {
  wide: { text: 16, line: 20, from: 12, fromLine: 16 },
  compact: { text: 14, line: 18, from: 12, fromLine: 16 },
}

export const CHIP_FRAME = { border: 1, padX: 12, padY: 8, icon: 14, iconGap: 4, gap: 6 } as const

/** Instrument Sans at weight 620 sets digits at about 0.6 em and its widest capital at 0.72 em, so this over-estimates every chip. */
const EM_PER_CHAR = 0.72

export function chipFootprint(item: string, size: RoomSize): { readonly w: number; readonly h: number } {
  const type = CHIP_TYPE[size]
  const f = CHIP_FRAME
  return {
    w: 2 * f.border + 2 * f.padX + f.icon + f.iconGap + Math.ceil(item.length * type.text * EM_PER_CHAR),
    h: 2 * f.border + 2 * f.padY + type.line,
  }
}

/** Whether the chips, wrapped into rows no wider than the spot, fit under the From line. The real chips are narrower, so they fit too. */
export function chipsFit(items: readonly string[], spot: Box, size: RoomSize, withFrom: boolean): boolean {
  const f = CHIP_FRAME
  let rows = 1
  let rowW = 0
  let chipH = 0
  for (const item of items) {
    const { w, h } = chipFootprint(item, size)
    if (w > spot.w) return false
    chipH = h
    const widened = rowW === 0 ? w : rowW + f.gap + w
    if (widened > spot.w) {
      rows += 1
      rowW = w
    } else {
      rowW = widened
    }
  }
  const fromH = withFrom ? CHIP_TYPE[size].fromLine + f.gap : 0
  return fromH + rows * chipH + (rows - 1) * f.gap <= spot.h
}
