import { useEffect, useRef } from 'react';
import { ensureSocketMode } from '@/lib/socket';
import { unwrapSocketPayload } from '@/lib/stateAdapters';

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

  // Keep track of the latest events object to avoid stale closures without re-subscribing
  const eventsRef = useRef(events);
  eventsRef.current = events;

  useEffect(() => {
    const socket = ensureSocketMode('spectator');
    if (!socket) return;
    socketRef.current = socket;
    pendingUpdates.current.clear();

    const activeSocket = socket;
    const expectedRoomId = Number(tableId);
    const resolveRoomId = (payload: any) => {
      const candidates = [
        payload?.room_id,
        payload?.roomId,
        payload?.payload?.room_id,
        payload?.payload?.roomId,
      ];
      for (const candidate of candidates) {
        const value = Number(candidate);
        if (Number.isFinite(value) && value > 0) return value;
      }
      return null;
    };

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

    // Store the actual handlers we bind so we can unbind them specifically
    const boundHandlers: Record<string, (data: any) => void> = {};

    // Event binding with RAF throttling
    Object.keys(eventsRef.current).forEach((eventName) => {
      const wrappedHandler = (data: any) => {
        const payload = unwrapSocketPayload(data);
        const payloadRoomId = resolveRoomId(payload);
        
        // Strict room check to prevent cross-talk
        if (payloadRoomId && Number.isFinite(expectedRoomId) && payloadRoomId !== expectedRoomId) {
          return;
        }

        if (!coalesceEvents.current.has(eventName)) {
          // Always call the latest handler
          eventsRef.current[eventName]?.(payload);
          return;
        }

        // Throttle high-frequency state updates; keep only the latest per event.
        pendingUpdates.current.set(eventName, payload);
        if (!rafRef.current) {
          rafRef.current = requestAnimationFrame(() => {
            pendingUpdates.current.forEach((data, evt) => {
              eventsRef.current[evt]?.(data);
            });
            pendingUpdates.current.clear();
            rafRef.current = null;
          });
        }
      };

      boundHandlers[eventName] = wrappedHandler;
      activeSocket.on(eventName, wrappedHandler);
    });

    return () => {
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
      }
      const roomId = Number(tableId);
      activeSocket.emit('room:leave', {
        room_id: Number.isFinite(roomId) && roomId > 0 ? roomId : undefined,
        role: 2,
      });
      
      activeSocket.off('connect', joinRoom);
      
      // Cleanup ONLY our specific handlers
      Object.entries(boundHandlers).forEach(([eventName, handler]) => {
        activeSocket.off(eventName, handler);
      });
    };
  }, [namespace, tableId]); // Re-run if these change
}
