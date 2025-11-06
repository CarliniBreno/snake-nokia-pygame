import pygame
import random
import threading
import socket
import queue
import time
import sys


try:
    import serial
    SERIAL_AVAILABLE = True
except Exception:
    serial = None
    SERIAL_AVAILABLE = False

# --- CONFIGURAÇÃO
UDP_LISTEN_HOST = '0.0.0.0'
UDP_LISTEN_PORT = 5005
SERIAL_ENABLED = False
SERIAL_PORT = 'COM3'
SERIAL_BAUD = 115200


GRID_W = 64
GRID_H = 32
TILE = 16
HUD_TILES = 2

SCREEN_W = GRID_W * TILE
SCREEN_H = HUD_TILES * TILE + GRID_H * TILE

SPEED = 8

DISPLAY_GREEN = (162, 255, 75)
BLACK = (0, 0, 0)

FOOD_COLORS = [ (200,20,20),
                (20,60,200),
                (150,40,180),
                (230,120,20) ]


HUNGER_LIMIT = 20.0

# --- INPUT REMOTO
input_queue = queue.Queue()

def udp_listener(stop_event, q, host=UDP_LISTEN_HOST, port=UDP_LISTEN_PORT):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.settimeout(1.0)
    while not stop_event.is_set():
        try:
            data, addr = s.recvfrom(64)
            cmd = data.decode('utf-8', errors='ignore').strip().upper()
            if cmd:
                q.put(('remote', cmd))
        except socket.timeout:
            continue
        except Exception:
            continue
    s.close()

def serial_listener(stop_event, q, port=SERIAL_PORT, baud=SERIAL_BAUD):
    if not SERIAL_AVAILABLE:
        print('pyserial não disponível; serial desativado')
        return
    try:
        ser = serial.Serial(port, baud, timeout=1)
    except Exception as e:
        print('Falha ao abrir serial:', e)
        return
    while not stop_event.is_set():
        try:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                q.put(('remote', line.upper()))
        except Exception:
            continue
    ser.close()

