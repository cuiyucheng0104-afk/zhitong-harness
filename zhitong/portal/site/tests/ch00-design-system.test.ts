import { readFileSync, statSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { CSS_EASE, DUR, EASE, SCRUB, STAGGER } from '../src/lib/motion-tokens';
import { formatInt, formatMoney, formatPercent } from '../src/lib/format';
import { LENIS_OPTIONS, SCROLL_DURATION, scrollEasing } from '../src/lib/smooth-scroll';

const css = (p: string) => readFileSync(`src/styles/${p}`, 'utf8');

describe('00 §5.2 动效变量', () => {
  it('DUR / EASE / STAGGER / SCRUB 与 spec 一致', () => {
    expect(DUR).toEqual({ micro: 0.16, short: 0.28, base: 0.45, long: 0.8, scene: 1.2 });
    expect(EASE).toEqual({
      out: 'power3.out',
      inOut: 'power2.inOut',
      expo: 'expo.out',
      snapBack: 'elastic.out(1, 0.45)',
      linear: 'none',
    });
    expect(STAGGER).toEqual({ tight: 0.04, base: 0.07, loose: 0.12 });
    expect(SCRUB).toEqual({ soft: 0.6, damp: 1, heavy: 1.6 });
    expect(CSS_EASE.out).toBe('cubic-bezier(.22,1,.36,1)');
  });

  it('CSS 同名变量', () => {
    const tokens = css('tokens.css');
    for (const decl of [
      '--dur-micro: 160ms',
      '--dur-short: 280ms',
      '--dur-base: 450ms',
      '--ease-out: cubic-bezier(0.22, 1, 0.36, 1)',
      '--ease-in-out: cubic-bezier(0.65, 0, 0.35, 1)',
    ])
      expect(tokens).toContain(decl);
  });
});

describe('00 §4.2 颜色变量增量', () => {
  it.each([
    ['--navy-900', '#082457'],
    ['--blue-600', '#0558d6'],
    ['--blue-050', '#f2f7ff'],
    ['--grid-line', '#dce8f4'],
    ['--grid-line-strong', '#c5d6ea'],
    ['--danger-bg', '#fff0ea'],
    ['--danger-text', '#b4400f'],
    ['--reduce-text', '#0b5cd5'],
    ['--code-bg', '#0f1e33'],
    ['--focus-ring', '0 0 0 3px rgba(6, 102, 245, 0.35)'],
  ])('%s = %s', (name, value) => {
    expect(css('tokens.css')).toContain(`${name}: ${value};`);
  });
});

describe('00 §4.3 等宽字体', () => {
  it('IBM Plex Mono 自托管、font-display: swap、每个文件 ≤ 20 KB', () => {
    const fonts = css('fonts.css');
    expect(fonts.match(/font-display: swap/g)).toHaveLength(3);
    for (const w of [400, 500, 600]) {
      expect(fonts).toContain(`ibm-plex-mono-${w}.woff2`);
      expect(statSync(`src/assets/fonts/ibm-plex-mono-${w}.woff2`).size).toBeLessThanOrEqual(20 * 1024);
    }
    expect(statSync('src/assets/fonts/OFL.txt').size).toBeGreaterThan(0);
    expect(fonts).not.toMatch(/https?:/);
  });
});

describe('00 §5.3 平滑滚动参数', () => {
  it('Lenis 参数与锚点滚动缓动', () => {
    expect(LENIS_OPTIONS).toMatchObject({
      lerp: 0.085,
      wheelMultiplier: 0.9,
      smoothWheel: true,
      syncTouch: false,
      anchors: false,
    });
    expect(SCROLL_DURATION).toBe(1.1);
    expect(scrollEasing(0)).toBe(0);
    expect(scrollEasing(1)).toBe(1);
    expect(scrollEasing(0.5)).toBeCloseTo(1 - 0.5 ** 4);
  });

  it('删除 html { scroll-behavior: smooth }，避免两套平滑叠加', () => {
    const all = ['base.css', 'responsive.css', 'motion.css', 'header.css'].map(css).join('\n');
    expect(all).not.toMatch(/scroll-behavior:\s*smooth/);
    expect(all).not.toMatch(/scroll-padding-top/);
  });
});

describe('00 §5.5 内容先可见与打印', () => {
  it('打印时 .motion-ready [data-reveal] 强制终态', () => {
    const motion = css('motion.css');
    expect(motion).toMatch(/@media print[\s\S]*\.motion-ready \[data-reveal\][\s\S]*opacity: 1 !important/);
  });
});

describe('00 §7.4 数字格式', () => {
  it('千分位、两位小数、核增负号', () => {
    expect(formatMoney(30530406.8)).toBe('30,530,406.80');
    expect(formatMoney(-32612.74)).toBe('−32,612.74');
    expect(formatPercent(906692.96 / 30530406.8)).toBe('2.97%');
    expect(formatInt(1284)).toBe('1,284');
  });
});
