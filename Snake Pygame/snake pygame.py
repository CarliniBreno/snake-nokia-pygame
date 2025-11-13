import pygame
import random
import threading
import socket
import queue
import time
import sys
import os

try:
    import serial
    SERIAL_AVAILABLE = True
except Exception:
    serial = None
    SERIAL_AVAILABLE = False

# --- CONFIG 
UDP_LISTEN_HOST = '0.0.0.0'
UDP_LISTEN_PORT = 5005
SERIAL_ENABLED = True
SERIAL_PORT = 'COM5'
SERIAL_BAUD = 115200
GRID_W = 56 # Era 64, agora 30
GRID_H = 24 # Era 32, agora 20
TILE = 16

HUD_TILES = 3

SCREEN_W = 64 * TILE
SCREEN_H = HUD_TILES * TILE + 32 * TILE
SPEED = 8.0
MIN_SPEED = 4.0
MAX_SPEED = 25.0

DISPLAY_GREEN = (110, 236, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

FOOD_COLORS = {
    'red': (200, 20, 20),   # vermelha
    'blue':   (20, 60, 200),   # azul
    'purple': (150, 40, 180),  # roxa
    'orange': (230, 120, 20)   # laranja
}
FOOD_TYPES = list(FOOD_COLORS.keys())

HUNGER_LIMIT = 20.0

BEST_SCORE_FILE = 'best_score.txt'
PIXEL_FONT_FILENAME = 'Iceberg-Regular.ttf'

MIN_SEGMENTS = 3

OBSTACLES_AFTER_EATEN = 10

ORANGE_ALLOWED_WAVE = 3

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

# --- utilities
def load_best_score():
    try:
        if os.path.exists(BEST_SCORE_FILE):
            with open(BEST_SCORE_FILE, 'r') as f:
                return int(f.read().strip())
    except Exception:
        pass
    return 0

def save_best_score(val):
    try:
        with open(BEST_SCORE_FILE, 'w') as f:
            f.write(str(int(val)))
    except Exception:
        pass

# --- o jogo
class SnakeGame:
    def __init__(self):
        pygame.init()
        pygame.font.init()

        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption('Snake - Waves & Obstacles (Nokia Inspired)')
        self.clock = pygame.time.Clock()
        small_size = max(16, int(TILE * 2.0))
        big_size   = max(24, int(TILE * 4.0))

        if os.path.exists(PIXEL_FONT_FILENAME):
            try:
                self.pixel_font = pygame.font.Font(PIXEL_FONT_FILENAME, small_size)
                self.pixel_font_big = pygame.font.Font(PIXEL_FONT_FILENAME, big_size)
            except Exception:
                self.pixel_font = pygame.font.SysFont('dejavusansmono', small_size)
                self.pixel_font_big = pygame.font.SysFont('dejavusansmono', big_size)
        else:
            self.pixel_font = pygame.font.SysFont('dejavusansmono', small_size)
            self.pixel_font_big = pygame.font.SysFont('dejavusansmono', big_size)

        self.font = self.pixel_font
        self.large_font = self.pixel_font_big

        self.best_score = load_best_score()
        self.start_new_game(initial_menu=True)

    def spawn_wave(self, n_foods):
        """
        Cria uma nova leva:
         - limpa comidas (e obstáculos)
         - gera n_foods (1..3)
         - gera 1..2 pedras se self.eaten_count >= OBSTACLES_AFTER_EATEN
        Observação: chama-se spawn_wave tanto no início (onde wave_number já = 1)
        quanto após cada reset — quando for um reset incrementamos wave_number antes de chamar.
        """
        n_foods = max(1, min(3, int(n_foods)))
        self.foods = []
        self.obstacles = []
        added = 0
        tries = 0
        while added < n_foods and tries < 1000:
            tries += 1
            f = self._create_food_candidate()
            if f:
                self.foods.append(f)
                added += 1

        if getattr(self, 'eaten_count', 0) >= OBSTACLES_AFTER_EATEN:
            n_obst = random.randint(1, 2)
            added_o = 0
            tries = 0
            while added_o < n_obst and tries < 1000:
                tries += 1
                obs = self._create_obstacle_candidate()
                if obs:
                    self.obstacles.append(obs)
                    added_o += 1

        if len(self.foods) == 0:
            f = self._create_food_candidate(force=True)
            if f:
                self.foods.append(f)

    def _create_food_candidate(self, force=False):
        """Tenta retornar a dict {'pos':(x,y), 'type':str} sem colidir com snake/obstacles/foods.
        Respeita a regra que a comida laranja só pode aparecer se wave_number >= ORANGE_ALLOWED_WAVE.
        """
        tries = 0
        while tries < 500:
            tries += 1
            x = random.randint(0, GRID_W-1)
            y = random.randint(0, GRID_H-1)
            pos = (x, y)
            if pos in self.snake:
                continue
            if any(pos in obs for obs in getattr(self, 'obstacles', [])):
                continue
            if any(f['pos'] == pos for f in getattr(self, 'foods', [])):
                continue

            allowed_types = FOOD_TYPES.copy()
            if getattr(self, 'wave_number', 1) < ORANGE_ALLOWED_WAVE:

                if 'orange' in allowed_types:
                    allowed_types.remove('orange')
            if not allowed_types:
                allowed_types = FOOD_TYPES.copy()

            ftype = random.choice(allowed_types)
            return {'pos': pos, 'type': ftype}

        if force:
            for x in range(GRID_W):
                for y in range(GRID_H):
                    pos = (x,y)
                    if pos not in self.snake:
                        allowed_types = FOOD_TYPES.copy()
                        if getattr(self, 'wave_number', 1) < ORANGE_ALLOWED_WAVE and 'orange' in allowed_types:
                            allowed_types.remove('orange')
                        ftype = random.choice(allowed_types) if allowed_types else random.choice(FOOD_TYPES)
                        return {'pos': pos, 'type': ftype}
        return None

    def _create_obstacle_candidate(self):
        """
        Cria um triângulo 3x2 (top center + bottom row of 3).
        Retorna set of tiles {(x+1,y),(x,y+1),(x+1,y+1),(x+2,y+1)} ou None.
        """
        tries = 0
        while tries < 500:
            tries += 1
            x = random.randint(0, max(0, GRID_W - 3))
            y = random.randint(0, max(0, GRID_H - 2))
            tiles = {(x+1, y), (x, y+1), (x+1, y+1), (x+2, y+1)}


            if any(t in self.snake for t in tiles):
                continue

            if any(any(f['pos'] == t for f in self.foods) for t in tiles):
                continue

            overlap = False
            for other in getattr(self, 'obstacles', []):
                for t in tiles:
                    if t in other:
                        overlap = True
                        break
                if overlap:
                    break
            if overlap:
                continue
            return tiles
        return None

    # --- ciclo de vida basico do jogo
    def start_new_game(self, initial_menu=False):
        cx, cy = GRID_W//2, GRID_H//2
        self.snake = [(cx, cy), (cx-1, cy), (cx-2, cy)]
        self.direction = (1, 0)
        self.next_direction = self.direction

        self.foods = []
        self.obstacles = []
        self.eaten_count = 0

        self.wave_number = 1


        self.spawn_wave(random.randint(1, 3))

        self.score = 0
        self.speed = float(SPEED)
        self.move_timer = 0.0
        self.move_delay = 1.0 / self.speed
        self.pending_grow = 0
        self.hunger_timer = 0.0
        self.hunger_limit = HUNGER_LIMIT
        self.gameover_selection = 0

        self.state = 'menu' if initial_menu else 'playing'
    

    def get_game_area_offset(self):

        game_area_total_width = GRID_W * TILE
        offset_x = (SCREEN_W - game_area_total_width) // 2

        total_space_below_hud = SCREEN_H - (HUD_TILES * TILE)
        
        game_area_total_height = GRID_H * TILE

        top_padding = (total_space_below_hud - game_area_total_height) // 2
        

        offset_y = (HUD_TILES * TILE) + top_padding
        
        return offset_x, offset_y

    def grid_to_pixel(self, gx, gy):
        offset_x, offset_y = self.get_game_area_offset()
        px = offset_x + gx * TILE
        py = offset_y + gy * TILE
        return px, py

    # --- drawing
    def draw(self):
        # fundo verde
        self.screen.fill(DISPLAY_GREEN)
        score_text = f'{self.score:04d}'
        score_surf = self.font.render(score_text, False, BLACK)
        
        pos_y = (HUD_TILES * TILE - score_surf.get_height()) // 2
        
        # score (esquerda)
        self.screen.blit(score_surf, (10, pos_y))

        # best (centro)
        best_text = f'BEST {self.best_score:04d}'
        best_surf = self.font.render(best_text, False, BLACK)
        best_x = (SCREEN_W - best_surf.get_width()) // 2 # Centralizado
        self.screen.blit(best_surf, (best_x, pos_y))

        # timer (direita)
        time_left = max(0.0, self.hunger_limit - self.hunger_timer)
        timer_text = f'{time_left:0.0f}s'
        timer_surf = self.font.render(timer_text, False, BLACK)
        timer_x = SCREEN_W - timer_surf.get_width() - 10 # 10 pixels da direita
        self.screen.blit(timer_surf, (timer_x, pos_y))
        
        # --- DEMARCACAO DO HUD ---
        pygame.draw.line(self.screen, BLACK, (0, HUD_TILES*TILE - 1), (SCREEN_W, HUD_TILES*TILE - 1), 2)
        
        offset_x, offset_y = self.get_game_area_offset()
        
        # Area jogável
        game_area_px_x = offset_x
        game_area_px_y = offset_y
        game_area_px_w = GRID_W * TILE
        game_area_px_h = GRID_H * TILE

        game_rect_bg = pygame.Rect(game_area_px_x, game_area_px_y, game_area_px_w, game_area_px_h)
        pygame.draw.rect(self.screen, DISPLAY_GREEN, game_rect_bg)
        
        # Borda
        dot_size = max(1, TILE // 8) 
        dot_step = max(1, TILE // 4) 
        

        for x in range(0, game_area_px_w, dot_step):
            pygame.draw.rect(self.screen, BLACK, (game_area_px_x + x, game_area_px_y, dot_size, dot_size)) # Top
            pygame.draw.rect(self.screen, BLACK, (game_area_px_x + x, game_area_px_y + game_area_px_h - dot_size, dot_size, dot_size)) # Bottom
        

        for y in range(0, game_area_px_h, dot_step):
            pygame.draw.rect(self.screen, BLACK, (game_area_px_x, game_area_px_y + y, dot_size, dot_size)) # Left
            pygame.draw.rect(self.screen, BLACK, (game_area_px_x + game_area_px_w - dot_size, game_area_px_y + y, dot_size, dot_size)) # Right
        
        # --- FIM DO HUD e BORDAS ---


        # comidas
        food_size = int(TILE * 0.6)
        for f in self.foods:
            fx, fy = f['pos']
            fpx, fpy = self.grid_to_pixel(fx, fy)
            frect = pygame.Rect(fpx + (TILE - food_size)//2, fpy + (TILE - food_size)//2, food_size, food_size)
            color = FOOD_COLORS.get(f['type'], (200,20,20))
            pygame.draw.rect(self.screen, color, frect, border_radius=2)

        # obstaculos
        for obs in self.obstacles:
            for (ox, oy) in obs:
                opx, opy = self.grid_to_pixel(ox, oy)
                rect = pygame.Rect(opx + (TILE//8), opy + (TILE//8), TILE - TILE//4, TILE - TILE//4)
                pygame.draw.rect(self.screen, BLACK, rect, border_radius=max(1, TILE//6))

        # cobra
        seg_w = int(TILE * 0.7)
        seg_h = int(TILE * 0.7)
        for i, (sx, sy) in enumerate(self.snake):
            px, py = self.grid_to_pixel(sx, sy)
            seg_rect = pygame.Rect(px + (TILE - seg_w)//2, py + (TILE - seg_h)//2, seg_w, seg_h)
            pygame.draw.rect(self.screen, BLACK, seg_rect, border_radius=max(1, seg_w//6))

        # overlays: menu / pause / gameover
        if self.state == 'menu':
            self._draw_center_text('SNAKE - Pressione ENTER para jogar', self.large_font, (SCREEN_W//2, SCREEN_H//2 - 30))
            self._draw_center_text('WASD ou setas para mover. ESP32 via UDP porta %d' % UDP_LISTEN_PORT, self.font, (SCREEN_W//2, SCREEN_H//2 + 20))
        elif self.state == 'paused':
            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0,0,0,160))
            self.screen.blit(overlay, (0,0))
            self._draw_center_text('PAUSE', self.large_font, (SCREEN_W//2, SCREEN_H//2))
            self._draw_center_text('Pressione P ou ESC para voltar', self.font, (SCREEN_W//2, SCREEN_H//2 + 40))
        elif self.state == 'gameover':
            if self.score > self.best_score:
                self.best_score = self.score
                save_best_score(self.best_score)

            overlay = pygame.Surface((SCREEN_W, SCREEN_H), pygame.SRCALPHA)
            overlay.fill((0,0,0,200))
            self.screen.blit(overlay, (0,0))

            self._draw_center_text('GAME OVER', self.large_font, (SCREEN_W//2, SCREEN_H//2 - 90))
            self._draw_center_text(f'Score final: {self.score}', self.font, (SCREEN_W//2, SCREEN_H//2 - 40))

            opts_center_x = SCREEN_W//2
            base_y = SCREEN_H//2 + 10
            spacing = int(TILE * 4)

            icon_size = int(TILE * 2.6)
            icon_rect = pygame.Rect(opts_center_x - spacing - icon_size//2, base_y - icon_size//2, icon_size, icon_size)
            if self.gameover_selection == 0:
                pygame.draw.rect(self.screen, (220,220,220), icon_rect.inflate(14,10), border_radius=4)
            self._draw_restart_icon(self.screen, icon_rect.center, icon_size, color=BLACK)
            lab = self.font.render('REINICIAR', False, BLACK if self.gameover_selection == 0 else (120,120,120))
            self.screen.blit(lab, (icon_rect.centerx - lab.get_width()//2, icon_rect.bottom + 6))

            exit_rect = pygame.Rect(opts_center_x + spacing - icon_size//2, base_y - icon_size//2, icon_size, icon_size)
            if self.gameover_selection == 1:
                pygame.draw.rect(self.screen, (220,220,220), exit_rect.inflate(14,10), border_radius=4)
            self._draw_exit_icon(self.screen, exit_rect.center, icon_size, color=BLACK)
            lab2 = self.font.render('SAIR', False, BLACK if self.gameover_selection == 1 else (120,120,120))
            self.screen.blit(lab2, (exit_rect.centerx - lab2.get_width()//2, exit_rect.bottom + 6))

        pygame.display.flip()

    def _draw_center_text(self, txt, font, pos):
        surf = font.render(txt, False, BLACK)
        r = surf.get_rect(center=pos)
        self.screen.blit(surf, r)

    def _draw_restart_icon(self, surf, center, size, color=BLACK):
        cx, cy = center
        r = max(6, size//2 - 2)
        rect = pygame.Rect(cx - r, cy - r, r*2, r*2)
        width = max(2, size//8)
        try:
            pygame.draw.arc(surf, color, rect, 3.0, 5.5, width)
        except Exception:
            pygame.draw.arc(surf, color, rect, 3.0, 5.5)
        tri = [(cx + r - 1, cy - 1), (cx + r + max(6, size//4), cy - max(3, size//6)), (cx + r + max(4, size//6), cy + max(4, size//6))]
        pygame.draw.polygon(surf, color, tri)

    def _draw_exit_icon(self, surf, center, size, color=BLACK):
        cx, cy = center
        off = max(6, size//3)
        thick = max(2, size//10)
        pygame.draw.line(surf, color, (cx-off, cy-off), (cx+off, cy+off), thick)
        pygame.draw.line(surf, color, (cx-off, cy+off), (cx+off, cy-off), thick)

    # --- game step
    def step(self):
        head = self.snake[0]
        dx, dy = self.direction
        new_head = (head[0] + dx, head[1] + dy)
        new_head = (new_head[0] % GRID_W, new_head[1] % GRID_H)

        if any(new_head in obs for obs in self.obstacles):
            self.state = 'gameover'
            self.gameover_selection = 0
            if self.score > self.best_score:
                self.best_score = self.score
                save_best_score(self.best_score)
            return

        # colisao no corpo
        if new_head in self.snake:
            self.state = 'gameover'
            self.gameover_selection = 0
            if self.score > self.best_score:
                self.best_score = self.score
                save_best_score(self.best_score)
            return


        self.snake.insert(0, new_head)

        eaten_idx = None
        eaten_food = None
        for i, f in enumerate(self.foods):
            if f['pos'] == new_head:
                eaten_idx = i
                eaten_food = f
                break

        if eaten_food:
            ftype = eaten_food['type']
            self.score += 1
            self.eaten_count = getattr(self, 'eaten_count', 0) + 1

            if ftype == 'purple':
                self.speed = min(MAX_SPEED, self.speed + 0.5)
                self.pending_grow += 1
            elif ftype == 'red':
                self.pending_grow += 2
            elif ftype == 'blue':
                self.speed = max(MIN_SPEED, self.speed - 0.5)
                self.pending_grow += 1
            elif ftype == 'orange':
                if len(self.snake) > 0:
                    self.snake.pop()
                if len(self.snake) < MIN_SEGMENTS:
                    self.state = 'gameover'
                    if self.score > self.best_score:
                        self.best_score = self.score
                        save_best_score(self.best_score)
                    if eaten_idx is not None:
                        self.foods.pop(eaten_idx)
                    return

            self.hunger_timer = 0.0

            if eaten_idx is not None:
                self.foods.pop(eaten_idx)


            if len(self.foods) == 0:
                self.wave_number = getattr(self, 'wave_number', 1) + 1
                n_new = random.randint(1, 3)
                self.spawn_wave(n_new)


            self.move_delay = 1.0 / self.speed


        if self.pending_grow > 0:
            self.pending_grow -= 1
        else:
            self.snake.pop()

        if len(self.snake) < MIN_SEGMENTS:
            self.state = 'gameover'
            if self.score > self.best_score:
                self.best_score = self.score
                save_best_score(self.best_score)
            self.gameover_selection = 0
            return

    def process_input_cmd(self, source, cmd):
        map_short = {'U':'UP','D':'DOWN','L':'LEFT','R':'RIGHT','P':'PAUSE','X':'RESET'}
        if len(cmd) == 1 and cmd in map_short:
            cmd = map_short[cmd]

        # gameover menu
        if self.state == 'gameover':
            if cmd in ('LEFT','A','ARROWLEFT'):
                self.gameover_selection = max(0, self.gameover_selection - 1)
            elif cmd in ('RIGHT','D','ARROWRIGHT'):
                self.gameover_selection = min(1, self.gameover_selection + 1)
            elif cmd in ('UP','W','ARROWUP'):
                self.gameover_selection = max(0, self.gameover_selection - 1)
            elif cmd in ('DOWN','S','ARROWDOWN'):
                self.gameover_selection = min(1, self.gameover_selection + 1)
            elif cmd == 'ENTER':
                if self.gameover_selection == 0:
                    self.start_new_game(initial_menu=False)
                else:
                    pygame.quit()
                    sys.exit(0)
            elif cmd == 'ESC':
                self.start_new_game(initial_menu=True)
            return

        # controles
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
            self.start_new_game(initial_menu=False)
        elif cmd == 'ENTER':
            if self.state == 'menu':
                self.state = 'playing'
        elif cmd == 'ESC':
            if self.state in ('playing','paused','gameover'):
                self.start_new_game(initial_menu=True)

    def try_set_direction(self, new_dir):
        # impede 180 graus
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
                    elif key == pygame.K_p:
                        input_queue.put(('local','PAUSE'))
                    elif key == pygame.K_ESCAPE:
                        input_queue.put(('local','PAUSE'))
                    elif key == pygame.K_r:
                        input_queue.put(('local','RESET'))


            try:
                while True:
                    source, cmd = input_queue.get_nowait()
                    self.process_input_cmd(source, cmd)
            except queue.Empty:
                pass


            if self.state == 'playing':
                # relogio de fome
                self.hunger_timer += dt
                if self.hunger_timer >= self.hunger_limit:
                    self.state = 'gameover'
                    self.gameover_selection = 0
                    if self.score > self.best_score:
                        self.best_score = self.score
                        save_best_score(self.best_score)

                # movimentacao
                self.move_timer += dt
                if self.move_timer >= self.move_delay:
                    self.direction = self.next_direction
                    self.step()
                    self.move_delay = 1.0 / self.speed
                    self.move_timer = 0.0


            self.draw()
            self.clock.tick(60)


if __name__ == '__main__':
    game = SnakeGame()
    game.run()