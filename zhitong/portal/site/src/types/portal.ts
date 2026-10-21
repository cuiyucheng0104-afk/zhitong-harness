export type SceneId = 'check' | 'review' | 'cad';

/** 能力相关类型以 `data/capabilities.ts` 为准（04 章 §0），此处转发。 */
export type { Feature, FeatureGroup, GroupId } from '../data/capabilities';

export type PortalAction =
  | { type: 'feature'; id: string }
  | { type: 'scene'; id: SceneId }
  | { type: 'source' }
  | { type: 'section'; id: string };
