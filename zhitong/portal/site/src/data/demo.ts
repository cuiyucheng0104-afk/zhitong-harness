export const comparisonRows = [
  { name: '混凝土工程', submitted: 1280000, approved: 1235000 },
  { name: '砌筑工程', submitted: 360000, approved: 348000 },
] as const;

export const rooms = [
  { id: 'meeting', name: '会议室', area: '42.00' },
  { id: 'office', name: '办公室', area: '28.00' },
  { id: 'archive', name: '资料室', area: '18.00' },
] as const;

export const sceneTabs = [
  { id: 'check', label: '计价表核对', icon: 'sheet', filename: '核对结果.xlsx' },
  { id: 'review', label: '投控复核', icon: 'shield', filename: '投控复核记录' },
  { id: 'cad', label: 'CAD 看图', icon: 'cad', filename: '图纸阅读结果' },
] as const;

export function formatMoney(value: number) {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}
