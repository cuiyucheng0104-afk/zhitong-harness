<script setup lang="ts">
/**
 * 使用流程示例会话的终态 DOM（05 章 §1.2.1）。每拍一个 `[data-beat]` 元素；节拍动画由 `scene-timeline.ts` 排出。
 * 场景内只有非交互元素（选项、文件条都是 span/div）；示意指针、飞入文件卡 `aria-hidden`。
 * `elapsed` 为 null 时（预渲染、减少动效、动效未加载）流式文字显示终态。
 */
import { computed } from 'vue';
import AppIcon from '../../AppIcon.vue';
import ZtToolCall from '../../ui/ZtToolCall.vue';
import ZtStream from '../../ui/ZtStream.vue';
import ZtStatus from '../../ui/ZtStatus.vue';
import {
  BUCKET_PROJECTS,
  CASE_INDEX,
  DIFF_PROJECT_DOC,
  INVENTORY_CARD,
  OUTPUT_FILES,
  RECONCILE_CARD,
  type WorkflowStep,
} from '../../../data/workflow';
import { formatMoney, formatPercent } from '../../../lib/format';
import { formatMs, planScene, WF_STREAM_CPS, WF_STREAM_PAUSE } from './scene-plan';

const props = withDefaults(defineProps<{ step: WorkflowStep; elapsed?: number | null }>(), {
  elapsed: null,
});

const slots = computed(() => planScene(props.step.scene).slots);
const streamTime = (i: number) =>
  props.elapsed === null ? undefined : Math.max(-1, props.elapsed - slots.value[i]!.start);
const fmtFigure = (f: (typeof RECONCILE_CARD.figures)[number]) =>
  f.format === 'percent' ? formatPercent(f.value) : formatMoney(f.value);
const lastProjects = BUCKET_PROJECTS.slice(-4);
</script>

