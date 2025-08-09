import random

def hangman():
    words = ["python", "hangman", "challenge"]
    word = random.choice(words)
    display = ["_" ] * len(word)
    attempts = 6
    guessed = set()
    
    # ASCII art for hangman stages
    hangman_stages = ["""
     -----
     |   |
     |
     |
     |
     |
    """,
    """
     -----
     |   |
     O   |
     |
     |
     |
    """,
    """
     -----
     |   |
     O   |
     |   |
     |
     |
    """,
    """
     -----
     |   |
     O   |
     |   |
     /   |
     |
    """,
    """
     -----
     |   |
     O   |
     |   |
     / \  |
     |
    """,
    """
     -----
     |   |
     O   |
     |   |
     / \  |
     / \
    """,
    """
     -----
     |   |
     O   |
     |   |
     / \  |
     / \
    """]
    
    while attempts > 0 and "_" in display:
        print("".join(display))
        print(hangman_stages[6 - attempts])  # Display current hangman stage
        guess = input("Guess a letter: ").lower()
        if guess in guessed:
            print("You already guessed that!")
            continue
        guessed.add(guess)
        if guess in word:
            for i, letter in enumerate(word):
                if letter == guess:
                    display[i] = guess
        else:
            attempts -= 1
            print(f"Wrong! {attempts} attempts left.")

    if "_" not in display:
        print("Congratulations! You won!")
    else:
        print(f"You lost. The word was {word}")

hangman()