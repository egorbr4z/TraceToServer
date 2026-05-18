#!/usr/bin/env python3
"""
TraceToServer — Real-time network traffic world map
Visualises active TCP/UDP connections as lines on an ASCII world map.
Run with:  python3 trace_map.py
"""

import curses
import threading
import time
import socket
import ipaddress
import math
import json
import sys
import os
from collections import OrderedDict
from datetime import datetime

try:
    import psutil
except ImportError:
    sys.exit("psutil missing — install with:  pip3 install psutil")

try:
    import requests
except ImportError:
    sys.exit("requests missing — install with:  pip3 install requests")


# ──────────────────────────────────────────────────────────────────
# World map geometry
# ──────────────────────────────────────────────────────────────────

MAP_W = 120   # columns
MAP_H = 55    # rows

def latlon_to_xy(lat: float, lon: float) -> tuple[int, int]:
    """Convert (lat, lon) degrees → (col, row) on the character grid."""
    col = int((lon + 180.0) / 360.0 * (MAP_W - 1) + 0.5)
    row = int((90.0 - lat)  / 180.0 * (MAP_H - 1) + 0.5)
    col = max(0, min(MAP_W - 1, col))
    row = max(0, min(MAP_H - 1, row))
    return col, row


def bresenham(x0, y0, x1, y1):
    """Return list of (x, y) integer points along a line."""
    pts = []
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        pts.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0  += sx
        if e2 <  dx:
            err += dx
            y0  += sy
    return pts