<template>
  <div class="wf-stage">
    <svg class="wf-pointer" viewBox="0 0 20 20" aria-hidden="true">
      <path d="M3 2v14l4-3.5 2.6 5.5 2.4-1.1-2.6-5.4H15z" />
    </svg>
    <template v-for="(beat, i) in step.scene" :key="`d${i}`">
      <div v-if="beat.kind === 'drop'" class="wf-drop" :data-beat="i" aria-hidden="true">
        <span class="wf-drop-card"
          ><AppIcon name="archive" /><span class="mono">{{ beat.file }}</span
          ><span class="wf-drop-size mono">{{ beat.size }}</span></span
        >
      </div>
    </template>
    <div class="wf-body">
      <div class="wf-msgs" aria-live="off">
        <template v-for="(beat, i) in step.scene" :key="i">
          <div v-if="beat.kind === 'user'" class="wf-beat wf-user" :data-beat="i">
            <div class="wf-bubble">
              <span v-if="beat.attachment" class="wf-attach"
                ><AppIcon name="archive" /><span class="mono">{{ beat.attachment }}</span></span
              >
              <p>{{ beat.text }}</p>
            </div>
          </div>

          <div
            v-else-if="beat.kind === 'tool'"
            class="wf-beat wf-tool"
            :data-beat="i"
            :title="beat.title"
          >
            <span class="wf-tool-spin" aria-hidden="true"></span>
            <ZtToolCall
              :tool="{ label: beat.label, name: beat.command, elapsed: formatMs(beat.ms) }"
              state="done"
            />
            <p v-if="beat.result" class="wf-tool-result mono">{{ beat.result }}</p>
          </div>

          <div v-else-if="beat.kind === 'stream'" class="wf-beat wf-stream" :data-beat="i">
            <ZtStream
              :text="beat.text"
              :cps="WF_STREAM_CPS"
              :pause="WF_STREAM_PAUSE"
              :time="streamTime(i)"
            />
          </div>

          <div v-else-if="beat.kind === 'status'" class="wf-beat wf-status" :data-beat="i">
            <ZtStatus
              :value="beat.status"
              :counts="beat.counts"
              :manual="beat.manual"
              :lines="beat.lines?.map((text) => ({ level: 'warn' as const, text }))"
            />
          </div>

          <div
            v-else-if="beat.kind === 'card'"
            :class="['wf-beat', 'wf-card', `wf-card-${beat.card}`]"
            :data-beat="i"
          >
            <template v-if="beat.card === 'projects'">
              <p class="wf-card-title mono" data-row>tos://zt-demo/示例咨询/项目/</p>
              <ul class="wf-projects">
                <li
                  v-for="(name, k) in BUCKET_PROJECTS"
                  :key="name"
                  class="mono"
                  :class="{
                    'wf-wide-only': k < BUCKET_PROJECTS.length - 4,
                    'is-picked': k === BUCKET_PROJECTS.length - 1,
                  }"
                  :data-pick="k === BUCKET_PROJECTS.length - 1 ? '' : undefined"
                  data-row
                >
                  [目录] {{ name }}/
                </li>
                <li class="wf-narrow-only wf-projects-more" aria-hidden="true">
                  另 {{ BUCKET_PROJECTS.length - lastProjects.length }} 个目录
                </li>
              </ul>
            </template>

            <template v-else-if="beat.card === 'inventory'">
              <p class="wf-card-title" data-row>{{ INVENTORY_CARD.title }}</p>
              <p class="wf-card-metric mono" data-row>{{ INVENTORY_CARD.metric }}</p>
              <dl class="wf-inventory">
                <div v-for="row in INVENTORY_CARD.rows" :key="row.label" data-row>
                  <dt>{{ row.label }}</dt>
                  <dd>
                    <template v-for="(part, k) in row.parts" :key="k"
                      ><code v-if="part.mono" class="mono">{{ part.t }}</code
                      ><template v-else>{{ part.t }}</template></template
                    >
                  </dd>
                </div>
              </dl>
              <p class="wf-card-foot" data-row>{{ INVENTORY_CARD.footnote }}</p>
            </template>

            <template v-else-if="beat.card === 'reconcile'">
              <dl class="wf-figures" data-row>
                <div v-for="f in RECONCILE_CARD.figures" :key="f.label">
                  <dt>{{ f.label }}</dt>
                  <dd class="mono">
                    <span class="wf-count">
                      <span class="wf-count-value" :data-count="f.value" :data-format="f.format">{{
                        fmtFigure(f)
                      }}</span
                      ><span class="wf-count-live" aria-hidden="true"></span> </span
                    ><span v-if="f.unit" class="wf-unit">{{ f.unit }}</span>
                  </dd>
                </div>
              </dl>
              <ul class="wf-bars" data-row>
                <li
                  v-for="b in RECONCILE_CARD.bars"
                  :key="b.name"
                  :class="{ 'is-increase': b.kind === '核增' }"
                >
                  <span class="wf-bar-name">{{ b.name }}</span>
                  <span class="wf-bar-track" aria-hidden="true"
                    ><span
                      class="wf-bar-fill"
                      :style="{ width: `${(b.ratio * 100).toFixed(1)}%` }"
                    ></span
                  ></span>
                  <span class="wf-bar-value mono">{{ b.kind }} {{ b.amount }}</span>
                </li>
              </ul>
              <p class="wf-card-rows mono" data-row>{{ RECONCILE_CARD.rows }}</p>
            </template>

            <template v-else>
              <ul class="wf-files">
                <li v-for="f in OUTPUT_FILES" :key="f" data-row>
                  <AppIcon name="file" /><span class="mono">{{ f }}</span>
                </li>
              </ul>
            </template>
          </div>

          <div v-else-if="beat.kind === 'ask'" class="wf-beat wf-ask" :data-beat="i">
            <p class="wf-ask-title">{{ beat.title }}</p>
            <ul class="wf-ask-lines">
              <li v-for="line in beat.lines" :key="line">{{ line }}</li>
            </ul>
            <div class="wf-ask-options">
              <span
                v-for="(opt, k) in beat.options"
                :key="opt"
                class="wf-ask-opt"
                :data-picked="k === beat.pick ? 'true' : undefined"
                >{{ opt }}</span
              >
            </div>
          </div>

          <div v-else-if="beat.kind === 'push'" class="wf-beat wf-push" :data-beat="i">
            <p class="wf-push-title mono">{{ beat.title }}</p>
            <ul>
              <li
                v-for="(row, k) in beat.rows"
                :key="row.path"
                :class="{ 'wf-wide-only': beat.rows.length > 3 && k < 3, 'is-folded': !row.size }"
                data-row
              >
                <span class="wf-push-path mono">{{ row.path }}</span>
                <span v-if="row.size" class="wf-push-size mono">{{ row.size }}</span>
                <span v-if="row.size" class="wf-push-ok"><AppIcon name="check" />回读校验通过</span>
                <span v-if="row.note" class="wf-push-note">{{ row.note }}</span>
              </li>
              <li v-if="beat.rows.length > 3" class="wf-narrow-only" aria-hidden="true">
                <span class="wf-push-path mono">成果/ 3 个文件</span
                ><span class="wf-push-size mono">1.3 MiB</span>
              </li>
            </ul>
          </div>

          <div v-else-if="beat.kind === 'diff'" class="wf-beat wf-diff" :data-beat="i">
            <p class="wf-diff-file mono">{{ beat.file }}</p>
            <ol v-if="beat.file === '项目说明.md'" class="wf-diff-lines mono">
              <li
                v-for="(line, k) in DIFF_PROJECT_DOC"
                :key="k"
                :class="`op-${line.op === '+' ? 'ins' : line.op === '-' ? 'del' : 'ctx'}`"
              >
                <span v-if="line.op === '+'" class="wf-ins-bg" aria-hidden="true"></span>
                <span class="wf-diff-op" aria-hidden="true">{{
                  line.op === ' ' ? '' : line.op === '-' ? '−' : '+'
                }}</span
                ><span class="sr-only">{{
                  line.op === '-' ? '删除：' : line.op === '+' ? '插入：' : ''
                }}</span
                ><span class="wf-diff-text"
                  >{{ line.text
                  }}<span v-if="line.op === '-'" class="wf-strike" aria-hidden="true"></span
                ></span>
              </li>
            </ol>
            <template v-else>
              <div class="wf-case-table" role="table" aria-label="案例索引.md">
                <div class="wf-case-row is-head" role="row">
                  <span v-for="c in CASE_INDEX.columns" :key="c" role="columnheader">{{ c }}</span>
                </div>
                <div class="wf-case-row is-context" role="row">
                  <span v-for="(c, k) in CASE_INDEX.context" :key="k" role="cell">{{ c }}</span>
                </div>
                <div class="wf-case-row is-changed" role="row">
                  <span
                    v-for="(c, k) in CASE_INDEX.after"
                    :key="k"
                    role="cell"
                    :class="{ 'is-swap': CASE_INDEX.changed.includes(k) }"
                  >
                    <template v-if="CASE_INDEX.changed.includes(k)"
                      ><span class="wf-cell-old" aria-hidden="true">{{
                        CASE_INDEX.before[k] || ' '
                      }}</span
                      ><span class="wf-cell-new">{{ c }}</span></template
                    >
                    <template v-else>{{ c }}</template>
                  </span>
                </div>
              </div>
              <dl class="wf-case-fields">
                <div
                  v-for="(c, k) in CASE_INDEX.columns"
                  :key="c"
                  :class="{ 'is-swap': CASE_INDEX.changed.includes(k) }"
                >
                  <dt>{{ c }}</dt>
                  <dd>
                    <template v-if="CASE_INDEX.changed.includes(k)"
                      ><span class="wf-cell-old" aria-hidden="true">{{
                        CASE_INDEX.before[k] || ' '
                      }}</span
                      ><span class="wf-cell-new">{{ CASE_INDEX.after[k] }}</span></template
                    >
                    <template v-else>{{ CASE_INDEX.after[k] }}</template>
                  </dd>
                </div>
              </dl>
            </template>
          </div>

          <div v-else-if="beat.kind === 'note'" class="wf-beat wf-note" :data-beat="i">
            <svg
              class="wf-note-lead"
              viewBox="0 0 24 40"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <path d="M2 0 V20 H24" />
            </svg>
            <div class="wf-note-box">
              <p class="wf-note-title mono">{{ beat.title }}</p>
              <ul>
                <li v-for="row in beat.rows" :key="row.field" data-row>
                  <code class="mono">{{ row.field }}</code
                  ><span class="wf-note-value">{{ row.value }}</span
                  ><AppIcon name="check" class="wf-note-ok" />
                </li>
              </ul>
              <p class="wf-note-foot">{{ beat.footnote }}</p>
            </div>
          </div>

          <div v-else-if="beat.kind === 'outcome'" class="wf-beat wf-outcome" :data-beat="i">
            <span class="mono">{{ beat.text }}</span>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
