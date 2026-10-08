/* motion.js — DERIVED by scripts/gen-motion.mjs from source/motion.json. Do not hand-edit.
 *
 * The reveal runner. Threshold and stagger step are MEASURED off the source
 * (https://dust.tt/), not guessed:
 *   threshold    = 0.15   (from the site's own IntersectionObserver options)
 *   staggerStep  = 80ms
 *
 * Usage:  <link rel="stylesheet" href="motion.css">
 *         <script src="motion.js" defer></script>
 *         <div data-reveal>…</div>            one element
 *         <div data-reveal-group>…</div>      children reveal staggered
 */
(() => {
  "use strict";
  const REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const THRESHOLD = 0.15;
  const STAGGER_STEP = 80;

  // Reduced motion is not "a slower reveal", it is NO reveal: show everything
  // and bind nothing. Anything else re-introduces the motion the user opted out of.
  if (REDUCED) {
    document.querySelectorAll("[data-reveal], [data-reveal-group] > *").forEach((el) => {
      el.style.opacity = "1";
      el.style.transform = "none";
    });
    return;
  }

  if (!("IntersectionObserver" in window)) {
    document.querySelectorAll("[data-reveal], [data-reveal-group] > *").forEach((el) => {
      el.classList.add("is-revealed");
    });
    return;
  }

  const io = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const el = entry.target;
        const group = el.parentElement && el.parentElement.hasAttribute("data-reveal-group");
        if (group && STAGGER_STEP > 0) {
          const idx = Array.prototype.indexOf.call(el.parentElement.children, el);
          el.style.animationDelay = idx * STAGGER_STEP + "ms";
          el.style.transitionDelay = idx * STAGGER_STEP + "ms";
        }
        el.classList.add("is-revealed");
        io.unobserve(el); // reveal is one-shot; re-firing on scroll-back reads as a glitch
      }
    },
    { threshold: THRESHOLD }
  );

  const bind = () => {
    document.querySelectorAll("[data-reveal]").forEach((el) => io.observe(el));
    document.querySelectorAll("[data-reveal-group]").forEach((g) => {
      Array.prototype.forEach.call(g.children, (c) => io.observe(c));
    });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bind);
  else bind();
})();
