export const getWerewolfSeatPosition = (index: number, totalPlayers: number, radiusPx = 280) => {
  if (totalPlayers <= 0) {
    return {
      x: 0,
      y: 0
    };
  }

  // Center is 50%, 50%
  // -90 degrees is top
  const angle = (index / totalPlayers) * 2 * Math.PI - Math.PI / 2;
  
  // Use pixel offsets from center to ensure perfect circle
  const xOffset = radiusPx * Math.cos(angle);
  const yOffset = radiusPx * Math.sin(angle);
  
  return { 
    x: xOffset,
    y: yOffset
  };
};
