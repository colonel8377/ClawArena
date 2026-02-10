export const getWerewolfSeatPosition = (index: number, totalPlayers: number, radius = 40) => {
  // Center is 50, 50 (percent)
  // -90 degrees is top
  const angle = (index / totalPlayers) * 2 * Math.PI - Math.PI / 2;
  const x = 50 + radius * Math.cos(angle);
  const y = 50 + radius * Math.sin(angle);
  return { x: `${x}%`, y: `${y}%`, rawX: x, rawY: y };
};
