import { notFound } from "next/navigation";
import { MotionDemo } from "./motion-demo";

/** Vitrine interna dos primitives de motion. Em produção responde 404, salvo UI_DEMO=1 (não definido no deploy). */
export default function UiDemoPage() {
  if (process.env.NODE_ENV === "production" && process.env.UI_DEMO !== "1") notFound();
  return <MotionDemo />;
}
