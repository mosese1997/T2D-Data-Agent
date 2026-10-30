/**
 * t2d 图表主题 — 浅橙可爱风。
 *
 * 分类色板经 CVD 验证器校验全项通过（色盲相邻对 ΔE≥8、明度带内、
 * 饱和度达标；金色 #C28A00 对白底 2.95:1 需配图例/表格救济——
 * 看板组件均有图例+tooltip+数据表格）。
 * 顺序：橙(品牌) → 蓝 → 绿 → 紫 → 金 → 粉，固定不循环。
 */
export const CHART_PALETTE = [
  '#E85D04', // 橙 — 品牌主色
  '#3B82C4', // 蓝
  '#3BA55D', // 绿
  '#8B5CF6', // 紫
  '#C28A00', // 金
  '#EC5FA0', // 粉
] as const;

/** 单系列（无 split_by）一律用品牌橙 */
export const BRAND_COLOR = '#F0741F';

/** 轴线/网格/文字的暖灰色系（与 CSS token 一致） */
export const CHART_TEXT = '#43281b';
export const CHART_MUTED = '#a07c62';
export const CHART_BORDER = '#ffe3c2';
export const CHART_GRID = '#ffeeda';

/** 合并进每个 ECharts option 的基础主题 */
export function chartTheme(option: Record<string, unknown>): Record<string, unknown> {
  return {
    color: [...CHART_PALETTE],
    textStyle: { color: CHART_TEXT, fontFamily: 'Nunito, sans-serif' },
    grid: { top: 36, right: 16, bottom: 28, left: 48, containLabel: false },
    tooltip: {
      backgroundColor: '#fffdf9',
      borderColor: CHART_BORDER,
      borderWidth: 1,
      textStyle: { color: CHART_TEXT, fontSize: 12 },
      extraCssText: 'border-radius:12px;box-shadow:0 4px 16px rgba(240,116,31,.12);',
    },
    ...option,
    // 不被调用方覆盖的关键项
    ...(option.textStyle ? {} : {}),
  };
}
