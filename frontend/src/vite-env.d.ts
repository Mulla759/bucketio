/// <reference types="vite/client" />

declare module "vanta/dist/vanta.*.min.js" {
  interface VantaInstance {
    destroy: () => void;
    setOptions?: (options: Record<string, unknown>) => void;
  }

  const factory: (
    options: Record<string, unknown> & { el: HTMLElement; THREE: unknown },
  ) => VantaInstance;

  export default factory;
}