# --- JOGO
class SnakeGame:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption('Snake - Nokia Style 32x64')
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont('dejavusans', TILE)
        self.large_font = pygame.font.SysFont('dejavusans', TILE*2)
        self.reset()

    def reset(self):
        self.state = 'menu'
        cx, cy = GRID_W//2, GRID_H//2
        self.snake = [(cx,cy), (cx-1,cy), (cx-2,cy)]
        self.direction = (1,0)
        self.next_direction = self.direction
        self.spawn_food()
        self.score = 0
        self.speed = SPEED
        self.move_timer = 0.0
        self.move_delay = 1.0 / self.speed
        self.hunger_timer = 0.0  # segundos desde último alimento
        self.hunger_limit = HUNGER_LIMIT

        # gameover menu selection (0 = Reiniciar, 1 = Sair)
        self.gameover_selection = 0

        # se começando do menu, mantém menu; se reiniciado manualmente via 'R' definimos playing depois
        # (o process_input_cmd já lida com RESET)

    def spawn_food(self):
        while True:
            x = random.randint(0, GRID_W-1)
            y = random.randint(0, GRID_H-1)
            if (x,y) not in self.snake:
                self.food = (x,y)
                self.food_color = random.choice(FOOD_COLORS)
                break

    def grid_to_pixel(self, gx, gy):
        px = gx * TILE
        py = HUD_TILES * TILE + gy * TILE
        return px, py

    def draw(self):
        # campo todo verde
        self.screen.fill(DISPLAY_GREEN)

        # HUD (topo) em preto estilo Nokia: score e linha abaixo
        hud_rect = pygame.Rect(0, 0, SCREEN_W, HUD_TILES * TILE)
        pygame.draw.rect(self.screen, BLACK, hud_rect)

        # grade pequena na HUD (estética)
        for x in range(0, SCREEN_W, TILE//2):
            pygame.draw.rect(self.screen, BLACK, (x, (HUD_TILES*TILE)//2, max(1, TILE//4), max(1, TILE//4)))

        # linha horizontal abaixo do HUD
        pygame.draw.line(self.screen, BLACK, (0, HUD_TILES*TILE - 1), (SCREEN_W, HUD_TILES*TILE - 1))

        # SCORE (preto sobre fundo verde localizado na esquerda do HUD)
        score_text = f'{self.score:04d}'
        score_bg_w = TILE * 8
        score_bg_h = HUD_TILES * TILE
        score_bg = pygame.Rect(6, 0, score_bg_w, score_bg_h)
        pygame.draw.rect(self.screen, DISPLAY_GREEN, score_bg)
        score_surf = self.font.render(score_text, True, BLACK)
        self.screen.blit(score_surf, (10, (HUD_TILES*TILE - score_surf.get_height())//2))

        # TIMER (topo direito) - tempo restante até o hunger gameover
        time_left = max(0.0, self.hunger_limit - self.hunger_timer)
        # desenhar fundo verde na área do timer para contraste
        timer_text = f'{time_left:0.1f}s'
        timer_surf = self.font.render(timer_text, True, BLACK)
        timer_w = timer_surf.get_width() + 10
        timer_bg = pygame.Rect(SCREEN_W - timer_w - 6, 0, timer_w, score_bg_h)
        pygame.draw.rect(self.screen, DISPLAY_GREEN, timer_bg)
        self.screen.blit(timer_surf, (SCREEN_W - timer_w - 1, (HUD_TILES*TILE - timer_surf.get_height())//2))

        # desenha cobra (preta) — cobra mais fina: ocupando 70% do tile
        seg_w = int(TILE * 0.7)
        seg_h = int(TILE * 0.7)
        for i, (sx, sy) in enumerate(self.snake):
            px, py = self.grid_to_pixel(sx, sy)
            seg_rect = pygame.Rect(px + (TILE-seg_w)//2, py + (TILE-seg_h)//2, seg_w, seg_h)
            pygame.draw.rect(self.screen, BLACK, seg_rect, border_radius=max(1, seg_w//6))

        # desenha comida colorida (um quadrado menor)
        fx, fy = self.food
        fpx, fpy = self.grid_to_pixel(fx, fy)
        food_size = int(TILE * 0.6)
        food_rect = pygame.Rect(fpx + (TILE-food_size)//2, fpy + (TILE-food_size)//2, food_size, food_size)
        pygame.draw.rect(self.screen, self.food_color, food_rect, border_radius=2)

        # overlays (menu / pause / gameover)
        if self.state == 'menu':
            self._draw_center_text('SNAKE - Pressione ENTER para jogar', self.large_font, (SCREEN_W//2, SCREEN_H//2 - 30))
            self._draw_center_text('WASD ou setas para mover. ESP32 via UDP porta %d' % UDP_LISTEN_PORT, self.font, (SCREEN_W//2, SCREEN_H//2 + 20))
        elif self.state == 'paused':
            # overlay escuro semi-transparente
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0,0,0,160))
            self.screen.blit(overlay, (0,0))
            self._draw_center_text('PAUSE', self.large_font, (SCREEN_W//2, SCREEN_H//2))
            self._draw_center_text('Pressione P ou ESC para voltar', self.font, (SCREEN_W//2, SCREEN_H//2 + 40))
        elif self.state == 'gameover':
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0,0,0,200))
            self.screen.blit(overlay, (0,0))
            self._draw_center_text('GAME OVER', self.large_font, (SCREEN_W//2, SCREEN_H//2 - 60))
            self._draw_center_text(f'Score final: {self.score}', self.font, (SCREEN_W//2, SCREEN_H//2 - 20))

            # opções Reiniciar / Sair
            opts = ['Reiniciar', 'Sair']
            base_y = SCREEN_H//2 + 10
            for idx, txt in enumerate(opts):
                color = (200,200,200) if idx == self.gameover_selection else (150,150,150)
                surf = self.font.render(txt, True, color)
                r = surf.get_rect(center=(SCREEN_W//2, base_y + idx*(TILE*1.4)))
                self.screen.blit(surf, r)

        pygame.display.flip()

    def _draw_center_text(self, txt, font, pos):
        surf = font.render(txt, True, BLACK)
        r = surf.get_rect(center=pos)
        self.screen.blit(surf, r)

    def step(self):
        head = self.snake[0]
        dx, dy = self.direction
        new_head = (head[0] + dx, head[1] + dy)
        new_head = (new_head[0] % GRID_W, new_head[1] % GRID_H)

        # colisão com self
        if new_head in self.snake:
            self.state = 'gameover'
            # deixa o cursor de seleção no primeiro item
            self.gameover_selection = 0
            return

        self.snake.insert(0, new_head)

        if new_head == self.food:
            self.score += 1
            self.spawn_food()
            self.speed = min(25, SPEED + self.score//5)
            self.move_delay = 1.0 / self.speed
            # reset do timer de fome ao comer
            self.hunger_timer = 0.0
        else:
            self.snake.pop()

    def process_input_cmd(self, source, cmd):
        map_short = {'U':'UP','D':'DOWN','L':'LEFT','R':'RIGHT','P':'PAUSE','X':'RESET'}
        if len(cmd) == 1 and cmd in map_short:
            cmd = map_short[cmd]

        # tratamento especial: quando estiver em gameover, use teclas para navegar nas opções
        if self.state == 'gameover':
            if cmd in ('UP','W','ARROWUP','LEFT','A','ARROWLEFT'):
                self.gameover_selection = max(0, self.gameover_selection - 1)
            elif cmd in ('DOWN','S','ARROWDOWN','RIGHT','D','ARROWRIGHT'):
                self.gameover_selection = min(1, self.gameover_selection + 1)
            elif cmd in ('ENTER', ''):  # ENTER confirmado
                if self.gameover_selection == 0:
                    # Reiniciar
                    # reinicia o estado mantendo janela ativa
                    self.__init__()   # reinicializa tudo
                    self.state = 'playing'
                else:
                    # Sair
                    pygame.quit()
                    sys.exit(0)
            elif cmd == 'ESC':
                # volta para menu
                self.state = 'menu'
            return

        # se estiver no menu normal
        if cmd in ('UP','W','ARROWUP'):
            self.try_set_direction((0,-1))
        elif cmd in ('DOWN','S','ARROWDOWN'):
            self.try_set_direction((0,1))
        elif cmd in ('LEFT','A','ARROWLEFT'):
            self.try_set_direction((-1,0))
        elif cmd in ('RIGHT','D','ARROWRIGHT'):
            self.try_set_direction((1,0))
        elif cmd in ('PAUSE','P'):
            if self.state == 'playing':
                self.state = 'paused'
            elif self.state == 'paused':
                self.state = 'playing'
        elif cmd in ('RESET','R'):
            self.__init__()
            self.state = 'playing'
        elif cmd == 'ENTER':
            if self.state == 'menu':
                self.state = 'playing'
        elif cmd == 'ESC':
            if self.state in ('playing','paused','gameover'):
                self.state = 'menu'

    def try_set_direction(self, new_dir):
        if (new_dir[0] == -self.direction[0] and new_dir[1] == -self.direction[1]):
            return
        self.next_direction = new_dir

    def run(self):
        stop_event = threading.Event()
        t_udp = threading.Thread(target=udp_listener, args=(stop_event, input_queue, UDP_LISTEN_HOST, UDP_LISTEN_PORT), daemon=True)
        t_udp.start()
        if SERIAL_ENABLED:
            t_ser = threading.Thread(target=serial_listener, args=(stop_event, input_queue, SERIAL_PORT, SERIAL_BAUD), daemon=True)
            t_ser.start()

        last_time = time.time()
        while True:
            now = time.time()
            dt = now - last_time
            last_time = now

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    stop_event.set()
                    pygame.quit()
                    return
                elif event.type == pygame.KEYDOWN:
                    key = event.key
                    # se estiver em gameover, as setas/enter navegam no menu
                    if key in (pygame.K_w, pygame.K_UP):
                        input_queue.put(('local','UP'))
                    elif key in (pygame.K_s, pygame.K_DOWN):
                        input_queue.put(('local','DOWN'))
                    elif key in (pygame.K_a, pygame.K_LEFT):
                        input_queue.put(('local','LEFT'))
                    elif key in (pygame.K_d, pygame.K_RIGHT):
                        input_queue.put(('local','RIGHT'))
                    elif key == pygame.K_RETURN:
                        input_queue.put(('local','ENTER'))
                    elif key == pygame.K_p or key == pygame.K_ESCAPE:
                        # P/ESC pausam ou voltam ao menu (process_input_cmd lida com estado)
                        input_queue.put(('local','PAUSE'))
                    elif key == pygame.K_r:
                        input_queue.put(('local','RESET'))

            try:
                while True:
                    source, cmd = input_queue.get_nowait()
                    self.process_input_cmd(source, cmd)
            except queue.Empty:
                pass

            # atualização de tempo: não incrementa timers enquanto em menu/paused/gameover
            if self.state == 'playing':
                # hunger timer: se ultrapassar limite -> game over
                self.hunger_timer += dt
                if self.hunger_timer >= self.hunger_limit:
                    self.state = 'gameover'
                    self.gameover_selection = 0

                # movimento baseado em move_delay
                self.move_timer += dt
                if self.move_timer >= self.move_delay:
                    self.direction = self.next_direction
                    self.step()
                    self.move_timer = 0.0

            # desenha tela (inclui overlays para pause/gameover/menu)
            self.draw()
            self.clock.tick(60)


if __name__ == '__main__':
    game = SnakeGame()
    game.run()
