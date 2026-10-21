<script setup lang="ts">
/**
 * 小动画外框（04 章 §4.5）：舞台、示例标签、进度线、暂停按钮、文本等价。
 * 预渲染为终帧（`.art-stage` 没有 `art-live` 时过程元素隐藏）；`useArtLoop` 接管后显示暂停按钮。
 */
import { computed, inject, ref, toRef } from 'vue';
import AppIcon from '../AppIcon.vue';
import type { FeatureId } from '../../data/capabilities';
import { ART_PAUSED } from './art-tokens';
import { useArtLoop } from '../../composables/useArtLoop';
import ProjectArt from './art/ProjectArt.vue';
import QaArt from './art/QaArt.vue';
import CadArt from './art/CadArt.vue';
import CheckArt from './art/CheckArt.vue';
import MetricsArt from './art/MetricsArt.vue';
import ControlArt from './art/ControlArt.vue';
import EstimateArt from './art/EstimateArt.vue';
import ReportArt from './art/ReportArt.vue';
import BillsArt from './art/BillsArt.vue';
import ArchiveArt from './art/ArchiveArt.vue';
import KnowledgeArt from './art/KnowledgeArt.vue';
import CloudArt from './art/CloudArt.vue';

const props = defineProps<{ id: FeatureId; caption: string; active: boolean }>();

const ARTS = {
  project: ProjectArt,
  qa: QaArt,
  cad: CadArt,
  check: CheckArt,
  metrics: MetricsArt,
  control: ControlArt,
  estimate: EstimateArt,
  report: ReportArt,
  bills: BillsArt,
  archive: ArchiveArt,
  knowledge: KnowledgeArt,
  cloud: CloudArt,
} as const;

const figure = ref<HTMLElement | null>(null);
const paused = inject(ART_PAUSED, ref(false));
const { layout, running, live } = useArtLoop(figure, {
  id: props.id,
  active: toRef(props, 'active'),
  paused,
});
const label = computed(() => (paused.value ? '播放示意动画' : '暂停示意动画'));

function toggle() {
  paused.value = !paused.value;
}
</script>

<template>
  <figure
    ref="figure"
    class="feature-art"
    :data-art="id"
    :data-layout="layout"
    :data-running="running ? 'true' : 'false'"
  >
    <div class="art-stage" :class="{ 'art-live': live }">
      <component :is="ARTS[id]" />
    </div>
    <div class="art-foot">
      <span class="art-tag">示例</span>
      <span class="art-progress" aria-hidden="true"></span>
      <button
        type="button"
        class="art-toggle icon-button"
        :hidden="!live"
        :aria-label="label"
        :title="label"
        :aria-pressed="paused ? 'true' : 'false'"
        @click="toggle"
      >
        <AppIcon :name="paused ? 'play' : 'pause'" />
      </button>
    </div>
    <figcaption class="visually-hidden sr-only">{{ caption }}</figcaption>
  </figure>
</template>