# Simplified continent outlines as (lat, lon) polylines
# Source geometry: derived from Natural Earth 110m (public domain)
_OUTLINES = [
    # --- North America ---
    [(70,-140),(65,-168),(58,-137),(53,-130),(48,-125),(42,-124),
     (32,-118),(22,-110),(15,-92),(10,-83),(9,-77),(10,-75),(18,-66),
     (23,-82),(25,-80),(32,-80),(35,-75),(41,-70),(45,-66),(47,-53),
     (52,-56),(60,-63),(63,-68),(60,-78),(60,-85),(64,-83),(68,-78),
     (72,-78),(75,-90),(72,-100),(72,-120),(71,-140),(70,-140)],
    # --- Greenland ---
    [(60,-45),(65,-40),(70,-22),(76,-18),(83,-30),(82,-50),
     (76,-65),(72,-68),(65,-53),(60,-45)],
    # --- South America ---
    [(12,-72),(10,-62),(8,-60),(5,-60),(0,-50),(-5,-35),(-10,-37),
     (-15,-39),(-23,-43),(-30,-51),(-34,-53),(-38,-57),(-42,-64),
     (-50,-69),(-55,-67),(-55,-65),(-52,-70),(-55,-70),(-55,-74),
     (-50,-75),(-42,-73),(-35,-72),(-18,-70),(-5,-80),(0,-80),
     (5,-77),(10,-72),(12,-72)],
    # --- Europe ---
    [(36,-6),(44,-9),(44,-8),(48,-4),(51,2),(54,9),(58,10),(58,18),
     (57,22),(60,22),(65,15),(70,25),(68,28),(60,28),(55,22),
     (52,21),(50,22),(48,22),(48,17),(45,17),(42,20),(40,18),
     (38,13),(38,9),(36,6),(36,-6)],
    # --- Scandinavia ---
    [(57,5),(58,7),(58,10),(65,15),(70,25),(71,28),(70,30),
     (65,25),(63,20),(60,20),(57,10),(57,5)],
    # --- UK / Ireland ---
    [(50,-6),(52,-5),(53,-4),(55,-3),(58,-5),(58,-3),(56,0),
     (53,0),(51,-3),(50,-6)],
    # --- Africa ---
    [(37,10),(37,-6),(14,-17),(5,-10),(4,7),(0,8),(-5,10),(-10,14),
     (-18,13),(-30,17),(-35,20),(-35,26),(-30,31),(-25,33),(-15,37),
     (-10,40),(-5,40),(0,42),(10,44),(12,43),(15,42),(20,40),
     (25,37),(30,33),(37,37),(37,10)],
    # --- Madagascar ---
    [(-13,49),(-15,44),(-20,44),(-25,44),(-26,47),(-24,51),
     (-18,50),(-13,50),(-13,49)],
    # --- Arabian Peninsula ---
    [(30,32),(22,37),(12,45),(15,52),(22,59),(26,57),(30,48),
     (30,43),(26,50),(22,56),(12,43),(22,37),(30,32)],
    # --- India ---
    [(28,77),(22,68),(8,77),(8,80),(12,80),(20,87),(22,89),(28,97),
     (34,76),(28,77)],
    # --- Sri Lanka ---
    [(7,80),(6,81),(9,81),(9,80),(7,80)],
    # --- Southeast Asia / Indochina ---
    [(28,97),(22,100),(13,100),(10,105),(5,103),(1,104),
     (5,116),(10,124),(20,120),(28,120),(28,97)],
    # --- Indonesia (Java/Sumatra rough) ---
    [(5,96),(0,103),(0,108),(-8,115),(-8,112),(-7,107),(0,104),(5,96)],
    # --- China / East Asia ---
    [(50,87),(28,97),(28,120),(38,121),(40,117),(42,121),(38,124),
     (42,131),(50,141),(55,137),(55,120),(50,87)],
    # --- Korean Peninsula ---
    [(38,125),(34,127),(35,129),(38,129),(38,125)],
    # --- Japan ---
    [(31,130),(33,131),(35,137),(37,137),(40,141),(44,144),(45,141),
     (43,140),(40,140),(35,137),(31,131),(31,130)],
    # --- Russia / Siberia ---
    [(70,25),(68,28),(60,28),(55,22),(50,30),(50,60),(50,87),
     (55,120),(55,137),(50,141),(50,145),(55,163),(65,170),(70,165),
     (73,155),(75,150),(75,100),(73,80),(72,68),(72,54),(68,50),
     (65,57),(68,50),(68,32),(70,28),(70,25)],
    # --- Australia ---
    [(-10,142),(-14,130),(-20,114),(-34,114),(-38,140),(-38,149),
     (-44,148),(-44,168),(-35,150),(-25,153),(-20,148),(-14,136),(-10,142)],
    # --- New Zealand ---
    [(-34,172),(-40,175),(-44,171),(-46,168),(-41,172),(-34,172)],
    # --- Antarctica (rough strip) ---
    [(-65,-180),(-65,-120),(-60,-90),(-65,-60),(-62,0),(-65,60),
     (-62,90),(-65,120),(-65,180),(-90,180),(-90,-180),(-65,-180)],
    # --- Iceland ---
    [(63,-25),(65,-24),(66,-20),(64,-13),(63,-15),(63,-25)],
    # --- Cuba ---
    [(20,-75),(20,-84),(22,-84),(23,-82),(23,-75),(20,-75)],
    # --- Hispaniola (Haiti/DR) ---
    [(18,-74),(18,-72),(19,-69),(20,-71),(18,-74)],
]


def _build_base_map() -> list[list[str]]:
    grid = [[' '] * MAP_W for _ in range(MAP_H)]
    for poly in _OUTLINES:
        for i in range(len(poly) - 1):
            x0, y0 = latlon_to_xy(*poly[i])
            x1, y1 = latlon_to_xy(*poly[i + 1])
            for px, py in bresenham(x0, y0, x1, y1):
                grid[py][px] = '.'
    return grid


BASE_MAP = _build_base_map()


# ──────────────────────────────────────────────────────────────────
# IP helpers
# ──────────────────────────────────────────────────────────────────

