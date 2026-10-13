// Ponto de entrada dos primitives de motion [M56]. Contrato: specs/design/motion-foundation.md
export { Skeleton, SkeletonLine, SkeletonBlock, SkeletonAvatar, SkeletonText, SkeletonCard, SkeletonList, LoadingBlock } from "./skeleton";
export { Spinner, ProgressIndicator, Shimmer } from "./loading";
export { TypingIndicator, StreamingText } from "./chat";
export { Enter, Transition, StaggerItem, Reveal, ScreenTransition } from "./transitions";
export { EmptyState, ErrorState, Toast, ToastViewport } from "./feedback";
export { closeDialogAnimated } from "./dialog-motion";
export { useReducedMotion } from "./use-reduced-motion";
export { staggerStyle, STAGGER_MAX, MOTION_MS, REDUCED_MOTION_QUERY } from "./motion-logic";
export { btn, type ButtonVariant, type ButtonSize } from "./button-variants";
