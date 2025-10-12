import random

def guess_number():
    number = random.randint(1, 100)
    attempts = 0
    print("\nWelcome to the Higher/Lower game! Guess a number between 1 and 100.")
    while True:
        guess = input("\nYour guess: ")
        attempts += 1
        if not guess.isdigit():
            print("Please enter a valid number.")
            continue
        guess = int(guess)
        if guess == number:
            print(f"\nCongratulations! You guessed it in {attempts} attempts!")
            break
        elif guess < number:
            print("Too low. Try again.")
        else:
            print("Too high. Try again.")

if __name__ == "__main__":
    guess_number()