<script setup lang="ts">
/**
 * 确认提问卡（02 章 §4.4，对应 `ask_user_question`）。
 * - 自动播放：模拟指针选中“确认异常”→ 理由逐字写入 → 点“提交”→ 到标签 `ask:submitted` 收起为一行；
 * - 手动：用户选项后理由框预填示例理由（只读，标“示例理由”），未选时“提交”禁用；提交后时间线跳到 `ask:submitted` 按所选分支播放后半段；
 * - 手机与减少动效：直接显示已提交状态（§10.2）。
 */
import { computed } from 'vue';
import type { HitlState } from '../../data/demo';
import { typedText, type AskTimeline } from './engine';

const props = defineProps<{
  ask: AskTimeline;
  t: number;
  /** 已生效的决定（提交后的分支）。 */
  decision: HitlState;
  /** 用户在卡上点过的选项；null 表示未操作（按自动播放显示）。 */
  choice: HitlState | null;
  /** 直接显示已提交状态（手机、减少动效）。 */
  instant: boolean;
}>();
const emit = defineEmits<{ choose: [value: HitlState]; submit: [value: HitlState] }>();

const submitted = computed(() => props.t >= (props.instant ? props.ask.at : props.ask.submitted));
const auto = computed(() => props.choice === null);
const selected = computed<HitlState | null>(() => {
  if (!auto.value) return props.choice;
  const o = props.ask.option;
  return o && props.t >= o.at + o.dur ? 'confirmed' : null;
});
const reason = computed(() => {
  if (!auto.value) return props.choice ? props.ask.spec.reasons[props.choice] : '';
  const ty = props.ask.type;
  return ty ? typedText(ty.text, ty.at, ty.dur, props.t) : '';
});
const typing = computed(() => {
  const ty = props.ask.type;
  return auto.value && !!ty && props.t >= ty.at && props.t < ty.at + ty.dur;
});
/** 模拟点击时目标按下 0.12 s（§10.2 `.is-pressed`）。 */
const pressed = (step: AskTimeline['option']) => !!step && auto.value && props.t >= step.at + step.dur && props.t < step.at + step.dur + 0.12;
const answer = computed(() => {
  const opt = props.ask.spec.options.find((o) => o.value === props.decision)!;
  return `您的回答：${opt.label} · ${props.ask.spec.reasons[props.decision]}`;
});

function onKey(e: KeyboardEvent, i: number) {
  const opts = props.ask.spec.options;
  let next = i;
  if (e.key === 'ArrowDown' || e.key === 'ArrowRight') next = (i + 1) % opts.length;
  else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') next = (i - 1 + opts.length) % opts.length;
  else return;
  e.preventDefault();
  emit('choose', opts[next]!.value);
  const group = (e.currentTarget as HTMLElement).parentElement;
  (group?.children[next] as HTMLElement | undefined)?.focus();
}
</script>

<template>
  <div class="ask-card" :class="{ 'is-submitted': submitted }" data-ask-card data-hotspot-target="decision" title="由您判定">
    <div class="ask-head">
      <span>{{ ask.spec.header }}</span><code class="mono">{{ ask.spec.tool }}</code>
    </div>
    <template v-if="!submitted">
      <p class="ask-question">{{ ask.spec.question }}</p>
      <p class="ask-detail">{{ ask.spec.detail }}</p>
      <div class="ask-options" role="radiogroup" :aria-label="ask.spec.question">
        <button
          v-for="(opt, i) in ask.spec.options"
          :key="opt.value"
          type="button"
          role="radio"
          class="ask-option"
          :class="{ 'is-selected': selected === opt.value, 'is-pressed': opt.value === 'confirmed' && pressed(ask.option) }"
          :aria-checked="selected === opt.value"
          :tabindex="(selected ?? 'confirmed') === opt.value ? 0 : -1"
          :data-ask-option="opt.value"
          @click="emit('choose', opt.value)"
          @keydown="onKey($event, i)"
        >
          <span class="ask-radio" aria-hidden="true"></span><span class="ask-option-label">{{ opt.label }}</span
          ><span class="ask-option-desc"> — {{ opt.description }}</span>
        </button>
      </div>
      <div class="ask-reason">
        <span class="ask-reason-label">{{ ask.spec.reasonLabel }}</span>
        <span v-if="!auto" class="ask-reason-tag">示例理由</span>
        <p class="ask-reason-box" data-ask-reason :class="{ 'is-typing': typing }" :aria-readonly="true">
          {{ reason }}<i v-if="typing" class="ask-caret" aria-hidden="true"></i>
        </p>
      </div>
      <button
        type="button"
        class="button button-primary ask-submit"
        :class="{ 'is-pressed': pressed(ask.submit) }"
        :disabled="!selected"
        data-ask-submit
        @click="selected && emit('submit', selected)"
      >
        {{ ask.spec.submitLabel }}
      </button>
    </template>
    <p v-else class="ask-answer">{{ answer }}</p>
  </div>
</template>
