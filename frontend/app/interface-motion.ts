/**
 * Visual-only entry motion for surfaces that change content without remounting
 * (e.g. a tour step). It never owns open state, focus, timers, data or dismissal:
 * it only plays and cancels the Web Animations it created itself.
 */

export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

type MediaQueryListLike = {
  matches: boolean;
  addEventListener?: (type: "change", listener: (event: { matches: boolean }) => void) => void;
  removeEventListener?: (type: "change", listener: (event: { matches: boolean }) => void) => void;
};
type AnimationLike = { cancel(): void; finished?: Promise<unknown> };
type AnimatableLike = { animate(keyframes: Keyframe[], options: KeyframeAnimationOptions): AnimationLike };

export type SurfaceEntryOptions = {
  /** Vertical offset in px the surface travels from (default 6). */
  offsetY?: number;
  /** Starting opacity; readable surfaces start at .92, never 0 (default .92). */
  opacityStart?: number;
  /** Duration in ms, kept within the approved 180–220 ms band (default 200). */
  duration?: number;
  matchMedia?: (query: string) => MediaQueryListLike;
};

const ENTER_EASING = "cubic-bezier(0.2, 0.8, 0.2, 1)";
const noop = () => {};

function mediaFor(options: SurfaceEntryOptions): MediaQueryListLike | null {
  const match = options.matchMedia ?? (typeof window !== "undefined" && typeof window.matchMedia === "function" ? window.matchMedia.bind(window) : undefined);
  return match ? match(REDUCED_MOTION_QUERY) : null;
}

export function clampDuration(duration: number | undefined): number {
  if (duration === undefined || !Number.isFinite(duration)) return 200;
  return Math.min(220, Math.max(180, duration));
}

/**
 * Plays a short entry on the given elements and returns a cancel function.
 * Reduced motion (initially or when it changes mid-animation) cancels everything,
 * leaving the elements in their natural, final styles. Calling cancel twice is safe.
 */
export function playSurfaceEntry(targets: AnimatableLike | null | undefined | ReadonlyArray<AnimatableLike | null | undefined>, options: SurfaceEntryOptions = {}): () => void {
  const elements = (Array.isArray(targets) ? targets : [targets]).filter((item): item is AnimatableLike => Boolean(item && typeof item.animate === "function"));
  if (elements.length === 0) return noop;
  const media = mediaFor(options);
  if (media?.matches) return noop;
  const offset = options.offsetY ?? 6;
  const keyframes: Keyframe[] = [
    { opacity: options.opacityStart ?? 0.92, transform: `translateY(${offset}px)` },
    { opacity: 1, transform: "none" },
  ];
  // fill "none": once finished or cancelled the element shows its own computed styles.
  const animations = elements.map((element) => element.animate(keyframes, { duration: clampDuration(options.duration), easing: ENTER_EASING, fill: "none" }));
  let active = true;
  const onChange = (event: { matches: boolean }) => { if (event.matches) cancel(); };
  function cancel() {
    if (!active) return;
    active = false;
    media?.removeEventListener?.("change", onChange);
    for (const animation of animations) animation.cancel();
  }
  media?.addEventListener?.("change", onChange);
  void Promise.all(animations.map((animation) => animation.finished ?? Promise.resolve())).then(() => {
    if (!active) return;
    active = false;
    media?.removeEventListener?.("change", onChange);
  }, noop);
  return cancel;
}