_PRIVATE_RANGES = [
    ipaddress.ip_network(n) for n in (
        '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
        '127.0.0.0/8', '::1/128', 'fc00::/7', 'fe80::/10',
        '169.254.0.0/16',
    )
]


def is_private(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in _PRIVATE_RANGES)
    except ValueError:
        return True


# ──────────────────────────────────────────────────────────────────
# Geolocation cache + worker
# ──────────────────────────────────────────────────────────────────

class GeoCache:
    """Thread-safe LRU cache for IP→(lat, lon, city, country)."""

    def __init__(self, maxsize=512):
        self._lock  = threading.Lock()
        self._cache: OrderedDict[str, tuple] = OrderedDict()
        self._maxsize = maxsize
        self._queue:  list[str]  = []
        self._pending: set[str]  = set()

    def get(self, ip: str):
        with self._lock:
            if ip in self._cache:
                self._cache.move_to_end(ip)
                return self._cache[ip]
            if ip not in self._pending and not is_private(ip):
                self._queue.append(ip)
                self._pending.add(ip)
        return None

    def _store(self, ip: str, data: tuple):
        with self._lock:
            self._pending.discard(ip)
            self._cache[ip] = data
            self._cache.move_to_end(ip)
            if len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)

    def run_worker(self):
        """Background thread: drains queue, fetches geo in batches."""
        while True:
            time.sleep(1.5)
            with self._lock:
                batch = self._queue[:100]
                self._queue = self._queue[100:]
            if not batch:
                continue
            try:
                resp = requests.post(
                    'http://ip-api.com/batch',
                    json=[{'query': ip, 'fields': 'query,lat,lon,city,country,status'}
                          for ip in batch],
                    timeout=5,
                )
                if resp.status_code == 200:
                    for item in resp.json():
                        if item.get('status') == 'success':
                            self._store(
                                item['query'],
                                (item['lat'], item['lon'],
                                 item.get('city', ''), item.get('country', '')),
                            )
            except Exception:
                pass


GEO = GeoCache()


# ──────────────────────────────────────────────────────────────────
# Connection monitor
# ──────────────────────────────────────────────────────────────────

class ConnMonitor:
    """Polls psutil for active TCP/UDP connections."""

    def __init__(self):
        self._lock  = threading.Lock()
        self.conns: list[dict] = []   # [{rip, rport, lip, lport, pid, proc}, …]

    def run(self):
        while True:
            try:
                raw = psutil.net_connections(kind='inet')
            except Exception:
                time.sleep(2)
                continue

            seen: list[dict] = []
            for c in raw:
                if not c.raddr:
                    continue
                rip = c.raddr.ip
                if is_private(rip):
                    continue
                proc = ''
                try:
                    if c.pid:
                        proc = psutil.Process(c.pid).name()
                except Exception:
                    pass
                seen.append({
                    'rip':   rip,
                    'rport': c.raddr.port,
                    'lip':   c.laddr.ip if c.laddr else '',
                    'lport': c.laddr.port if c.laddr else 0,
                    'pid':   c.pid,
                    'proc':  proc,
                    'status': c.status,
                })
            with self._lock:
                self.conns = seen
            time.sleep(1)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self.conns)


MONITOR = ConnMonitor()


# ──────────────────────────────────────────────────────────────────
# Own location (best-effort)
# ──────────────────────────────────────────────────────────────────

_OWN_GEO: tuple | None = None

def _fetch_own_geo():
    global _OWN_GEO
    try:
        r = requests.get('http://ip-api.com/json/', timeout=5)
        d = r.json()
        if d.get('status') == 'success':
            _OWN_GEO = (d['lat'], d['lon'], d.get('city',''), d.get('country',''))
    except Exception:
        _OWN_GEO = (37.7749, -122.4194, 'Unknown', 'US')  # fallback: SF


# ──────────────────────────────────────────────────────────────────
# Curses UI
# ──────────────────────────────────────────────────────────────────

