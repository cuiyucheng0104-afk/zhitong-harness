/**
 * 动效懒加载块（00 章 §5.1）：GSAP 与全部插件、Lenis 同一块动态 import。
 * 只在首页调用；文档页与 404 页不加载（06 章 §9.1）。
 * 加载成功且未减少动效时，在 <html> 上加 `motion-ready`（00 章 §5.5）。
 */
export type Motion = {
  gsap: typeof import('gsap').gsap;
  ScrollTrigger: typeof import('gsap/ScrollTrigger').ScrollTrigger;
  SplitText: typeof import('gsap/SplitText').SplitText;
  Flip: typeof import('gsap/Flip').Flip;
  DrawSVGPlugin: typeof import('gsap/DrawSVGPlugin').DrawSVGPlugin;
  MotionPathPlugin: typeof import('gsap/MotionPathPlugin').MotionPathPlugin;
  CustomEase: typeof import('gsap/CustomEase').CustomEase;
  Observer: typeof import('gsap/Observer').Observer;
  Lenis: typeof import('lenis').default;
};

let loading: Promise<Motion | null> | undefined;
let loaded: Motion | null = null;

/** 当前是否偏好减少动效（SSR 时为 false）。 */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/** 精确指针设备（磁吸、光斑只在此时启用）。 */
export function hasFinePointer(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(hover: hover) and (pointer: fine)').matches
  );
}

/**
 * 加载 GSAP、插件与 Lenis；失败时返回 null，页面内容不受影响。
 * @returns 已注册插件的动效句柄；多次调用共享同一 Promise。
 */
export function loadMotion(): Promise<Motion | null> {
  loading ??= Promise.all([
    import('gsap'),
    import('gsap/ScrollTrigger'),
    import('gsap/SplitText'),
    import('gsap/Flip'),
    import('gsap/DrawSVGPlugin'),
    import('gsap/MotionPathPlugin'),
    import('gsap/CustomEase'),
    import('gsap/Observer'),
    import('lenis'),
  ])
    .then(
      ([
        { gsap },
        { ScrollTrigger },
        { SplitText },
        { Flip },
        { DrawSVGPlugin },
        { MotionPathPlugin },
        { CustomEase },
        { Observer },
        { default: Lenis },
      ]) => {
        gsap.registerPlugin(
          ScrollTrigger,
          SplitText,
          Flip,
          DrawSVGPlugin,
          MotionPathPlugin,
          CustomEase,
          Observer,
        );
        loaded = {
          gsap,
          ScrollTrigger,
          SplitText,
          Flip,
          DrawSVGPlugin,
          MotionPathPlugin,
          CustomEase,
          Observer,
          Lenis,
        };
        if (!prefersReducedMotion()) document.documentElement.classList.add('motion-ready');
        return loaded;
      },
    )
    .catch(() => null);
  return loading;
}

/** 已加载的动效句柄；未加载或加载失败时为 null（不触发加载）。 */
export function getMotion(): Motion | null {
  return loaded;
}

/** 布局变化后重新测量 ScrollTrigger（动效未加载时什么也不做）。 */
export function refreshMotionLayout() {
  void loading?.then((motion) => motion?.ScrollTrigger.refresh());
}
