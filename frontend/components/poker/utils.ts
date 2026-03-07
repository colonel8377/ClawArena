import { Rank, Suit } from './PlayingCard';

export function parseCard(cardStr: string): { rank: Rank; suit: Suit } | null {
  if (!cardStr || cardStr.length < 2 || cardStr === '??') return null;

  const normalized = cardStr.trim();
  const shortMatch = normalized.match(/^(10|[2-9TJQKA])([shdc])$/i);

  let rankChar = '';
  let suitChar = '';

  if (shortMatch) {
    rankChar = shortMatch[1];
    suitChar = shortMatch[2].toLowerCase();
  } else {
    return null;
  }

  let rank: Rank;
  const numericRank = Number(rankChar);
  if (Number.isFinite(numericRank)) {
    if (numericRank === 1 || numericRank === 14) rank = 'A';
    else if (numericRank === 11) rank = 'J';
    else if (numericRank === 12) rank = 'Q';
    else if (numericRank === 13) rank = 'K';
    else if (numericRank === 10) rank = '10';
    else rank = String(numericRank) as Rank;
  } else if (rankChar.toUpperCase() === 'T') {
    rank = '10';
  } else {
    rank = rankChar.toUpperCase() as Rank;
  }

  let suit: Suit;
  switch (suitChar) {
    case 's':
    case '♠':
      suit = 'spades';
      break;
    case 'h':
    case '♥':
      suit = 'hearts';
      break;
    case 'd':
    case '♦':
      suit = 'diamonds';
      break;
    case 'c':
    case '♣':
      suit = 'clubs';
      break;
    default:
      return null;
  }

  return { rank, suit };
}
