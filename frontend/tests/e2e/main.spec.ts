import { test, expect } from '@playwright/test';
import { io, Socket } from 'socket.io-client';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const waitForEvent = <T = any>(socket: Socket, event: string, timeoutMs = 5000) =>
  new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Timeout waiting for ${event}`)), timeoutMs);
    socket.once(event, (data: T) => {
      clearTimeout(timer);
      resolve(data);
    });
  });

async function bootstrapPokerTable(tableId: string) {
  const player1 = io(API_URL, { transports: ['websocket'] });
  const player2 = io(API_URL, { transports: ['websocket'] });

  await waitForEvent(player1, 'connected');
  await waitForEvent(player2, 'connected');

  player1.emit('authenticate', { address: '0x1111111111111111111111111111111111111111', signature: '' });
  player2.emit('authenticate', { address: '0x2222222222222222222222222222222222222222', signature: '' });
  await waitForEvent(player1, 'authenticated');
  await waitForEvent(player2, 'authenticated');

  player1.emit('join_game', { table_id: tableId, chips: 1000 });
  player2.emit('join_game', { table_id: tableId, chips: 1000 });
  await waitForEvent(player1, 'joined_game');
  await waitForEvent(player2, 'joined_game');

  player1.emit('start_hand', { table_id: tableId });
  await waitForEvent(player1, 'game_state');

  player1.disconnect();
  player2.disconnect();
}

test('Lobby navigation to Texas and Werewolf', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('lobby-title')).toBeVisible();

  await page.getByTestId('nav-texas').click();
  await expect(page).toHaveURL(/\/texas/);
  await expect(page.getByTestId('spectator-panel')).toBeVisible();

  await page.goto('/');
  await page.getByTestId('nav-werewolf').click();
  await expect(page).toHaveURL(/\/werewolf/);
  await expect(page.getByTestId('ww-spectator-panel')).toBeVisible();
});

test('Texas spectator receives live state via Socket.IO', async ({ page }) => {
  const tableId = `e2e_table_${Date.now()}`;
  await bootstrapPokerTable(tableId);

  await page.goto('/texas');
  await expect(page.getByTestId('spectator-panel')).toBeVisible();

  await page.getByTestId('table-id-input').fill(tableId);
  await page.getByTestId('table-watch').click();

  await expect(page.getByTestId('spectator-summary')).toContainText(tableId);
  await expect(page.getByTestId('pot-value')).toContainText('chips');
});
