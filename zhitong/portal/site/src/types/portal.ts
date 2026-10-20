export type SceneId = 'check' | 'review' | 'cad';
export type RoomId = 'meeting' | 'office' | 'archive';
export type ReviewDecision = 'confirmed' | 'false-positive' | null;
export type GroupId = 'project' | 'calculate' | 'output' | 'knowledge';

export type PortalAction =
  | { type: 'feature'; id: string }
  | { type: 'scene'; id: SceneId }
  | { type: 'source' }
  | { type: 'section'; id: string };

export interface Feature {
  id: string;
  name: string;
  icon: string;
  kicker: string;
  title: string;
  description: string;
  input: string;
  output: string;
  caution: string;
  scene?: SceneId;
}

export interface FeatureGroup {
  id: GroupId;
  label: string;
  icon: string;
  features: Feature[];
}

export interface Role {
  id: string;
  name: string;
  icon: string;
  title: string;
  description: string;
  tasks: { label: string; action: PortalAction }[];
}
