'use client';

import React from 'react';

export interface AnchoredCenter {
  percent: {
    left: string;
    top: string;
  };
  pixel: {
    x: number;
    y: number;
  };
  stageSize: {
    width: number;
    height: number;
  };
}

const clampPercent = (value: number) => Math.min(100, Math.max(0, value));
const defaultCenter: AnchoredCenter = {
  percent: { left: '50%', top: '50%' },
  pixel: { x: 0, y: 0 },
  stageSize: { width: 0, height: 0 }
};

const isClose = (a: number, b: number) => Math.abs(a - b) < 0.5;

export function useAnchoredCenter<TStage extends HTMLElement = HTMLDivElement, TAnchor extends HTMLElement = HTMLDivElement>() {
  const stageRef = React.useRef<TStage | null>(null);
  const anchorRef = React.useRef<TAnchor | null>(null);
  const [observedStage, setObservedStage] = React.useState<TStage | null>(null);
  const [observedAnchor, setObservedAnchor] = React.useState<TAnchor | null>(null);
  const [center, setCenter] = React.useState<AnchoredCenter>(defaultCenter);

  const syncCenter = React.useCallback(() => {
    const host = stageRef.current;
    if (!host) return;

    const hostRect = host.getBoundingClientRect();
    if (!hostRect.width || !hostRect.height) return;

    const anchor = anchorRef.current;
    const anchorRect = anchor?.getBoundingClientRect();

    const centerX = anchorRect
      ? (anchorRect.left + anchorRect.width / 2) - hostRect.left
      : hostRect.width / 2;
    const centerY = anchorRect
      ? (anchorRect.top + anchorRect.height / 2) - hostRect.top
      : hostRect.height / 2;

    const percentLeft = clampPercent((centerX / hostRect.width) * 100);
    const percentTop = clampPercent((centerY / hostRect.height) * 100);

    const next: AnchoredCenter = {
      percent: {
        left: `${percentLeft.toFixed(2)}%`,
        top: `${percentTop.toFixed(2)}%`
      },
      pixel: {
        x: centerX,
        y: centerY
      },
      stageSize: {
        width: hostRect.width,
        height: hostRect.height
      }
    };

    setCenter((prev) => {
      if (
        prev.percent.left === next.percent.left &&
        prev.percent.top === next.percent.top &&
        isClose(prev.pixel.x, next.pixel.x) &&
        isClose(prev.pixel.y, next.pixel.y) &&
        isClose(prev.stageSize.width, next.stageSize.width) &&
        isClose(prev.stageSize.height, next.stageSize.height)
      ) {
        return prev;
      }
      return next;
    });
  }, []);

  const stageCallbackRef = React.useCallback((node: TStage | null) => {
    stageRef.current = node;
    setObservedStage(node);
  }, []);

  const anchorCallbackRef = React.useCallback((node: TAnchor | null) => {
    anchorRef.current = node;
    setObservedAnchor(node);
  }, []);

  React.useEffect(() => {
    if (typeof window === 'undefined') return;

    let raf: number | null = null;
    const schedule = () => {
      if (raf) window.cancelAnimationFrame(raf);
      raf = window.requestAnimationFrame(syncCenter);
    };

    schedule();
    window.addEventListener('resize', schedule);

    const resizeObserver = 'ResizeObserver' in window ? new ResizeObserver(schedule) : null;
    if (resizeObserver) {
      observedStage && resizeObserver.observe(observedStage);
      observedAnchor && resizeObserver.observe(observedAnchor);
    }

    return () => {
      if (raf) window.cancelAnimationFrame(raf);
      window.removeEventListener('resize', schedule);
      resizeObserver?.disconnect();
    };
  }, [observedStage, observedAnchor, syncCenter]);

  React.useEffect(() => {
    if (!observedStage) return;
    syncCenter();
  }, [observedStage, observedAnchor, syncCenter]);

  return {
    center,
    stageRef: stageCallbackRef,
    anchorRef: anchorCallbackRef,
    syncCenter
  };
}
