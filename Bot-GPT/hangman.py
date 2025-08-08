import random


def hangman():
    """A simple command-line Hangman game."""
    words = [
        "python", "jules", "developer", "interface", "workspace", "feature",
        "bug", "software"
    ]
    word_to_guess = random.choice(words).lower()
    guessed_letters = set()
    incorrect_guesses = 0
    max_incorrect_guesses = 6

    hangman_stages = [
        r"""
           +---+
           |   |
               |
               |
               |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
               |
               |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
           |   |
               |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
          /|   |
               |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
          /|\  |
               |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
          /|\  |
          /    |
               |
        =========
        """,
        r"""
           +---+
           |   |
           O   |
          /|\  |
          / \  |
               |
        =========
        """
    ]

    print("Welcome to Hangman!")

    while incorrect_guesses < max_incorrect_guesses:
        print(hangman_stages[incorrect_guesses])

        display_word = ""
        for letter in word_to_guess:
            if letter in guessed_letters:
                display_word += letter + " "
            else:
                display_word += "_ "
        print(f"Word: {display_word.strip()}")
        print(f"Guessed letters: {', '.join(sorted(guessed_letters))}")

        if all(letter in guessed_letters for letter in word_to_guess):
            print("\nCongratulations! You guessed the word correctly!")
            print(f"The word was: {word_to_guess}")
            return

        guess = input("Guess a letter: ").lower()

        if len(guess) != 1 or not guess.isalpha():
            print("Invalid input. Please enter a single letter.")
            continue

        if guess in guessed_letters:
            print("You have already guessed that letter.")
            continue

        guessed_letters.add(guess)

        if guess in word_to_guess:
            print(f"Good guess! '{guess}' is in the word.")
        else:
            print(f"Sorry, '{guess}' is not in the word.")
            incorrect_guesses += 1

    print(hangman_stages[incorrect_guesses])
    print("\nGame Over! You ran out of guesses.")
    print(f"The word was: {word_to_guess}")


if __name__ == "__main__":
    hangman()
