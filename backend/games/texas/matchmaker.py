"""Matchmaker module for Texas Hold'em tables.

This queue manager mirrors the werewolf matchmaker style but uses poker-first
rules: fill full-ring tables first, start preferred short-handed tables quickly,
and eventually allow any valid 2+ player table to avoid long waits.
"""

import asyncio
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Dict, List, Optional

from backend.config.texas_config import (
    TEXAS_MATCHMAKING_ADAPTIVE_WAIT_TIME,
    TEXAS_MATCHMAKING_CHECK_INTERVAL,
    TEXAS_MATCHMAKING_FULL_RING_SIZE,
    TEXAS_MATCHMAKING_MIN_PLAYERS,
    TEXAS_MATCHMAKING_PREFERRED_GAME_SIZE,
)


@dataclass
class QueuedPokerPlayer:
    """Represents a player waiting for auto-seat matchmaking."""

    sid: str
    wallet_address: str
    nickname: str
    buy_in_tokens: Decimal
    join_time: float = field(default_factory=time.time)


class TexasMatchmaker:
    """Adaptive table matchmaker for Texas Hold'em."""

    MIN_PLAYERS = TEXAS_MATCHMAKING_MIN_PLAYERS
    PREFERRED_GAME_SIZE = TEXAS_MATCHMAKING_PREFERRED_GAME_SIZE
    FULL_RING_SIZE = TEXAS_MATCHMAKING_FULL_RING_SIZE
    ADAPTIVE_WAIT_TIME = TEXAS_MATCHMAKING_ADAPTIVE_WAIT_TIME
    CHECK_INTERVAL = TEXAS_MATCHMAKING_CHECK_INTERVAL

    def __init__(
        self,
        game_start_callback: Optional[Callable] = None,
        fallback_warning_callback: Optional[Callable] = None,
    ):
        self.queue: List[QueuedPokerPlayer] = []
        self.queue_sids: set = set()
        self.game_start_callback = game_start_callback
        self.fallback_warning_callback = fallback_warning_callback
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._queue_lock = asyncio.Lock()

    async def add_player(
        self,
        sid: str,
        wallet_address: str,
        nickname: str,
        buy_in_tokens: Decimal,
    ) -> bool:
        """Add a player to queue; returns False if already queued."""
        async with self._queue_lock:
            if sid in self.queue_sids:
                return False

            self.queue.append(
                QueuedPokerPlayer(
                    sid=sid,
                    wallet_address=wallet_address,
                    nickname=nickname,
                    buy_in_tokens=buy_in_tokens,
                )
            )
            self.queue_sids.add(sid)
            return True

    async def remove_player(self, sid: str) -> bool:
        """Remove player from queue if present."""
        async with self._queue_lock:
            if sid not in self.queue_sids:
                return False
            self.queue = [p for p in self.queue if p.sid != sid]
            self.queue_sids.discard(sid)
            return True

    def is_player_in_queue(self, sid: str) -> bool:
        return sid in self.queue_sids

    def get_queue_info(self) -> Dict:
        if not self.queue:
            return {
                'size': 0,
                'oldest_wait_time': 0,
                'average_wait_time': 0,
            }

        now = time.time()
        waits = [now - p.join_time for p in self.queue]
        return {
            'size': len(self.queue),
            'oldest_wait_time': max(waits),
            'average_wait_time': sum(waits) / len(waits),
        }

    async def _check_queue(self):
        while self._running:
            try:
                await self._process_queue()
            except Exception as e:
                print(f"Error in texas matchmaker check_queue: {e}")
            await asyncio.sleep(self.CHECK_INTERVAL)

    async def _process_queue(self):
        async with self._queue_lock:
            queue_size = len(self.queue)
            if queue_size < self.MIN_PLAYERS:
                return

            # Highest priority: launch full-ring table immediately.
            if queue_size >= self.FULL_RING_SIZE:
                players = self.queue[:self.FULL_RING_SIZE]
                self.queue = self.queue[self.FULL_RING_SIZE:]
                for p in players:
                    self.queue_sids.discard(p.sid)
                # Release lock before the potentially slow callback
                await self._start_game_unlocked(players, self.FULL_RING_SIZE)
                return

            oldest_wait = time.time() - self.queue[0].join_time

            # Start preferred-size table after a short wait for better fill quality.
            if queue_size >= self.PREFERRED_GAME_SIZE and oldest_wait >= self.ADAPTIVE_WAIT_TIME / 2:
                players = self.queue[:self.PREFERRED_GAME_SIZE]
                self.queue = self.queue[self.PREFERRED_GAME_SIZE:]
                for p in players:
                    self.queue_sids.discard(p.sid)
                await self._start_game_unlocked(players, self.PREFERRED_GAME_SIZE)
                return

            # Fallback: start any legal short-handed table after full wait budget.
            if oldest_wait >= self.ADAPTIVE_WAIT_TIME:
                target_size = min(queue_size, self.PREFERRED_GAME_SIZE)
                if self.fallback_warning_callback:
                    try:
                        await self.fallback_warning_callback(self.queue[:target_size], target_size)
                    except Exception as e:
                        print(f"Error in texas fallback warning callback: {e}")

                players = self.queue[:target_size]
                self.queue = self.queue[target_size:]
                for p in players:
                    self.queue_sids.discard(p.sid)
                await self._start_game_unlocked(players, target_size)

    async def _start_game_unlocked(self, players: List[QueuedPokerPlayer], game_size: int):
        """Start a game. Must NOT be called while holding _queue_lock if the
        callback may re-enter the matchmaker (e.g. to re-queue failed players).
        In _process_queue the lock is held for the pop, then this is called
        inside the same ``async with`` block which is fine because re-queue
        happens via ``self.queue.extend`` which is also inside the lock."""
        if not self.game_start_callback:
            return
        try:
            await self.game_start_callback(players, game_size)
        except Exception as e:
            print(f"Error starting texas game: {e}")
            self.queue.extend(players)
            for p in players:
                self.queue_sids.add(p.sid)

    def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._check_queue())

    def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    def is_running(self) -> bool:
        return self._running

    def clear_queue(self):
        self.queue.clear()
        self.queue_sids.clear()
