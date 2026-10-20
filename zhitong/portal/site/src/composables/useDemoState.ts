import { computed, ref } from 'vue';
import { comparisonRows, rooms } from '../data/demo';
import type { ReviewDecision, RoomId, SceneId } from '../types/portal';

export function useDemoState() {
  const scene = ref<SceneId>('check');
  const decision = ref<ReviewDecision>(null);
  const room = ref<RoomId>('meeting');
  const totals = computed(() => {
    const submitted = comparisonRows.reduce((sum, row) => sum + row.submitted, 0);
    const approved = comparisonRows.reduce((sum, row) => sum + row.approved, 0);
    const reduction = submitted - approved;
    return { submitted, approved, reduction, rate: ((reduction / submitted) * 100).toFixed(2) };
  });

  function selectScene(id: SceneId) {
    decision.value = null;
    scene.value = id;
  }

  return {
    scene,
    decision,
    room,
    totals,
    roomLabel: computed(() => rooms.find((item) => item.id === room.value)!.name),
    selectScene,
    decide: (value: Exclude<ReviewDecision, null>) => {
      decision.value = value;
    },
    resetReview: () => {
      decision.value = null;
    },
    selectRoom: (id: RoomId) => {
      room.value = id;
    },
  };
}
