// @vitest-environment jsdom
import { Context } from '@deepseek-ai/cordis'
import { SlotRegistry } from '@deepseek-ai/dsh-client-ui-renderer/client'
import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { apply as hostApply } from '../src/index.ts'
import { apply, inject } from '../src/client/index.ts'
import { ZhitongBrandMark, ZhitongBrandName } from '../src/client/Brand.tsx'
import { ZhitongModelLabel } from '../src/client/ModelLabel.tsx'
import { en, zh } from '../src/client/locales.ts'

afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
})

const HOLES = ['sidebar.brand.mark', 'sidebar.brand.name', 'conversation.hero.brand.mark', 'conversation.input.model.label'] as const
const SCOPES: Record<string, string> = { 'conversation.input.model.label': 'session' }

/** Translate through the shipped Chinese dictionary, as the renderer's `t` seat would. */
const t = ((key: keyof typeof zh) => zh[key]) as never

async function bench(declare = true) {
  const ctx = new Context()
  await ctx.plugin(SlotRegistry).await()
  const slots = ctx.get('slots') as SlotRegistry
  const dictionaries: { ns: string, dicts: unknown }[] = []
  ctx.provide('locale', {
    register(ns: string, dicts: unknown) {
      const record = { ns, dicts }
      dictionaries.push(record)
      return () => { dictionaries.splice(dictionaries.indexOf(record), 1) }
    },
  } as never)
  const declareHoles = () => slots.register({
    name: 'root',
    children: Object.fromEntries(HOLES.map(name => [name, { kind: 'single', scope: SCOPES[name] ?? 'root' }])),
  } as never, () => null)
  const disposeHoles = declare ? declareHoles() : undefined
  return { ctx, slots, dictionaries, declareHoles, disposeHoles }
}

describe('智通数工AI browser-brand plugin', () => {
  it('keeps the host Loader entry inert and declares the services it uses', () => {
    expect(hostApply).not.toThrow()
    expect(inject).toEqual(['slots', 'locale'])
  })

  it('names the product and the recommended model identically in both locales', () => {
    expect(zh.name).toBe('智通数工AI')
    expect({ ...en, recommendedBadge: undefined }).toEqual({ ...zh, recommendedBadge: undefined })
    expect([zh.recommendedBadge, en.recommendedBadge]).toEqual(['官方推荐', 'Recommended'])
  })

  it('fills every brand slot in any build profile and removes them on teardown', async () => {
    vi.stubEnv('DSH_CLIENT_BUILD_PROFILE', 'local')
    const subject = await bench()
    const fiber = subject.ctx.plugin({ inject: [...inject], apply })
    await fiber.await()
    for (const hole of HOLES) expect(subject.slots.entries(hole)).toHaveLength(1)
    expect(subject.dictionaries.map(entry => entry.ns)).toEqual(['zhitong-brand'])

    subject.disposeHoles?.()
    for (const hole of HOLES) expect(subject.slots.entries(hole)).toHaveLength(0)
    subject.declareHoles()
    await Promise.resolve()
    for (const hole of HOLES) expect(subject.slots.entries(hole)).toHaveLength(1)

    await fiber.dispose()
    for (const hole of HOLES) expect(subject.slots.entries(hole)).toHaveLength(0)
    expect(subject.dictionaries).toHaveLength(0)
  })

  it('waits for declarations that appear after activation', async () => {
    const subject = await bench(false)
    await subject.ctx.plugin({ inject: [...inject], apply }).await()
    for (const hole of HOLES) expect(subject.slots.entries(hole)).toHaveLength(0)
    subject.declareHoles()
    await Promise.resolve()
    for (const hole of HOLES) expect(subject.slots.entries(hole)).toHaveLength(1)
  })

  it('renders the mark at the requested size and the wordmark from the dictionary', () => {
    const mark = render(<ZhitongBrandMark size={34} className="hero" t={t} />)
    const svg = mark.container.querySelector('svg')!
    expect(svg.getAttribute('width')).toBe('34')
    expect(svg.getAttribute('class')).toBe('hero')
    expect(svg.textContent).toBe('智')
    mark.rerender(<ZhitongBrandMark size={24} t={t} />)
    expect(mark.container.querySelector('svg')?.getAttribute('width')).toBe('24')
    mark.unmount()

    const name = render(<ZhitongBrandName t={t} />)
    expect(name.container.textContent).toBe('智通数工AI')
    expect(name.container.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
  })

  it('recommends only deepseek-flash on the official DeepSeek routes', () => {
    const label = (provider: string, id: string, name: string) => {
      const view = render(<ZhitongModelLabel {...{ provider: { id: provider, name: provider }, model: { id, name }, t } as never} />)
      const text = view.container.textContent
      view.unmount()
      return text
    }
    expect(label('deepseek-official', 'deepseek-flash', 'DeepSeek-V4.1-Flash')).toBe('DeepSeek V4.1 Flash 官方推荐')
    expect(label('deepseek-account', 'deepseek-flash', 'Renamed')).toBe('DeepSeek V4.1 Flash 官方推荐')
    expect(label('deepseek-official', 'deepseek-v4-pro', 'DeepSeek-V4-Pro')).toBe('DeepSeek-V4-Pro')
    expect(label('my-gateway', 'deepseek-flash', 'Gateway Flash')).toBe('Gateway Flash')
  })
})
