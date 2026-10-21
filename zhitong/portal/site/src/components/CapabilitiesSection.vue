<script setup lang="ts">
/** 转发壳：实现在 components/capabilities/CapabilitiesSection.vue（04 章 §0）。HomePage 从这里导入。 */
import { ref } from 'vue';
import Impl from './capabilities/CapabilitiesSection.vue';
import type { FeatureGroup, FeatureId } from '../data/capabilities';
import type { SceneId } from '../types/portal';

withDefaults(defineProps<{ groups?: readonly FeatureGroup[] }>(), { groups: undefined });
const emit = defineEmits<{ scene: [scene: SceneId] }>();
const inner = ref<InstanceType<typeof Impl> | null>(null);

/**
 * 选中某项能力（签名同 04 章 §5.4）。
 * @param id - 能力 id。
 * @param opts - focus / instant。
 */
function selectFeature(
  id: FeatureId | string,
  opts?: { focus?: boolean; instant?: boolean },
): Promise<void> {
  return inner.value?.selectFeature(id, opts) ?? Promise.resolve();
}
defineExpose({ selectFeature });
</script>

<template>
  <Impl ref="inner" v-bind="groups ? { groups } : {}" @scene="(s: SceneId) => emit('scene', s)" />
</template>
