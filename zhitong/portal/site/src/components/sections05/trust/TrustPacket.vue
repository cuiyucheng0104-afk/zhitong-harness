<script setup lang="ts">
/**
 * 数据包图形（05 章 §2.2 图例），以 (0, 0) 为中心。五类靠形状区分：
 * 文件 20×14 圆角矩形两条横线；金额 半径 9 的圆内“¥”；凭据 22×12 钥匙；回复 圆角矩形三条短横线；成果 圆角矩形内对勾。
 * `amountEcho` 是虚线圆（脚本结果原值，模型只转述）。用于 SVG 内部，也用于图例（`standalone` 时包一层 svg）。
 */
import type { PacketKind } from './trust-geometry';

withDefaults(defineProps<{ kind: PacketKind; standalone?: boolean }>(), { standalone: false });
</script>

<template>
  <svg
    v-if="standalone"
    class="trust-legend-icon"
    viewBox="-12 -10 24 20"
    width="24"
    height="20"
    aria-hidden="true"
  >
    <TrustPacket :kind="kind" />
  </svg>
  <g v-else :class="['trust-shape', `shape-${kind}`]">
    <template v-if="kind === 'file'">
      <rect x="-10" y="-7" width="20" height="14" rx="3" />
      <path class="trust-shape-line" d="M-6 -2 H6 M-6 2.5 H3" />
    </template>
    <template v-else-if="kind === 'amount'">
      <circle r="9" />
      <text class="trust-shape-glyph" y="4" text-anchor="middle">¥</text>
    </template>
    <template v-else-if="kind === 'amountEcho'">
      <circle r="9" />
      <text class="trust-shape-glyph" y="4" text-anchor="middle">¥</text>
    </template>
    <template v-else-if="kind === 'credential'">
      <circle class="trust-key-ring" cx="-6" cy="0" r="4.5" />
      <path class="trust-key-bar" d="M-1.5 0 H11 M7 0 V4 M10 0 V3" />
    </template>
    <template v-else-if="kind === 'reply'">
      <rect x="-10" y="-7" width="20" height="14" rx="3" />
      <path class="trust-shape-line" d="M-6 -3 H6 M-6 0 H4 M-6 3 H2" />
    </template>
    <template v-else>
      <rect x="-10" y="-7" width="20" height="14" rx="3" />
      <path class="trust-shape-line" d="M-4.5 0 L-1.5 3 L4.5 -3" />
    </template>
  </g>
</template>
