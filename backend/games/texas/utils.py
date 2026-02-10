import re

def censor_card_info(message: str) -> str:
    """
    Censor playing card information from chat messages.
    
    Replaces card patterns (e.g., "Ah", "Ks", "10d", "Ace of Spades") with "***".
    
    Args:
        message: The original chat message.
        
    Returns:
        The message with card information censored.
    """
    if not message:
        return message

    # Regex patterns for card detection
    
    # 1. Short notation: Rank + Suit (e.g., Ah, Ks, 10d, 2c)
    # Ranks: 2-9, 10, J, Q, K, A
    # Suits: s, h, d, c (case insensitive)
    # \b ensures we don't match inside words (e.g., "bash" shouldn't match "as")
    short_pattern = r'\b([2-9]|10|[JQKAjqka])[shdcSHDC]\b'
    
    # 2. Long notation: Rank + "of" + Suit (e.g., Ace of Spades)
    ranks = r'(?:Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Jack|Queen|King|Ace)'
    suits = r'(?:Spades|Hearts|Diamonds|Clubs)'
    long_pattern = f'\\b{ranks}\\s+of\\s+{suits}\\b'
    
    # Apply filters (case insensitive for long pattern too just in case)
    censored = re.sub(short_pattern, '***', message)
    censored = re.sub(long_pattern, '***', censored, flags=re.IGNORECASE)
    
    return censored
