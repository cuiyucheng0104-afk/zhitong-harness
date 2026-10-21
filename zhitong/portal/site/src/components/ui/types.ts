/** ui 基础件共用类型（00 章 §8.3）。 */

/** 脚本结果状态：`status` 字段的四个值。 */
export type ResultStatus = 'ok' | 'partial' | 'empty' | 'insufficient';
/** 告警级别。 */
export type AlertLevel = 'error' | 'warn' | 'info';
/** ZtStatus 可显示的全部徽标值（文档行内语法 `status:*`、`level:*` 同此）。 */
export type StatusValue = ResultStatus | AlertLevel | 'manual';

/** 徽标中文名（06 章 §7.12）。 */
export const STATUS_LABEL: Record<StatusValue, string> = {
  ok: '完成',
  partial: '部分完成',
  empty: '无结果',
  insufficient: '资料不足',
  manual: '需人工确认',
  error: '错误',
  warn: '警告',
  info: '提示',
};

export interface StatusLine {
  level: AlertLevel;
  text: string;
}

/** 工具调用条（与 02 章 `ToolSpec` 字段一致）。 */
export interface ToolCallSpec {
  /** 中文标签，如“运行核对”。 */
  label: string;
  /** 等宽原名，如 `reconcile.py run`。 */
  name: string;
  /** 等宽参数摘要（窄屏省略）。 */
  args?: string;
  /** 并发次数，> 1 显示 ×n。 */
  times?: number;
  /** 产品实际耗时量级，如“5.9 s”。 */
  elapsed?: string;
  /** 完成后的结果行。 */
  detail?: string;
  /** 工具返回的警告原文。 */
  warnings?: string[];
}
export type ToolCallState = 'pending' | 'running' | 'done' | 'error';

/** 流式片段：字符串逐字出现；mono 片段整段出现、等宽显示；带 hotspot 的片段可由插槽渲染为按钮。 */
export type StreamSeg = string | { t: string; mono?: boolean; hotspot?: string };

/** 说明卡里“需要什么 / 得到什么”等两行（标签由各章给出）。 */
export interface PopoverRow {
  label: string;
  text: string;
}
