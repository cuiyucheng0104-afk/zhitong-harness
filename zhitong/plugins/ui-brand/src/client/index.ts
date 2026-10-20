/**
 * 智通数工AI browser-brand plugin. It occupies the sidebar mark and name slots and the new-session hero mark as one
 * declaration-aware registration set, in every build profile, and labels DeepSeek V4.1 Flash as the recommended
 * model in the composer model selector. `zhitong/bundle/cordis.patch.yml` disables the upstream `ui-brand-official`
 * and `ui-deepseek-model-label-1017` rows, so these are the only occupants.
 */
import type { Context as ClientContext } from '@deepseek-ai/cordis'
// Type-only: the locale plugin's Context merge (ctx.locale).
import type {} from '@deepseek-ai/dsh-client-locale/client'
// Type-only: the conversation hero slot declaration.
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
// Type-only: the composer model-label slot declaration.
import type {} from '@deepseek-ai/dsh-client-ui-model-selection/client'
// Type-only: the renderer-owned slots service.
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
// Type-only: the sidebar brand slot declarations.
import type {} from '@deepseek-ai/dsh-client-ui-sidebar/client'
import { ZhitongBrandMark, ZhitongBrandName } from './Brand.tsx'
import { ZhitongModelLabel } from './ModelLabel.tsx'
import { en, zh, type BrandKey } from './locales.ts'

declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface LocaleNamespaceMap {
    /** 智通数工AI product name and recommended-model label. */
    'zhitong-brand': BrandKey
  }
}

/** Dictionary namespace owned by this plugin. */
export type BrandNamespace = 'zhitong-brand'
const NS: BrandNamespace = 'zhitong-brand'

/** Required services: the UI slot registry and the locale dictionaries. */
export const inject = ['slots', 'locale']

/**
 * Register the brand dictionary, fill the three brand slots, and label the composer's recommended model; every
 * occupant leaves with this plugin's fiber or with the declaration it fills.
 * @param ctx - Client root context.
 */
export function apply(ctx: ClientContext): void {
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'zhitong-ui-brand: dictionaries')
  ctx.slots.inject('sidebar.brand.mark', () =>
    ctx.slots.inject('sidebar.brand.name', function* () {
      yield ctx.slots.register({ name: 'sidebar.brand.mark', locale: NS }, ZhitongBrandMark)
      yield ctx.slots.register({ name: 'sidebar.brand.name', locale: NS }, ZhitongBrandName)
    }))
  ctx.slots.inject('conversation.hero.brand.mark', () =>
    ctx.slots.register({ name: 'conversation.hero.brand.mark', locale: NS }, ZhitongBrandMark))
  ctx.slots.inject('conversation.input.model.label', () =>
    ctx.slots.register({ name: 'conversation.input.model.label', locale: NS }, ZhitongModelLabel))
}
