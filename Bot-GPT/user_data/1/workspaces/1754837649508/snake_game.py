import pygame
import time
import random

pygame.init()

# Colors
white = (255, 255, 25, 255)
yellow = (255, 255, 0)
black = (0, 0, 0)
red = (213, 50, 80)
green = (0, 255, 0)
blue = (50, 153, 213)

# Display settings
width = 600
height = 400
speed = 15

display = pygame.display.set_mode((width, height))
pygame.display.set_caption('Snake Game by AI')

clock = pygame.time.Clock()

font_style = pygame.font.SysFont("bahnschrift", 25)

def score(score):
    value = font_style.render(f"Score: {score}", True, yellow)
    display.blit(value, [0, 0])

def message(msg, color):
    mesg = font_style.render(msg, True, color)
    display.blit(mesg, [width/6, height/3])

def game_loop():
    game_over = False
    game_close = False
    x1 = width / 2
    y1 = height / 2
    x1_change = 0
    y1_change = 0
    snake_list = []
    length_of_snake = 1

    foodx = round(random.randrange(0, width - 10) / 10) * 10
    foody = round(random.randrange(0, height - 10) / 10) * 10

    while not game_over:
        while game_close:
            display.fill(blue)
            message("You Lost! Press Q-Quit or C-Play Again", red)
            score(length_of_snake - 1)
            pygame.display.update()

            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_q:
                        game_over = True
                        game_close = False
                    if event.key == pygame.K_c:
                        game_loop()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game_over = True
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_LEFT:
                    x1_change = -speed
                    y1_change = 0
                elif event.key == pygame.K_RIGHT:
                    x1_change = speed
                    y1_change = 0
                elif event.key == pygame.K_UP:
                    y1_change = -speed
                    x1_change = 0
                elif event.key == pygame.K_DOWN:
                    y1_change = speed
                    x1_change = 0

        if x1 >= width or x1 < 0 or y1 >= height or y1 < 0:
            game_close = True

        x1 += x1_change
        y1 += y1_change
        display.fill(black)
        pygame.draw.rect(display, green, [foodx, foody, 10, 10])
        snake_head = [x1, y1]
        snake_list.append(snake_head)
        if len(snake_list) > length_of_snake:
            del snake_list[0]

        for x in snake_list[:-1]:
            if x == snake_head:
                game_close = True

        for segment in snake_list:
            pygame.draw.rect(display, white, [segment[0], segment[1], 10, 10])

        score(length_of_snake - 1)
        pygame.display.update()

        if x1 == foodx and y1 == foody:
            foodx = round(random.randrange(0, width - 10) / 10) * 10
            foody = round(random.randrange(0, height - 10) / 10) * 10
            length_of_snake += 1

        clock.tick(speed)

    pygame.quit()
    quit()

if __name__ == "__main__":
    game_loop()
