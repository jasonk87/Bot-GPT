import pygame
import random
import numpy as np
import time

# Initialize Pygame
pygame.init()

# Screen dimensions
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("AI Platformer (RL)")

# Colors
WHITE = (255, 255, 255)
BLUE = (0, 0, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)

# Clock
clock = pygame.time.Clock()
FPS = 60

# Player class
class Player(pygame.sprite.Sprite):
    def __init__(self):
        super().__init__()
        self.image = pygame.Surface((40, 40))
        self.image.fill(BLUE)
        self.rect = self.image.get_rect()
        self.rect.center = (WIDTH//2, HEIGHT - 50)
        self.vel_y = 0
        self.jumping = False
        self.completed_level = False

    def update(self, platforms):
        # Human controls
        keys = pygame.key.get_pressed()
        dx = 0
        if keys[pygame.K_LEFT]:
            dx = -5
        if keys[pygame.K_RIGHT]:
            dx = 5
        self.rect.x += dx

        # Jump
        if keys[pygame.K_SPACE] and not self.jumping:
            self.vel_y = -15
            self.jumping = True

        # Gravity
        self.vel_y += 1
        self.rect.y += self.vel_y

        # Platform collision
        for platform in platforms:
            if self.rect.colliderect(platform.rect):
                if self.vel_y > 0:
                    self.rect.bottom = platform.rect.top
                    self.vel_y = 0
                    self.jumping = False
                elif self.vel_y < 0:
                    self.rect.top = platform.rect.bottom
                    self.vel_y = 0

        # Level completion
        if self.rect.right > WIDTH:
            self.completed_level = True

# Platform class
class Platform(pygame.sprite.Sprite):
    def __init__(self, x, y, width, height):
        super().__init__()
        self.image = pygame.Surface((width, height))
        self.image.fill(GREEN)
        self.rect = self.image.get_rect(topleft=(x, y))

# Game setup
player = Player()
platforms = pygame.sprite.Group()

for i in range(10):
    platform = Platform(100 + i*200, HEIGHT - 50 - i*30, 150, 20)
    platforms.add(platform)

# RL Parameters
state_size = 4  # (x, y, vel_y, jumping)
action_size = 3  # left, right, jump
learning_rate = 0.01
discount = 0.99
epsilon = 1.0
epsilon_decay = 0.995
epsilon_min = 0.01

# Initialize networks
class QNetwork:
    def __init__(self, state_size, action_size):
        self.state_size = state_size
        self.action_size = action_size
        self.weights = np.random.randn(state_size, action_size) * 0.01

    def predict(self, state):
        return np.dot(state, self.weights)

    def train(self, state, action, target):
        self.weights += learning_rate * (target - np.dot(state, self.weights)) * state

class TargetNetwork:
    def __init__(self, state_size, action_size):
        self.state_size = state_size
        self.action_size = action_size
        self.weights = np.random.randn(state_size, action_size) * 0.01

    def predict(self, state):
        return np.dot(state, self.weights)

# Training mode
training_mode = False

# Game loop
running = True
while running:
    clock.tick(FPS)
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_t:
                training_mode = not training_mode
                print("Training mode:", training_mode)

    # Update
    if training_mode:
        # Get state
        state = np.array([
            player.rect.x / WIDTH,
            player.rect.y / HEIGHT,
            player.vel_y / 10,
            player.jumping
        ])

        # Epsilon-greedy action selection
        if random.random() < epsilon:
            action = random.randint(0, 2)
        else:
            action_values = q_network.predict(state)
            action = np.argmax(action_values)

        # Map action to movement
        if action == 0:
            player.rect.x -= 5
        elif action == 1:
            player.rect.x += 5
        elif action == 2:
            if not player.jumping:
                player.vel_y = -15
                player.jumping = True

        # Update player position
        player.vel_y += 1
        player.rect.y += player.vel_y

        # Platform collision
        for platform in platforms:
            if player.rect.colliderect(platform.rect):
                if player.vel_y > 0:
                    player.rect.bottom = platform.rect.top
                    player.vel_y = 0
                    player.jumping = False
                elif player.vel_y < 0:
                    player.rect.top = platform.rect.bottom
                    player.vel_y = 0

        # Level completion
        if player.rect.right > WIDTH:
            reward = 100
            next_state = np.array([
                player.rect.x / WIDTH,
                player.rect.y / HEIGHT,
                player.vel_y / 10,
                player.jumping
            ])
            replay_memory.add(state, action, reward, next_state)
            print("Level completed! Reward:", reward)
            time.sleep(2)
            player.rect.center = (WIDTH//2, HEIGHT - 50)
            player.jumping = False
            player.vel_y = 0
            player.completed_level = False
        else:
            # Penalize falling
            if player.rect.y > HEIGHT:
                reward = -100
                next_state = np.array([
                    player.rect.x / WIDTH,
                    player.rect.y / HEIGHT,
                    player.vel_y / 10,
                    player.jumping
                ])
                replay_memory.add(state, action, reward, next_state)
                player.rect.y = HEIGHT - 50
                player.vel_y = 0
                player.jumping = False

        # Train the network
        if len(replay_memory.memory) > 32:
            batch = replay_memory.sample(32)
            for state, action, reward, next_state in batch:
                target = reward + discount * target_network.predict(next_state)
                q_network.train(state, action, target)

        # Update target network
        if random.random() < 0.1:
            target_network.weights = q_network.weights

        # Decay epsilon
        epsilon = max(epsilon_min, epsilon * epsilon_decay)

    # Draw
    screen.fill(WHITE)
    platforms.draw(screen)
    screen.blit(player.image, player.rect)
    pygame.display.flip()

pygame.quit()