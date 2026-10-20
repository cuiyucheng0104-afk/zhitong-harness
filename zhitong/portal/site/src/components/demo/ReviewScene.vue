<script setup lang="ts">
import { nextTick, ref } from 'vue';
import AppIcon from '../AppIcon.vue';
import brandMark from '../../../assets/brand-mark.svg';
import type { ReviewDecision } from '../../types/portal';

defineProps<{ decision: ReviewDecision }>();
const emit = defineEmits<{ decide: [value: Exclude<ReviewDecision, null>]; reset: [] }>();
const resetButton = ref<HTMLButtonElement | null>(null);
const confirmButton = ref<HTMLButtonElement | null>(null);
async function decide(value: Exclude<ReviewDecision, null>) {
  emit('decide', value);
  await nextTick();
  resetButton.value?.focus({ preventScroll: true });
}
async function reset() {
  emit('reset');
  await nextTick();
  confirmButton.value?.focus({ preventScroll: true });
}
</script>

<template>
  <section id="scene-review" class="scene" role="tabpanel" aria-labelledby="tab-review">
    <div class="prompt">
      <span class="avatar-user">你</span><span>检查这份清单的投控异常</span
      ><AppIcon name="arrow" class="prompt-arrow" />
    </div>
    <div class="assistant-label">
      <img :src="brandMark" alt="" width="22" height="22" /><strong>智通数工AI</strong
      ><span class="read-status"><AppIcon name="check" />检查完成</span>
    </div>
    <p class="response-intro">发现一项疑似重复计取，请逐条复核。</p>
    <div class="anomaly-card">
      <div class="anomaly-heading">
        <span class="badge badge-warning">{{ decision ? '已复核' : '待复核' }}</span
        ><span class="mono">异常 01</span>
      </div>
      <h3>脚手架费用疑似重复计取</h3>
      <p>第 28 行与第 46 行名称、特征一致，可能重复列项。</p>
      <div class="anomaly-evidence">
        <AppIcon name="sheet" /><span
          >送审清单.xlsx<span>措施项目 · 第 28 / 46 行（示例）</span></span
        >
      </div>
    </div>
    <div v-if="!decision" class="review-actions">
      <button
        ref="confirmButton"
        class="button button-small button-primary"
        @click="decide('confirmed')"
      >
        <AppIcon name="check" />确认异常</button
      ><button class="button button-small button-outline" @click="decide('false-positive')">
        标记误报
      </button>
    </div>
    <div v-else class="decision-result" role="status">
      <AppIcon name="check" /><span>{{
        decision === 'confirmed' ? '已确认异常' : '已标记误报'
      }}</span
      ><button ref="resetButton" class="plain-button" @click="reset">重新选择</button>
    </div>
    <p class="scene-disclaimer">演示记录，仅当前页面有效 · 最终决定由您作出</p>
  </section>
</template>
