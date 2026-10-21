<script setup lang="ts">
/**
 * 场景一预览：核对底稿（02 章 §3.4）。模拟打开 `核对结果.xlsx`：汇总、按章汇总、逐行核对三张工作表；
 * 视图随时间线切换（2.15 文件卡 → 3.80 汇总 → 6.00 按章 → 8.25 逐行 → 10.30 回到汇总），也可点底部工作表页签手动切换（进入手动模式）。
 * 预览宽度 < 560px 时（容器查询）逐行表的送审/审定位置合并为一列，匹配依据隐藏；手机只列精简行（§3.5）。
 */
import { computed, ref } from 'vue';
import AppIcon from '../AppIcon.vue';
import ZtStatus from '../ui/ZtStatus.vue';
import ZtPopover from '../ui/ZtPopover.vue';
import { HOTSPOT_TITLES, RECONCILE } from '../../data/demo';
import { formatInt, formatMoney, formatPercent } from '../../lib/format';
import { onTabKeydown } from '../../lib/navigation';
import { checkViewAt, clamp01, easeExpo, type CompiledScene } from './engine';
import { useDemoContext, type CheckSheet } from './store';

const props = defineProps<{ compiled: CompiledScene; t: number }>();
const ctx = useDemoContext();
const S = RECONCILE.summary;

const cues = computed(() => props.compiled.cues);
const at = (name: keyof CompiledScene['cues']) => cues.value[name] ?? 0;
const override = computed(() => ctx.store.views.check);
const view = computed(() => override.value ?? checkViewAt(cues.value, props.t));
const sheets: { id: CheckSheet; label: string }[] = [
  { id: 'summary', label: '汇总' },
  { id: 'chapters', label: '按章汇总' },
  { id: 'rows', label: '逐行核对' },
];

/* 汇总：4 个数字滚动（useCountUp 的时间线版：真实值节点保持终值，滚动值写在 aria-hidden 副本里）。 */
const countP = computed(() => (override.value ? 1 : clamp01((props.t - at('summary')) / 0.8)));
const counting = computed(() => countP.value > 0 && countP.value < 1 && props.t >= at('summary'));
const counted = (to: number, fmt: (v: number) => string) => fmt(to * easeExpo(countP.value));
const numbers = computed(() => ({
  reduction: counted(S.adjust_amount, (v) => formatMoney(v)),
  rate: counted(S.adjust_rate, (v) => formatPercent(v)),
  a: counted(S.a_total, (v) => formatMoney(v)),
  b: counted(S.b_total, (v) => formatMoney(v)),
}));
const qtyShare = S.diff_by_qty / (S.diff_by_qty + S.diff_by_price);

const totals = {
  count: RECONCILE.chapters.reduce((s, c) => s + c.count, 0),
  a: RECONCILE.chapters.reduce((s, c) => s + c.a_amount, 0),
  b: RECONCILE.chapters.reduce((s, c) => s + c.b_amount, 0),
  adjust: RECONCILE.chapters.reduce((s, c) => s + c.adjust, 0),
};

type Row = (typeof RECONCILE.rows)[number];
const qtyText = (v: number, unit: string) => formatMoney(v, unit === 't' ? 3 : 2);
function rowMark(r: Row) {
  if (r.calc_flags.length) return r.calc_flags.join('、');
  if (r.diff_by_qty) return `量差 ${formatMoney(r.diff_by_qty)}`;
  if (r.diff_by_price) return `价差 ${formatMoney(r.diff_by_price)}`;
  return '—';
}
function rowDetail(r: Row): string[] {
  const a = `送审 ${qtyText(r.submitted_qty, r.unit)} ${r.unit} × ${formatMoney(r.submitted_price)} = ${formatMoney(r.submitted_amount)}`;
  if (r.approved_qty === null || r.approved_price === null) return [a, '审定 —（仅送审，审定表无此行）', `核减额 ${formatMoney(r.diff)}`];
  const b = `审定 ${qtyText(r.approved_qty, r.unit)} ${r.unit} × ${formatMoney(r.approved_price)} = ${formatMoney(r.approved_amount)}`;
  const lines = [a, b];
  if (r.calc_flags.length)
    lines.push(`送审合价与量×价（${formatMoney(r.submitted_qty * r.submitted_price)}）不符，已标记「${r.calc_flags.join('、')}」`);
  else lines.push(`量差 ${formatMoney(r.diff_by_qty ?? 0)}；价差 ${formatMoney(r.diff_by_price ?? 0)}`);
  return lines;
}

