/** Display-only recommendation for the official DeepSeek Flash model; the catalog and selected route stay unchanged. */
import type { PropsLocale, PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type {} from '@deepseek-ai/dsh-client-ui-model-selection/client'
import { Tag } from '@deepseek-ai/dsh-client-ui-primitives'
import css from './ModelLabel.module.css'

/** Providers whose `deepseek-flash` is the officially served DeepSeek V4.1 Flash. */
const OFFICIAL_PROVIDERS = new Set(['deepseek-official', 'deepseek-account'])

/**
 * Render DeepSeek V4.1 Flash with the recommendation badge; every other model keeps its catalog name.
 * @param props - provider and model identity plus the brand dictionary.
 * @returns the recommended label, or the untouched catalog name.
 */
export function ZhitongModelLabel({ provider, model, t }:
  PropsRuntime<'conversation.input.model.label'> & PropsLocale<'zhitong-brand'>,
) {
  if (!OFFICIAL_PROVIDERS.has(provider.id) || model.id !== 'deepseek-flash') return model.name
  return <span className={css.label}>
    <span>{t('recommendedModel')}</span>{' '}<Tag tone="info">{t('recommendedBadge')}</Tag>
  </span>
}
