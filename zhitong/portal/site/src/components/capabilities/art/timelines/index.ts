/**
 * 12 段能力小动画的构建函数（04 章 §7.2–§7.13），与 art-kit 一起为单独的懒加载块。
 */
import type { FeatureId } from '../../../../data/capabilities';
import type { ArtBuilder } from '../../art-kit';
import project from './project';
import qa from './qa';
import cad from './cad';
import check from './check';
import metrics from './metrics';
import control from './control';
import estimate from './estimate';
import report from './report';
import bills from './bills';
import archive from './archive';
import knowledge from './knowledge';
import cloud from './cloud';

export { createArtKit, finishArtLoop } from '../../art-kit';

export const builders: Record<FeatureId, ArtBuilder> = {
  project,
  qa,
  cad,
  check,
  metrics,
  control,
  estimate,
  report,
  bills,
  archive,
  knowledge,
  cloud,
};
