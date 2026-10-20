import { onBeforeUnmount, onMounted, type Ref } from 'vue';
import { loadMotion, refreshMotionLayout } from '../lib/motion';

export function usePageMotion(root: Ref<HTMLElement | null>) {
  let media: gsap.MatchMedia | undefined;
  let mounted = false;
  onMounted(async () => {
    mounted = true;
    const motion = await loadMotion();
    if (!mounted || !root.value || !motion) return;
    const { gsap } = motion;
    media = gsap.matchMedia();
    media.add(
      { desktop: '(min-width: 768px)', reduce: '(prefers-reduced-motion: reduce)' },
      (context) => {
        if (context.conditions?.reduce) return;
        const intro = gsap.timeline({ defaults: { ease: 'power2.out' } });
        intro
          .from(
            '.hero-enter',
            {
              autoAlpha: 0,
              y: 16,
              duration: 0.56,
              stagger: 0.07,
              clearProps: 'opacity,visibility,transform',
            },
            0,
          )
          .from(
            '.demo-stage',
            {
              autoAlpha: 0,
              y: 24,
              duration: 0.72,
              ease: 'power3.out',
              clearProps: 'opacity,visibility,transform',
            },
            0.12,
          );
        const reveals = root.value!.querySelectorAll('.reveal');
        for (const element of reveals) {
          gsap.from(element, {
            autoAlpha: 0,
            y: 16,
            duration: 0.45,
            ease: 'power2.out',
            clearProps: 'opacity,visibility,transform',
            scrollTrigger: { trigger: element, start: 'top 86%', once: true },
          });
        }
        gsap.from('.workflow-track > span', {
          ...(context.conditions?.desktop
            ? { scaleX: 0, transformOrigin: 'left center' }
            : { scaleY: 0, transformOrigin: 'center top' }),
          duration: 0.7,
          ease: 'power2.out',
          clearProps: 'transform',
          scrollTrigger: { trigger: '.workflow-grid', start: 'top 82%', once: true },
        });
      },
      root.value,
    );
    void document.fonts?.ready.then(() => {
      if (mounted) refreshMotionLayout();
    });
  });
  onBeforeUnmount(() => {
    mounted = false;
    media?.revert();
  });
}
