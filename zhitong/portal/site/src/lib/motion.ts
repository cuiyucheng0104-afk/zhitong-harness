let loading: Promise<Motion | null> | undefined;
export type Motion = {
  gsap: typeof import('gsap').gsap;
  ScrollTrigger: typeof import('gsap/ScrollTrigger').ScrollTrigger;
};

export function loadMotion(): Promise<Motion | null> {
  loading ??= Promise.all([import('gsap'), import('gsap/ScrollTrigger')])
    .then(([{ gsap }, { ScrollTrigger }]) => {
      gsap.registerPlugin(ScrollTrigger);
      return { gsap, ScrollTrigger };
    })
    .catch(() => null);
  return loading;
}

export function refreshMotionLayout() {
  void loading?.then((motion) => motion?.ScrollTrigger.refresh());
}
