import { useEffect, useRef } from 'react';
import { ensureSocketMode } from '@/lib/socket';
import { unwrapSocketPayload } from '@/lib/stateAdapters';
import { getBotToken } from '@/lib/antiBot';

type EventHandler = (data: any) => void;

interface UseSpectatorSocketProps {
  namespace: string;
  tableId: string;
  events: Record<string, EventHandler>;
  revealMode?: boolean;
}

export function useSpectatorSocket({ namespace, tableId, events }: UseSpectatorSocketProps) {
  const socketRef = useRef<ReturnType<typeof getSocket> | null>(null);
  const rafRef = useRef<number | null>(null);
  const pendingUpdates = useRef<Map<string, any>>(new Map());
  const coalesceEvents = useRef<Set<string>>(
    new Set([
      'room:state',
      'room:update',
      'tx:phase:change',
      'ww:phase:change',
    ])
  );

  useEffect(() => {
    const socket = ensureSocketMode('spectator');
    if (!socket) return;
    socketRef.current = socket;

    const activeSocket = socket;

    // Join logic
    const joinRoom = () => {
      const roomId = Number(tableId);
      if (!Number.isFinite(roomId) || roomId <= 0) {
        return;
      }
      console.log(`[Spectator] Joining ${namespace} room: ${tableId}`);
      activeSocket.emit('room:join', { room_id: roomId, role: 2 });
    };

    if (activeSocket.connected) {
      joinRoom();
    }

    activeSocket.on('connect', joinRoom);

    // Event binding with RAF throttling
    Object.entries(events).forEach(([eventName, handler]) => {
      activeSocket.on(eventName, (data: any) => {
        const payload = unwrapSocketPayload(data);
        if (!coalesceEvents.current.has(eventName)) {
          handler(payload);
          return;
        }

        // Throttle high-frequency state updates; keep only the latest per event.
        pendingUpdates.current.set(eventName, payload);
        if (!rafRef.current) {
          rafRef.current = requestAnimationFrame(() => {
            pendingUpdates.current.forEach((data, evt) => {
              if (events[evt]) {
                events[evt](data);
              }
            });
            pendingUpdates.current.clear();
            rafRef.current = null;
          });
        }
      });
    });

    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }
      
      activeSocket.emit('room:leave', {});
      
      activeSocket.off('connect', joinRoom);
      Object.keys(events).forEach((eventName) => {
        activeSocket.off(eventName);
      });
    };
  }, [namespace, tableId]); // Re-run if these change
}
