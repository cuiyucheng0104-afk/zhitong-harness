/** 数字格式（00 章 §7.4）：千分位、金额两位小数。 */

/**
 * 金额或面积格式化。
 * @param value - 数值。
 * @param digits - 小数位，默认 2。
 * @returns 如 `906,692.96`；负数前加 `−`（U+2212）。
 */
export function formatMoney(value: number, digits = 2): string {
  const text = Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  return value < 0 ? `−${text}` : text;
}

/**
 * 比例格式化。
 * @param ratio - 0.0297 这样的比例。
 * @param digits - 小数位，默认 2。
 * @returns 如 `2.97%`。
 */
export function formatPercent(ratio: number, digits = 2): string {
  return `${(ratio * 100).toFixed(digits)}%`;
}

/**
 * 整数千分位。
 * @param value - 数值，四舍五入到整数。
 * @returns 如 `1,284`。
 */
export function formatInt(value: number): string {
  return Math.round(value).toLocaleString('en-US');
}
