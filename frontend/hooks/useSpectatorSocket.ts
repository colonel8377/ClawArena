import { useEffect, useRef } from 'react';
import { getSocket } from '@/lib/socket';

type EventHandler = (data: any) => void;

interface UseSpectatorSocketProps {
  namespace: string; // 'texas' or 'werewolf'
  tableId: string;
  events: Record<string, EventHandler>;
  revealMode?: boolean;
}

export function useSpectatorSocket({ namespace, tableId, events, revealMode = false }: UseSpectatorSocketProps) {
  const socketRef = useRef<ReturnType<typeof getSocket> | null>(null);
  const rafRef = useRef<number | null>(null);
  const pendingUpdates = useRef<Map<string, any>>(new Map());

  useEffect(() => {
    const socket = getSocket();
    if (!socket) return;
    socketRef.current = socket;

    const activeSocket = socket;

    // Join logic
    const joinEvent = namespace === 'texas' ? 'join_spectate' : 'join_spectate';
    const payloadKey = namespace === 'texas' ? 'table_id' : 'game_id';
    
    const joinRoom = () => {
      console.log(`[Spectator] Joining ${namespace} room: ${tableId} (Reveal: ${revealMode})`);
      activeSocket.emit(joinEvent, { [payloadKey]: tableId, reveal: revealMode });
    };

    if (activeSocket.connected) {
      joinRoom();
    }

    activeSocket.on('connect', joinRoom);

    // Event binding with RAF throttling
    Object.entries(events).forEach(([eventName, handler]) => {
      activeSocket.on(eventName, (data: any) => {
        // Simple throttling: store latest data for this event
        pendingUpdates.current.set(eventName, data);
        
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
      
      const leavePayload = { [payloadKey]: tableId };
      activeSocket.emit('leave_spectate', leavePayload);
      
      activeSocket.off('connect', joinRoom);
      Object.keys(events).forEach((eventName) => {
        activeSocket.off(eventName);
      });
    };
  }, [namespace, tableId, revealMode]); // Re-run if these change
}
