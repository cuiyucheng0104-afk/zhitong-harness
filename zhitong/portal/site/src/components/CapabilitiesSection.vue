<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue';
import { featureGroups } from '../data/content';
import { onTabKeydown } from '../lib/navigation';
import { refreshMotionLayout } from '../lib/motion';
import type { GroupId, SceneId } from '../types/portal';
import AppIcon from './AppIcon.vue';
import FeatureArtwork from './FeatureArtwork.vue';

const emit = defineEmits<{ scene: [scene: SceneId] }>();
const section = ref<HTMLElement | null>(null);
const selectedGroup = ref<GroupId>('calculate');
const selectedFeatures = ref<Record<GroupId, string | null>>({
  project: 'project',
  calculate: 'check',
  output: 'report',
  knowledge: 'knowledge',
});
const mobile = ref(false);
let mobileMedia: MediaQueryList | undefined;

function chooseGroup(groupId: GroupId) {
  const group = featureGroups.find((item) => item.id === groupId);
  if (!group) return;
  selectedGroup.value = groupId;
  selectedFeatures.value[groupId] = group.features[0]?.id ?? null;
  void nextTick(refreshMotionLayout);
}

function chooseFeature(groupId: GroupId, featureId: string) {
  const closing = mobile.value && selectedFeatures.value[groupId] === featureId;
  selectedFeatures.value[groupId] = closing ? null : featureId;
  void nextTick(refreshMotionLayout);
}

async function selectFeature(id: string): Promise<void> {
  const group = featureGroups.find((item) => item.features.some((feature) => feature.id === id));
  if (!group) return;
  selectedGroup.value = group.id;
  selectedFeatures.value[group.id] = id;
  await nextTick();
  refreshMotionLayout();
  section.value?.querySelector<HTMLElement>(`#feature-${id}-title`)?.focus({ preventScroll: true });
}

defineExpose({ selectFeature });

function updateLayout() {
  mobile.value = mobileMedia?.matches ?? false;
  if (!mobile.value) {
    for (const group of featureGroups) {
      if (!selectedFeatures.value[group.id]) {
        selectedFeatures.value[group.id] = group.features[0]?.id ?? null;
      }
    }
  }
  void nextTick(refreshMotionLayout);
}

onMounted(() => {
  mobileMedia = window.matchMedia('(max-width: 767px)');
  updateLayout();
  mobileMedia.addEventListener('change', updateLayout);
});

onUnmounted(() => {
  mobileMedia?.removeEventListener('change', updateLayout);
});
</script>

<template>
  <section
    id="capabilities"
    ref="section"
    class="capabilities-section section-space"
    aria-labelledby="capabilities-title"
  >
    <div class="container">
      <div class="section-heading capabilities-heading reveal">
        <div>
          <p class="eyebrow">产品能力</p>
          <h2 id="capabilities-title" tabindex="-1">从项目资料，到交付成果。</h2>
        </div>
        <p>12 项具体工作，按任务选择。<br />需要什么，得到什么，一目了然。</p>
      </div>
      <div class="capability-tabs" role="tablist" aria-label="能力分组" @keydown="onTabKeydown">
        <button
          v-for="group in featureGroups"
          :id="`group-${group.id}`"
          :key="group.id"
          type="button"
          role="tab"
          :aria-selected="selectedGroup === group.id"
          :aria-controls="`feature-group-${group.id}`"
          :tabindex="selectedGroup === group.id ? 0 : -1"
          :data-group="group.id"
          @click="chooseGroup(group.id)"
        >
          <AppIcon :name="group.icon" />{{ group.label }}<span>{{ group.features.length }}</span>
        </button>
      </div>
      <div
        v-for="group in featureGroups"
        :id="`feature-group-${group.id}`"
        :key="group.id"
        class="feature-group"
        role="tabpanel"
        :aria-labelledby="`group-${group.id}`"
        :hidden="selectedGroup !== group.id"
      >
        <details
          v-for="feature in group.features"
          :key="feature.id"
          class="feature-item"
          :data-feature="feature.id"
          :open="selectedFeatures[group.id] === feature.id"
        >
          <summary
            :aria-expanded="selectedFeatures[group.id] === feature.id"
            @click.prevent="chooseFeature(group.id, feature.id)"
          >
            <AppIcon :name="feature.icon" /><span>{{ feature.name }}</span
            ><AppIcon name="arrow" class="feature-chevron" />
          </summary>
          <div class="feature-detail">
            <p class="feature-kicker">{{ feature.kicker }}</p>
            <h3 :id="`feature-${feature.id}-title`" tabindex="-1">
              {{ feature.title }}
            </h3>
            <p class="feature-description">{{ feature.description }}</p>
            <dl class="feature-io">
              <div>
                <dt>需要什么</dt>
                <dd>{{ feature.input }}</dd>
              </div>
              <div>
                <dt>得到什么</dt>
                <dd>{{ feature.output }}</dd>
              </div>
            </dl>
            <FeatureArtwork :feature="feature" />
            <p class="feature-caution">
              <AppIcon v-if="feature.id === 'check'" name="alert" />{{ feature.caution }}
            </p>
            <button
              v-if="feature.scene"
              type="button"
              class="text-link"
              :data-go-scene="feature.scene"
              @click="emit('scene', feature.scene)"
            >
              查看工作示例<AppIcon name="arrow" />
            </button>
          </div>
        </details>
      </div>
      <p class="capability-footnote"><AppIcon name="link" />资料有位置，计算有依据，成果有去处。</p>
    </div>
  </section>
</template>
