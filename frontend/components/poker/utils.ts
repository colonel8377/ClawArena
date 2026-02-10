import { Rank, Suit } from './PlayingCard';

export function parseCard(cardStr: string): { rank: Rank; suit: Suit } | null {
  if (!cardStr || cardStr.length < 2 || cardStr === '??') return null;

  const rankChar = cardStr.slice(0, -1);
  const suitChar = cardStr.slice(-1).toLowerCase();

  let rank: Rank;
  if (rankChar === 'T') rank = '10';
  else rank = rankChar as Rank;

  let suit: Suit;
  switch (suitChar) {
    case 's': suit = 'spades'; break;
    case 'h': suit = 'hearts'; break;
    case 'd': suit = 'diamonds'; break;
    case 'c': suit = 'clubs'; break;
    default: suit = 'spades'; // fallback
  }

  return { rank, suit };
}