const popover = ref<InstanceType<typeof ZtPopover> | null>(null);
const detailRow = ref<Row | null>(null);
function openRow(r: Row, e: Event) {
  ctx.interact();
  detailRow.value = r;
  popover.value?.show(e.currentTarget as HTMLElement);
}

function choose(id: CheckSheet) {
  ctx.interact();
  ctx.store.views.check = id;
}

function openSource(e: MouseEvent) {
  ctx.openSource(e.currentTarget as HTMLElement);
}

/** 段落 2 播放时前 3 章依次底色闪（每行 0.4 s，错开 0.3 s），在 7 行落格之后开始。 */
const flashAt = (i: number) => at('chapters') + 0.7 + i * 0.3;
</script>

<template>
  <div class="preview check-preview" :data-view="view" :style="override ? { '--t': 999 } : undefined">
    <div class="preview-path">
      <span class="mono">工作/2026-10-19-核对/核对结果.xlsx</span>
    </div>
    <div class="preview-body">
      <p v-show="view === 'empty'" class="preview-empty">结果会出现在这里</p>

      <div v-show="view === 'files'" class="check-files">
        <p class="check-files-dir mono"><AppIcon name="folder" />资料/4 结算资料/</p>
        <div
          v-for="(f, i) in RECONCILE.inputs"
          :key="f.name"
          class="file-card"
          data-a="fade up"
          :style="{ '--at': at('files') + i * 0.07, '--dy': '-12px' }"
        >
          <AppIcon name="sheet" />
          <span class="file-card-name">{{ f.name }}</span>
          <span class="file-card-size mono">{{ f.size }}</span>
          <span class="file-card-tag" data-a="pop-spring" :style="{ '--at': at('probe') }">计价表 · kind={{ f.kind }}</span>
        </div>
        <div class="check-skeleton" data-a="fade" :style="{ '--at': at('loading') }" aria-hidden="true">
          <i style="width: 92%"></i><i style="width: 76%"></i><i style="width: 84%"></i>
        </div>
      </div>

      <div v-show="view === 'summary'" class="check-summary">
        <div class="summary-hero">
          <button
            type="button"
            class="amount-button"
            :title="HOTSPOT_TITLES.reduction"
            :aria-label="`核减额 ${formatMoney(S.adjust_amount)} 元，查看出处`"
            data-hotspot-target="reduction"
            data-source-amount
            @click="openSource"
          >
            <span class="amount-label">核减额（正=审减）</span>
            <span class="amount-value mono" :class="{ 'is-counting': counting }"
              >{{ formatMoney(S.adjust_amount) }}<span v-if="counting" class="count-up-shadow" aria-hidden="true">{{
                numbers.reduction
              }}</span></span
            ><span class="amount-unit">元</span>
          </button>
          <div class="rate-box">
            <span class="amount-label">核减率</span>
            <span class="rate-value mono" :class="{ 'is-counting': counting }"
              >{{ formatPercent(S.adjust_rate)
              }}<span v-if="counting" class="count-up-shadow" aria-hidden="true">{{ numbers.rate }}</span></span
            >
          </div>
        </div>
        <dl class="summary-totals">
          <div>
            <dt>送审合计</dt>
            <dd class="mono" :class="{ 'is-counting': counting }">
              {{ formatMoney(S.a_total) }}<span v-if="counting" class="count-up-shadow" aria-hidden="true">{{ numbers.a }}</span>
            </dd>
          </div>
          <div>
            <dt>审定合计</dt>
            <dd class="mono" :class="{ 'is-counting': counting }">
              {{ formatMoney(S.b_total) }}<span v-if="counting" class="count-up-shadow" aria-hidden="true">{{ numbers.b }}</span>
            </dd>
          </div>
          <span class="summary-unit">（元）</span>
        </dl>
        <p class="summary-counts">
          逐行 <b class="mono">{{ formatInt(S.count_total) }}</b>：一致 {{ formatInt(S.count_same) }} · 调整 {{ S.count_changed }} · 仅送审
          {{ S.count_only_a }} · 仅审定 {{ S.count_only_b }} · 待核实 {{ S.count_uncertain }}
        </p>
        <div class="qp-bar" aria-hidden="true">
          <i class="qp-qty" data-a="scalex" :style="{ '--at': at('summary'), '--dur': 0.45, width: `${qtyShare * 100}%` }"></i
          ><i class="qp-price" data-a="scalex" :style="{ '--at': at('summary') + 0.12, '--dur': 0.45, width: `${(1 - qtyShare) * 100}%` }"></i>
        </div>
        <p class="qp-legend">
          <span><i class="qp-dot qp-dot-qty"></i>量差 <b class="mono">{{ formatMoney(S.diff_by_qty) }}</b></span>
          <span><i class="qp-dot qp-dot-price"></i>价差 <b class="mono">{{ formatMoney(S.diff_by_price) }}</b></span>
        </p>
        <p class="summary-basis">
          对比口径 {{ S.basis }} · 送审取数 {{ S.basis_label.submitted }} · 审定取数 {{ S.basis_label.approved }}
        </p>
        <div class="summary-status" data-a="fade up" :style="{ '--at': at('warnings') }">
          <ZtStatus value="ok" manual />
          <ul class="summary-warnings" :aria-label="`告警 ${RECONCILE.warnings.length} 条`">
            <li
              v-for="(w, i) in RECONCILE.warnings"
              :key="i"
              :class="`tone-${w.level}`"
              data-a="fade up"
              :style="{ '--at': at('warnings') + i * 0.07 }"
            >
              <ZtStatus :value="w.level" size="sm" /><code class="mono">{{ w.code }}</code
              ><span v-if="w.file" class="warn-file">{{ w.file }}</span><span class="warn-text">{{ w.message }}</span>
            </li>
          </ul>
        </div>
      </div>

      <div v-show="view === 'chapters'" class="check-chapters">
        <table class="demo-table">
          <caption class="sr-only">按章汇总，金额单位元</caption>
          <thead>
            <tr><th>章</th><th>章名</th><th class="num">行数</th><th class="num">送审</th><th class="num">审定</th><th class="num">核减额</th></tr>
          </thead>
          <tbody>
            <tr
              v-for="(ch, i) in RECONCILE.chapters"
              :key="ch.chapter"
              :class="{ 'is-extra': i >= 3 }"
              data-a="fade up"
              :style="{ '--at': at('chapters') + i * 0.06, '--dy': '-8px', '--fa': flashAt(i) }"
              :data-flash="i < 3 ? 'true' : undefined"
            >
              <td class="mono">{{ ch.chapter }}</td>
              <td>{{ ch.chapter_name }}</td>
              <td class="num mono">{{ ch.count }}</td>
              <td class="num mono">{{ formatMoney(ch.a_amount) }}</td>
              <td class="num mono">{{ formatMoney(ch.b_amount) }}</td>
              <td class="num mono" :class="ch.adjust >= 0 ? 'is-reduce' : 'is-increase'">
                {{ formatMoney(ch.adjust) }}<small>{{ ch.adjust >= 0 ? '核减' : '核增' }}</small>
              </td>
            </tr>
            <tr class="is-total" data-a="fade up" :style="{ '--at': at('chapters') + 6 * 0.06, '--dy': '-8px' }">
              <td></td>
              <td>合计</td>
              <td class="num mono">{{ formatInt(totals.count) }}</td>
              <td class="num mono">{{ formatMoney(totals.a) }}</td>
              <td class="num mono">{{ formatMoney(totals.b) }}</td>
              <td class="num mono is-reduce">{{ formatMoney(totals.adjust) }}</td>
            </tr>
          </tbody>
        </table>
        <i class="total-rule" data-a="scalex" :style="{ '--at': at('chapters') + 6 * 0.06 + 0.1 }" aria-hidden="true"></i>
      </div>

      <div v-show="view === 'rows'" class="check-rows">
        <p class="rows-title">按 |核减额| 排序 · 示例只列前 3 行与 1 行计算错误标记</p>
        <table class="demo-table rows-table">
          <caption class="sr-only">逐行核对，金额单位元</caption>
          <thead>
            <tr>
              <th>状态</th><th>项目编码</th><th>项目名称</th><th class="col-split">送审位置</th><th class="col-split">审定位置</th
              ><th class="col-merged">位置</th><th class="num">核减额</th><th class="col-match">匹配依据</th><th>标记</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(r, i) in RECONCILE.rows"
              :key="r.item_code"
              :class="{ 'is-extra': i >= 3, 'is-flash': i === 0 && ctx.store.flashRow.value > 0 }"
              :data-flash-key="i === 0 ? ctx.store.flashRow.value : undefined"
              data-a="fade up"
              :style="{ '--at': at('rows') + i * 0.06, '--dy': '-8px' }"
              :title="`送审：${r.submitted_sheet} · 第 ${r.submitted_row} 行；审定：${r.approved_sheet ? `${r.approved_sheet} · 第 ${r.approved_row} 行` : '—'}`"
              tabindex="0"
              :data-row="i"
              @click="openRow(r, $event)"
              @keydown.enter.prevent="openRow(r, $event)"
              @keydown.space.prevent="openRow(r, $event)"
            >
              <td>{{ r.status }}</td>
              <td class="mono">{{ r.item_code }}</td>
              <td>{{ r.item_name }}（{{ r.feature }}）</td>
              <td class="col-split">{{ r.submitted_sheet }} · <span class="mono">{{ r.submitted_row }}</span></td>
              <td class="col-split">
                <template v-if="r.approved_sheet">{{ r.approved_sheet }} · <span class="mono">{{ r.approved_row }}</span></template
                ><template v-else>—</template>
              </td>
              <td class="col-merged mono">{{ r.submitted_row }} → {{ r.approved_row ?? '—' }}</td>
              <td class="num mono is-reduce">{{ formatMoney(r.diff) }}</td>
              <td class="col-match">{{ r.matched_by ?? '—' }}</td>
              <td :class="{ 'is-flag': r.calc_flags.length }">{{ rowMark(r) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div
      class="sheet-tabs"
      role="tablist"
      aria-label="核对结果.xlsx 工作表"
      :title="HOTSPOT_TITLES['sheet-tabs']"
      data-hotspot-target="sheet-tabs"
      @keydown="onTabKeydown"
    >
      <button
        v-for="s in sheets"
        :key="s.id"
        type="button"
        role="tab"
        class="sheet-tab"
        :aria-selected="view === s.id"
        :tabindex="view === s.id || (view === 'empty' || view === 'files' ? s.id === 'summary' : false) ? 0 : -1"
        :data-sheet="s.id"
        @click="choose(s.id)"
      >
        {{ s.label }}
      </button>
    </div>
    <ZtPopover ref="popover" id="demo-row-detail" :title="detailRow ? `${detailRow.item_name} · ${detailRow.item_code}` : '逐行核对'">
      <ul v-if="detailRow" class="row-detail mono" data-popover-row>
        <li v-for="line in rowDetail(detailRow)" :key="line">{{ line }}</li>
      </ul>
      <p class="row-detail-note" data-popover-row>
        送审 {{ detailRow?.submitted_sheet }} · 第 {{ detailRow?.submitted_row }} 行；审定
        {{ detailRow?.approved_sheet ? `${detailRow.approved_sheet} · 第 ${detailRow.approved_row} 行` : '—' }}（示例）
      </p>
    </ZtPopover>
  </div>
</template>