# Colour pair IDs
C_MAP    = 1   # map dots
C_CONN   = 2   # connection lines
C_OWN    = 3   # own location marker
C_REMOTE = 4   # remote location marker
C_HEADER = 5   # header bar
C_INFO   = 6   # info text
C_TITLE  = 7   # title
C_FADE1  = 8   # fading line colour 1
C_FADE2  = 9   # fading line colour 2


def _init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_MAP,    curses.COLOR_GREEN,   -1)
    curses.init_pair(C_CONN,   curses.COLOR_CYAN,    -1)
    curses.init_pair(C_OWN,    curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_REMOTE, curses.COLOR_RED,     -1)
    curses.init_pair(C_HEADER, curses.COLOR_BLACK,   curses.COLOR_CYAN)
    curses.init_pair(C_INFO,   curses.COLOR_WHITE,   -1)
    curses.init_pair(C_TITLE,  curses.COLOR_YELLOW,  -1)
    curses.init_pair(C_FADE1,  curses.COLOR_BLUE,    -1)
    curses.init_pair(C_FADE2,  curses.COLOR_MAGENTA, -1)


def _safe_addch(win, y, x, ch, attr=0):
    max_y, max_x = win.getmaxyx()
    if 0 <= y < max_y and 0 <= x < max_x - 1:
        try:
            win.addch(y, x, ch, attr)
        except curses.error:
            pass


def _safe_addstr(win, y, x, s, attr=0):
    max_y, max_x = win.getmaxyx()
    if 0 <= y < max_y and 0 <= x < max_x - 1:
        avail = max_x - x - 1
        try:
            win.addstr(y, x, s[:avail], attr)
        except curses.error:
            pass


def _draw_map(win, row_off: int, col_off: int, scale_x: float, scale_y: float):
    """Render the base world map scaled to the available terminal area."""
    attr = curses.color_pair(C_MAP)
    max_y, max_x = win.getmaxyx()
    for ry in range(MAP_H):
        dy = int(ry * scale_y + 0.5) + row_off
        if dy >= max_y - 1:
            break
        for rx in range(MAP_W):
            if BASE_MAP[ry][rx] == '.':
                dx = int(rx * scale_x + 0.5) + col_off
                if 0 <= dx < max_x - 1:
                    _safe_addch(win, dy, dx, '.', attr)


def _draw_line(win, x0, y0, x1, y1, attr):
    """Draw a straight line between two terminal coordinates."""
    for px, py in bresenham(x0, y0, x1, y1):
        _safe_addch(win, py, px, '*', attr)


def _map_coords(lat, lon, row_off, col_off, scale_x, scale_y):
    mx, my = latlon_to_xy(lat, lon)
    tx = int(mx * scale_x + 0.5) + col_off
    ty = int(my * scale_y + 0.5) + row_off
    return tx, ty


