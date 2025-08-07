import pygame
import sys

# Initialize Pygame
pygame.init()

# Screen dimensions
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Life Simulation Game")

# Colors
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)

# Player class
class Player:
    def __init__(self):
        self.health = 100
        self.hunger = 100
        self.money = 50
        self.day = 1

    def update(self):
        # Simple resource decay
        self.hunger -= 1
        self.health -= 0.5

        # Regenerate some health
        if self.health < 80:
            self.health += 1

    def draw(self, surface):
        pygame.draw.rect(surface, GREEN, (50, 50, 50, 50))
        font = pygame.font.SysFont(None, 36)
        text = font.render(f"Day {self.day}", True, BLACK)
        surface.blit(text, (50, 100))

        # Display stats
        stats = [
            f"Health: {int(self.health)}",
            f"Hunger: {int(self hunger)}",
            f"Money: ${self.money}"
        ]

        for i, stat in enumerate(stats):
            text = font.render(stat, True, BLACK)
            surface.blit(text, (50, 150 + i*40))

# Game loop
def main():
    clock = pygame.time.Clock()
    player = Player()
    running = True

    while running:
        screen.fill(WHITE)

        # Event handling
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            # Key presses for actions
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1:  # Work
                    player.money += 20
                    player.hunger -= 10
                elif event.key == pygame.K_2:  # Eat
                    player.hunger += 20
                    player.money -= 5
                elif event.key == pygame.K_3:  # Rest
                    player.health += 15
                    player.hunger -= 5

        # Update game state
        player.update()
        player.day += 0.01  # Slow day progression

        # Check for game over
        if player.hunger <= 0 or player.health <= 0:
            font = pygame.font.SysFont(None, 72)
            text = font.render("Game Over!", True, RED)
            screen.blit(text, (WIDTH//2 - 150, HEIGHT//2 - 36))
            pygame.display.flip()
            pygame.time.wait(3000)
            running = False

        # Draw player
        player.draw(screen)

        # Update display
        pygame.display.flip()
        clock.tick(10)  # 10 FPS

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()