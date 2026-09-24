'use client';

import { ActionBar } from './ActionBar';
import { Canvas } from './Canvas';
import { Header } from './Header';
import { HistoryDrawer } from './HistoryDrawer';
import { LeftRail } from './LeftRail';
import { PredictionProvider } from './PredictionProvider';
import { StudioBoot } from './StudioBoot';
import { Toasts } from './Toasts';

export function Studio() {
  return (
    <PredictionProvider>
      <StudioBoot />

      <a
        href="#canvas"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[70] focus:border focus:border-selvedge focus:bg-warp focus:px-3 focus:py-2 focus:font-mono focus:text-[11px] focus:uppercase focus:tracking-loom"
      >
        Skip to canvas
      </a>

      <div className="flex h-[100dvh] flex-col overflow-hidden">
        <Header />

        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
          <LeftRail />

          <section
            id="canvas"
            tabIndex={-1}
            className="flex min-h-[60vh] flex-1 flex-col lg:min-h-0"
          >
            <Canvas />
            <ActionBar />
          </section>
        </main>
      </div>

      <HistoryDrawer />
      <Toasts />
    </PredictionProvider>
  );
}