def _main(stdscr):
    _init_colors()
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(200)

    frame = 0

    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27):   # q / ESC to quit
            break

        max_y, max_x = stdscr.getmaxyx()
        stdscr.erase()

        # ── Header bar ──────────────────────────────────────────
        ts  = datetime.now().strftime('%H:%M:%S')
        hdr = f" TraceToServer  |  {ts}  |  press Q to quit "
        _safe_addstr(stdscr, 0, 0, hdr.ljust(max_x - 1),
                     curses.color_pair(C_HEADER) | curses.A_BOLD)

        # ── Map area ─────────────────────────────────────────────
        MAP_ROWS = max_y - 8   # reserve bottom rows for connection list
        MAP_COLS = max_x
        if MAP_ROWS < 5 or MAP_COLS < 20:
            _safe_addstr(stdscr, 1, 0, "Terminal too small — resize and retry")
            stdscr.refresh()
            time.sleep(0.5)
            continue

        scale_x = MAP_COLS / MAP_W
        scale_y = MAP_ROWS / MAP_H
        row_off = 1
        col_off = 0

        _draw_map(stdscr, row_off, col_off, scale_x, scale_y)

        # ── Connections ──────────────────────────────────────────
        conns   = MONITOR.snapshot()
        own_geo = _OWN_GEO

        own_tx, own_ty = None, None
        if own_geo:
            own_tx, own_ty = _map_coords(own_geo[0], own_geo[1],
                                          row_off, col_off, scale_x, scale_y)
            _safe_addch(stdscr, own_ty, own_tx, '@',
                        curses.color_pair(C_OWN) | curses.A_BOLD)

        drawn_remote: list[tuple] = []   # (tx, ty, rip, proc)
        active_labels: list[str]  = []

        line_attrs = [
            curses.color_pair(C_CONN)  | curses.A_BOLD,
            curses.color_pair(C_FADE1) | curses.A_BOLD,
            curses.color_pair(C_FADE2),
        ]

        for idx, c in enumerate(conns[:60]):   # cap at 60 for perf
            geo = GEO.get(c['rip'])
            if geo is None:
                continue
            rlat, rlon, rcity, rcountry = geo
            rtx, rty = _map_coords(rlat, rlon, row_off, col_off, scale_x, scale_y)

            # draw line from own location → remote
            if own_tx is not None:
                attr = line_attrs[idx % len(line_attrs)]
                _draw_line(stdscr, own_tx, own_ty, rtx, rty, attr)

            _safe_addch(stdscr, rty, rtx, '+',
                        curses.color_pair(C_REMOTE) | curses.A_BOLD)
            drawn_remote.append((rtx, rty, c['rip'], c['proc']))

            label = f"{c['rip']} → {rcity or rcountry}  [{c['proc'] or 'unknown'}]"
            active_labels.append(label)

        # Re-draw own marker on top of any lines
        if own_tx is not None:
            _safe_addch(stdscr, own_ty, own_tx, '@',
                        curses.color_pair(C_OWN) | curses.A_BOLD)

        # ── Separator ────────────────────────────────────────────
        sep_y = row_off + MAP_ROWS
        _safe_addstr(stdscr, sep_y, 0,
                     '─' * (max_x - 1),
                     curses.color_pair(C_INFO))

        # ── Connection list ───────────────────────────────────────
        legend_y = sep_y + 1
        hdr2 = (f" {'@'} = you   {'+'} = remote server   "
                f"Active connections: {len(conns)}   "
                f"Geolocated: {len(active_labels)}")
        _safe_addstr(stdscr, legend_y, 0, hdr2,
                     curses.color_pair(C_TITLE) | curses.A_BOLD)

        list_y = legend_y + 1
        cols_per_entry = max_x // 2
        row_i, col_i = 0, 0
        for lbl in active_labels[:12]:
            ly = list_y + row_i
            lx = col_i * cols_per_entry
            if ly >= max_y - 1:
                break
            _safe_addstr(stdscr, ly, lx, lbl[:cols_per_entry - 1],
                         curses.color_pair(C_INFO))
            col_i += 1
            if col_i >= 2:
                col_i = 0
                row_i += 1

        if not active_labels:
            _safe_addstr(stdscr, list_y, 2,
                         "Waiting for connections…  (make sure you have internet activity)",
                         curses.color_pair(C_INFO))

        stdscr.refresh()
        frame += 1
        time.sleep(0.2)


def main():
    # Start background threads
    t_geo  = threading.Thread(target=GEO.run_worker,   daemon=True)
    t_conn = threading.Thread(target=MONITOR.run,      daemon=True)
    t_own  = threading.Thread(target=_fetch_own_geo,   daemon=True)
    t_geo.start()
    t_conn.start()
    t_own.start()

    print("Fetching own location…", flush=True)
    time.sleep(1.5)   # give own-geo a head start

    try:
        curses.wrapper(_main)
    except KeyboardInterrupt:
        pass

    print("\nBye!")


if __name__ == '__main__':
    main()
