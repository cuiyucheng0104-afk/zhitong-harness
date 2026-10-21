<script setup lang="ts">
/**
 * 原表片段（02 章 §4.6），放在 ZtPopover 内：列 行、项目编码、项目名称、项目特征、单位、工程量、综合单价、合价
 * （防火门表另有“其中：暂估价”）；被引用行底色 `--warning-bg`、左侧 2px `--warning-text` 竖线；
 * 行号不连续处插一行“…”。桌面宽 560px，横向超出时内部滚动。
 */
import { computed } from 'vue';
import type { Anomaly, SourceRow } from '../../data/demo';

const props = defineProps<{ anomaly: Anomaly }>();

const hasProvisional = computed(() => props.anomaly.source.rows.some((r) => r.provisional));
/** 行号与上一行不连续时前面插省略行。 */
const items = computed(() => {
  const out: ({ gap: true; key: string } | { gap: false; key: string; row: SourceRow })[] = [];
  props.anomaly.source.rows.forEach((row, i, arr) => {
    const prev = arr[i - 1];
    if (prev && row.row - prev.row > 1) out.push({ gap: true, key: `gap-${row.row}` });
    out.push({ gap: false, key: String(row.row), row });
  });
  return out;
});
/** 被引用行：本异常所在行（另一条同组的命中行也标出，便于对照）。 */
const isCited = (r: SourceRow) => r.row === props.anomaly.row || r.hit === true;
</script>

<template>
  <div class="source-rows" data-lenis-prevent>
    <table class="demo-table">
      <caption class="sr-only">{{ anomaly.source.sheet }}片段，第 {{ anomaly.row }} 行为本条异常</caption>
      <thead>
        <tr>
          <th class="num">行</th><th>项目编码</th><th>项目名称</th><th>项目特征</th><th>单位</th><th class="num">工程量</th
          ><th class="num">综合单价</th><th class="num">合价</th><th v-if="hasProvisional" class="num">其中：暂估价</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="item in items" :key="item.key">
          <tr v-if="item.gap" class="is-gap">
            <td :colspan="hasProvisional ? 9 : 8">…</td>
          </tr>
          <tr v-else :class="{ 'is-cited': isCited(item.row), 'is-self': item.row.row === anomaly.row }">
            <td class="num mono">{{ item.row.row }}</td>
            <td class="mono">{{ item.row.code }}</td>
            <td>{{ item.row.name }}</td>
            <td>{{ item.row.feature }}</td>
            <td>{{ item.row.unit }}</td>
            <td class="num mono">{{ item.row.qty }}</td>
            <td class="num mono">{{ item.row.price }}</td>
            <td class="num mono">{{ item.row.amount }}</td>
            <td v-if="hasProvisional" class="num mono">{{ item.row.provisional ?? '—' }}</td>
          </tr>
        </template>
      </tbody>
    </table>
    <p class="source-rows-note">行号即 <code class="mono">rows[].row</code>；表中数字为示例。</p>
  </div>
</template>
