export const getSeatPosition = (index: number, totalPlayers: number) => {
  // Simple ellipse distribution
  // 0 is bottom center (User perspective)
  // Then clockwise
  
  // Fixed 6-max layout for better predictability
  // 0: Bottom Center
  // 1: Bottom Left
  // 2: Top Left
  // 3: Top Center
  // 4: Top Right
  // 5: Bottom Right
  
  const positions = [
    { x: '50%', y: '85%' }, // Hero/Center Bottom
    { x: '15%', y: '60%' },
    { x: '15%', y: '25%' },
    { x: '50%', y: '10%' },
    { x: '85%', y: '25%' },
    { x: '85%', y: '60%' },
  ];
  
  // If more players, we might need dynamic calc, but for now fallback to modulo
  return positions[index % positions.length];
};
