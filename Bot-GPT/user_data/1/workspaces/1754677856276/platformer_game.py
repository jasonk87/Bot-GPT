import pygame
import sys

pygame.init()
screen = pygame.display.set_mode((800, 600))
pygame.display.set_caption('Platformer Game')

clock = pygame.time.Clock()
gravity = 0.5
player_jump = -15
player_speed = 5

class Player:
    def __init__(self):
        self.rect = pygame.Rect(50, 500, 50, 50)
        self.velocity = pygame.math.Vector2(0, 0)

    def update(self, keys):
        self.velocity.y += gravity
        
        # Movement
        if keys[pygame.K_LEFT]:
            self.velocity.x = -player_speed
        elif keys[pygame.K_RIGHT]:
            self.velocity.x = player_speed
        else:
            self.velocity.x = 0
        
        # Jumping
        if keys[pygame.K_SPACE] and self.rect.y >= 550:
            self.velocity.y = player_jump
        
        # Apply velocity
        self.rect.x += self.velocity.x
        self.rect.y += self.velocity.y

    def draw(self):
        pygame.draw.rect(screen, (0, 0, 255), self.rect)

player = Player()

while True:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
    
    keys = pygame.key.get_pressed()
    player.update(keys)
    screen.fill((255, 255, 255))
    player.draw()
    pygame.display.update()
    clock.tick(60)