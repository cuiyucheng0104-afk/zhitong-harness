<script setup lang="ts">
/**
 * 场景二预览：投控异常（02 章 §4.5）。底部工作表页签 汇总 ｜ 异常清单 ｜ 对不准的行（默认异常清单）。
 * 异常清单：分布条（重点段最小宽 28%）→ 未跑规则 → 重点 4 张卡片（内部滚动，终态只展开 A1）；
 * 复核记录抽屉显示 `复核.jsonl` 的逐行记录：自动播放在 `cue: 'record'` 写入 1 行（reviewRecordLine 生成），
 * 手动决定与“重新选择”只追加不改写（与 zt.tk.review 一致）。
 */
import { computed, nextTick, ref, watch } from 'vue';
import ZtPopover from '../ui/ZtPopover.vue';
import SourceRows from './SourceRows.vue';
import { HOTSPOT_TITLES, TK, type Anomaly, type HitlState } from '../../data/demo';
import { formatMoney } from '../../lib/format';
import { onTabKeydown } from '../../lib/navigation';
import { reviewPhaseAt, type CompiledScene } from './engine';
import { autoRecord, foldStates, useDemoContext, type ReviewSheet } from './store';

const props = defineProps<{ compiled: CompiledScene; t: number }>();
const ctx = useDemoContext();
const store = ctx.store;

const cues = computed(() => props.compiled.cues);
const at = (name: keyof CompiledScene['cues']) => cues.value[name] ?? 0;
const sheet = computed<ReviewSheet>(() => store.views.review ?? 'list');
const phase = computed(() => (store.views.review ? 'ready' : reviewPhaseAt(cues.value, props.t)));
const sheets: { id: ReviewSheet; label: string }[] = [
  { id: 'summary', label: '汇总' },
  { id: 'list', label: '异常清单' },
  { id: 'unaligned', label: '对不准的行' },
];

/* 复核记录：自动写入的 1 行（按提问卡决定分支）+ 手动追加。 */
const recordAt = computed(() => at('record'));
const askReasons = computed(() => props.compiled.ask?.spec.reasons);
const records = computed(() => {
  const list = [];
  if (props.t >= recordAt.value && askReasons.value) {
    const d = props.compiled.decision;
    list.push(autoRecord(d, askReasons.value[d], store.askUserTs.value ?? TK.autoRecordTs));
  }
  return [...list, ...store.manualRecords.value];
});
const states = computed(() => foldStates(records.value));
const drawerOpen = computed(() => store.drawer.value ?? props.t >= recordAt.value);

const STATE_LABEL: Record<HitlState, string> = { pending: '待复核', confirmed: '已确认', dismissed: '已判误报' };

/* 分布条：两段按条数比例，但重点段最小宽 28%；重点内部按 2/1/1 分三色。 */
const focusShare = Math.max(0.28, TK.focusCount / TK.total);
const parts = [
  { key: 'duplicate', n: TK.byRule.duplicate, cls: 'is-blue' },
  { key: 'zangu', n: TK.byRule.zangu, cls: 'is-cyan' },
  { key: 'self_check', n: TK.byRule.self_check, cls: 'is-green' },
];

function choose(id: ReviewSheet) {
  ctx.interact();
  store.views.review = id;
}

function toggleCard(a: Anomaly) {
  ctx.interact();
  const list = store.expanded.value;
  store.expanded.value = list.includes(a.anomaly_id) ? list.filter((x) => x !== a.anomaly_id) : [...list, a.anomaly_id];
}

function decide(a: Anomaly, to: HitlState) {
  ctx.interact();
  store.appendDecision(a, states.value[a.anomaly_id] ?? 'pending', to);
  store.drawer.value = true;
}

function toggleDrawer() {
  ctx.interact();
  store.drawer.value = !drawerOpen.value;
}

const popover = ref<InstanceType<typeof ZtPopover> | null>(null);
const rowsFor = ref<Anomaly | null>(null);
function openRows(a: Anomaly, e: MouseEvent) {
  ctx.interact();
  rowsFor.value = a;
  void nextTick(() => popover.value?.show(e.currentTarget as HTMLElement));
}

