import random

def hangman():
    words = ['python', 'javascript', 'ruby', 'java', 'csharp', 'html', 'css']
    word = random.choice(words)
    guessed = ['_'] * len(word)
    attempts = 6
    guessed_letters = []

    print("Welcome to Hangman!")
    print(" ".join(guessed))

    while attempts > 0 and "_" in guessed:
        guess = input("\nGuess a letter: ").lower()

        if len(guess) != 1 or not guess.isalpha():
            print("Please enter a single letter.")
            continue

        if guess in guessed_letters:
            print("You already guessed that letter.")
            continue

        guessed_letters.append(guess)

        if guess in word:
            for i in range(len(word)):
                if word[i] == guess:
                    guessed[i] = guess
            print(" ".join(guessed))
        else:
            attempts -= 1
            print("Wrong guess! You have", attempts, "attempts left.")
            print(" ".join(guessed))

    if "_" not in guessed:
        print("\nCongratulations! You guessed the word:", word)
    else:
        print("\nGame over! The word was:", word)

hangman()