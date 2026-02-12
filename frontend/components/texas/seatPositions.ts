interface SeatStageSize {
  width: number;
  height: number;
}

export const getSeatPosition = (index: number, totalPlayers: number, stageSize?: SeatStageSize) => {
  // Use elliptical distribution to match the poker table shape
  if (totalPlayers === 0) return { x: 0, y: 0 };

  // Distribute players evenly (start from bottom)
  const angle = (index / totalPlayers) * 2 * Math.PI + Math.PI / 2;

  const width = stageSize?.width || 1200;
  const height = stageSize?.height || 800;

  // Dynamic radii based on stage size to avoid crowding on small screens
  const radiusX = Math.min(520, Math.max(240, width * 0.36));
  const radiusY = Math.min(300, Math.max(170, height * 0.27));

  return {
    x: radiusX * Math.cos(angle),
    y: radiusY * Math.sin(angle)
  };
};