/* cue 'focus-a1'：A1 高亮并滚入视野。 */
const list = ref<HTMLElement | null>(null);
watch(
  () => props.t >= at('focus-a1') && props.t < recordAt.value,
  (on) => {
    if (!on || !list.value) return;
    const card = list.value.querySelector<HTMLElement>('[data-anomaly-index="0"]');
    if (card) list.value.scrollTop = Math.max(0, card.offsetTop - list.value.offsetTop - 4);
  },
);
</script>

<template>
  <div class="preview review-preview" :data-sheet="sheet" :style="store.views.review ? { '--t': 999 } : undefined">
    <div class="preview-path"><span class="mono">工作/2026-10-19-投控/投控异常.xlsx</span></div>
    <div class="preview-body">
      <template v-if="sheet === 'list'">
        <p v-if="phase === 'empty'" class="preview-empty">结果会出现在这里</p>
        <div v-else-if="phase === 'loading'" class="check-skeleton review-skeleton" aria-hidden="true">
          <i style="width: 92%"></i><i style="width: 76%"></i><i style="width: 84%"></i>
        </div>
        <div v-else class="review-list">
          <div class="dist" :aria-label="`疑似 ${TK.total} 条：重点 ${TK.focusCount}，粗筛 ${TK.screenCount}`" role="img">
            <span class="dist-focus" data-a="scalex" :style="{ '--at': at('distribution'), '--dur': 0.4, width: `${focusShare * 100}%` }">
              <i
                v-for="p in parts"
                :key="p.key"
                :class="p.cls"
                :style="{ width: `${(p.n / TK.focusCount) * 100}%` }"
              ></i>
            </span>
            <span
              class="dist-screen"
              data-a="scalex"
              :style="{ '--at': at('distribution') + 0.4, '--dur': 0.4, width: `${(1 - focusShare) * 100}%` }"
            ></span>
          </div>
          <p class="dist-legend">
            重点 {{ TK.focusCount }}：重复计取 {{ TK.byRule.duplicate }} · 暂估价 {{ TK.byRule.zangu }} · 行内自洽
            {{ TK.byRule.self_check }} ｜ 粗筛 {{ TK.screenCount }}：大额（置信最低）
          </p>
          <p class="rules-skipped">
            未跑（没有合同或中标清单）：<span v-for="label in TK.skippedLabels" :key="label" class="rule-tag" title="baseline_not_provided">{{
              label
            }}</span>
          </p>
          <div ref="list" class="anomaly-list" data-lenis-prevent>
            <article
              v-for="(a, i) in TK.focus"
              :key="a.anomaly_id"
              class="anomaly-card"
              :class="{
                'is-open': store.expanded.value.includes(a.anomaly_id),
                'is-focus': i === 0 && t >= at('focus-a1') && t < recordAt,
                'is-extra': i > 0,
              }"
              :data-anomaly-index="i"
              :data-state="states[a.anomaly_id]"
              data-a="fade up"
              :style="{ '--at': at('focus') + i * 0.1, '--dy': '10px' }"
            >
              <header class="anomaly-head">
                <button
                  type="button"
                  class="anomaly-toggle"
                  :aria-expanded="store.expanded.value.includes(a.anomaly_id)"
                  @click="toggleCard(a)"
                >
                  <span class="anomaly-type">{{ a.anomaly_type }}</span
                  ><span class="anomaly-conf mono">{{ a.confidence_tier }} · {{ a.confidence }}</span>
                  <span class="anomaly-title">{{ a.title }}</span>
                </button>
                <span class="state-pill" :class="`is-${states[a.anomaly_id]}`"
                  ><svg v-if="states[a.anomaly_id] === 'confirmed'" viewBox="0 0 12 12" aria-hidden="true">
                    <path d="m2.5 6.2 2.3 2.3L9.5 3.8" pathLength="1" /></svg
                  >{{ STATE_LABEL[states[a.anomaly_id] ?? 'pending'] }}</span
                >
              </header>
              <p class="anomaly-amount">
                送审金额 <b class="mono">{{ formatMoney(a.line_amount) }}</b> 元 · <span class="manual-badge">需人工确认</span>
              </p>
              <p v-show="store.expanded.value.includes(a.anomaly_id)" class="anomaly-detail">{{ a.detail }}</p>
              <button
                type="button"
                class="anomaly-source"
                :title="HOTSPOT_TITLES['anomaly-source']"
                :data-hotspot-target="i === 0 ? 'anomaly-source' : undefined"
                @click="openRows(a, $event)"
              >
                {{ a.source_file }} · {{ a.sheet }} · 第 {{ a.row }} 行
              </button>
              <div class="anomaly-actions" :title="HOTSPOT_TITLES.decision">
                <template v-if="states[a.anomaly_id] === 'pending'">
                  <button type="button" class="chip-button" :data-decide="`${i}-confirmed`" @click="decide(a, 'confirmed')">确认异常</button>
                  <button type="button" class="chip-button" :data-decide="`${i}-dismissed`" @click="decide(a, 'dismissed')">判为误报</button>
                </template>
                <template v-else>
                  <span class="decided">{{ STATE_LABEL[states[a.anomaly_id]!] }}</span> ·
                  <button type="button" class="chip-link" :data-decide="`${i}-pending`" @click="decide(a, 'pending')">重新选择</button>
                </template>
              </div>
            </article>
          </div>
        </div>
      </template>
      <dl v-else-if="sheet === 'summary'" class="review-summary">
        <div><dt>阈值版本</dt><dd class="mono">{{ TK.rules_version }}</dd></div>
        <div><dt>异常条数</dt><dd class="mono">{{ TK.total }}</dd></div>
        <div>
          <dt>按规则</dt>
          <dd class="mono">
            big_amount {{ TK.byRule.big_amount }}、duplicate {{ TK.byRule.duplicate }}、zangu {{ TK.byRule.zangu }}、self_check
            {{ TK.byRule.self_check }}
          </dd>
        </div>
        <div><dt>合同基准</dt><dd class="mono">{{ TK.baseline.status }}</dd></div>
        <div><dt>基准行数</dt><dd class="mono">{{ TK.baseline.rows }}</dd></div>
        <p class="review-summary-note">引擎只给疑似，终判由造价师逐条复核；金额需人工复核。</p>
      </dl>
      <p v-else class="preview-empty">本轮没有提供合同或中标清单，没有需要人工指定合同行的清单项。</p>
    </div>
    <div class="review-drawer" :class="{ 'is-open': drawerOpen }">
      <button type="button" class="drawer-toggle" :aria-expanded="drawerOpen" aria-controls="review-records" @click="toggleDrawer">
        <span class="mono">复核.jsonl</span> · {{ records.length }} 条
      </button>
      <ol id="review-records" v-show="drawerOpen" class="drawer-lines mono" data-lenis-prevent>
        <li
          v-for="(r, i) in records"
          :key="`${i}-${r.ts}`"
          :data-a="i === 0 && store.manualRecords.value.length === 0 ? 'fade left' : undefined"
          :class="{ 'is-new': i > 0 || store.manualRecords.value.length > 0 }"
          :style="i === 0 ? { '--at': recordAt, '--dx': '-12px' } : undefined"
        >
          {{ r.line }}
        </li>
      </ol>
    </div>
    <p class="review-note">演示记录，仅当前页面有效 · 最终决定由您作出</p>
    <div class="sheet-tabs" role="tablist" aria-label="投控异常.xlsx 工作表" @keydown="onTabKeydown">
      <button
        v-for="s in sheets"
        :key="s.id"
        type="button"
        role="tab"
        class="sheet-tab"
        :aria-selected="sheet === s.id"
        :tabindex="sheet === s.id ? 0 : -1"
        :data-sheet="s.id"
        @click="choose(s.id)"
      >
        {{ s.label }}
      </button>
    </div>
    <ZtPopover
      ref="popover"
      id="demo-source-rows"
      :title="rowsFor ? `${rowsFor.source_file} · ${rowsFor.sheet} · 第 ${rowsFor.row} 行（示例）` : '原表片段（示例）'"
    >
      <SourceRows v-if="rowsFor" :anomaly="rowsFor" data-popover-row />
    </ZtPopover>
  </div>
</template>
