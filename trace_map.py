#!/usr/bin/env python3
"""
TraceToServer — real-time network traffic world map.
Dependencies: pip3 install psutil requests
Run:          sudo python3 trace_map.py
"""
from __future__ import annotations

import base64, ipaddress, json, os, sys, signal
import threading, time, zlib
from collections import OrderedDict
from datetime import datetime

try:
    import psutil
except ImportError:
    sys.exit("Missing: pip3 install psutil")
try:
    import requests
except ImportError:
    sys.exit("Missing: pip3 install requests")


# ── Pre-baked world map (Natural Earth 110m, 120×55, zlib+base64) ─────────────
_MAP_DATA = "eNrlmFuOwzAIRf+9iiux/z1OO20aP3hcbKcZafhK5MQHbDAY4B4p+JNgseUi8GNi8aVV7XgctE6BJRZr+vNNV9EFGxhmoX9HDFV7sP1pB7K458zUWh1S2A9rQs2WSSk0t9u/JeoT7P//GfzsYMbzvXlL63GmV4z+JJLbVEGj/AFOHxlzdvZgbkasop8/peJ4IxhpMFaxnW9yYOtcxdQq82d1NnMxW1WIOWMu0lwjLRIJIWmrcPlYC7yVhXbysXo8KNmdCPYk2IoXJGP41LrSJFVzWRmcOGS69JIEnzMoP4aFWJ171LWOyltjnwInaiyXKTCCgscCS7viMwW92EYjziIwwjgHDlKFWnRao0mw595UuM+DJQOGdqzsAYMp8uvjgAeDLQhg35Tan+V1k8CSe1FXSBnA77p6NqKGXQz1PvPRVjC3U6/vUmDPd3gwsAWMqEGwAewMJn1TOPBi16PNkcczD17u81QGPx5o8I4WU31jLF/kNnzSYi2jBnZt6OzJdpsT4fRfeplKKHwXTGGtbpyeYqbjWFZkBF/Z81HB1EUz3dnyJiu0AVuQFdi51V4qRW6S28A/00Rc3Q=="
MAP_W, MAP_H = 120, 55

def _decode_map() -> list[list[str]]:
    raw = zlib.decompress(base64.b64decode(_MAP_DATA)).decode()
    return [list(line.ljust(MAP_W)) for line in raw.split('\n')]

_BASE_MAP = _decode_map()


# ── ANSI helpers ──────────────────────────────────────────────────────────────

ESC = "\033"

def _goto(x: int, y: int) -> str:
    return f"{ESC}[{y};{x}H"

def _fg(r: int, g: int, b: int) -> str:
    return f"{ESC}[38;2;{r};{g};{b}m"

def _bg(r: int, g: int, b: int) -> str:
    return f"{ESC}[48;2;{r};{g};{b}m"

RESET   = f"{ESC}[0m"
BOLD    = f"{ESC}[1m"
DIM     = f"{ESC}[2m"
CLEAR   = f"{ESC}[2J"
HIDE    = f"{ESC}[?25l"   # hide cursor
SHOW    = f"{ESC}[?25h"   # show cursor

# Colours
C_OCEAN      = _bg(5, 15, 35)
C_LAND       = _fg(60, 180, 60)   + _bg(5, 15, 35)
C_LINE       = _fg(0, 220, 255)   + _bg(5, 15, 35)
C_OWN        = _fg(255, 220, 0)   + _bg(5, 15, 35)
C_REMOTE     = _fg(255, 80, 80)   + _bg(5, 15, 35)
C_HEADER_BG  = _bg(10, 30, 60)
C_HEADER_TXT = _fg(0, 200, 255)
C_FOOTER_BG  = _bg(10, 25, 50)
C_DIM        = _fg(100, 120, 140) + _bg(10, 25, 50)
C_YELLOW     = _fg(255, 200, 60)  + _bg(10, 25, 50)
C_GREEN      = _fg(80, 220, 120)  + _bg(10, 25, 50)
C_WHITE      = _fg(220, 230, 240) + _bg(10, 25, 50)


# ── Terminal size ─────────────────────────────────────────────────────────────

def _term_size() -> tuple[int, int]:
    try:
        sz = os.get_terminal_size()
        return sz.columns, sz.lines
    except Exception:
        return 80, 24


# ── Coordinate helpers ────────────────────────────────────────────────────────

def _ll_to_map(lat: float, lon: float) -> tuple[int, int]:
    """lat/lon → column, row on the 120×55 map grid."""
    x = int((lon + 180) / 360 * (MAP_W - 1) + .5)
    y = int((90 - lat)  / 180 * (MAP_H - 1) + .5)
    return max(0, min(MAP_W-1, x)), max(0, min(MAP_H-1, y))


def _bresenham(x0, y0, x1, y1):
    dx, dy = abs(x1-x0), abs(y1-y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    e = dx - dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * e
        if e2 > -dy: e -= dy; x0 += sx
        if e2 <  dx: e += dx; y0 += sy


# ── IP helpers ────────────────────────────────────────────────────────────────

_PRIVATE = [ipaddress.ip_network(n) for n in (
    '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
    '127.0.0.0/8', '169.254.0.0/16', '::1/128', 'fc00::/7', 'fe80::/10',
)]

def is_private(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
        return any(a in n for n in _PRIVATE)
    except ValueError:
        return True


# ── Geo cache ─────────────────────────────────────────────────────────────────

class GeoCache:
    def __init__(self):
        self._lock    = threading.Lock()
        self._cache: OrderedDict = OrderedDict()
        self._queue:  list = []
        self._pending: set = set()

    def get(self, ip: str) -> tuple | None:
        with self._lock:
            if ip in self._cache:
                self._cache.move_to_end(ip)
                return self._cache[ip]
            if ip not in self._pending and not is_private(ip):
                self._queue.append(ip)
                self._pending.add(ip)
        return None

    def run(self):
        while True:
            time.sleep(1.5)
            with self._lock:
                batch, self._queue = self._queue[:100], self._queue[100:]
            if not batch:
                continue
            try:
                r = requests.post(
                    'http://ip-api.com/batch',
                    json=[{'query': ip,
                           'fields': 'query,lat,lon,city,country,status'}
                          for ip in batch],
                    timeout=5,
                )
                if r.ok:
                    for item in r.json():
                        if item.get('status') == 'success':
                            with self._lock:
                                self._pending.discard(item['query'])
                                self._cache[item['query']] = (
                                    item['lat'], item['lon'],
                                    item.get('city', ''),
                                    item.get('country', ''),
                                )
                                if len(self._cache) > 512:
                                    self._cache.popitem(last=False)
            except Exception:
                pass


# ── Connection monitor ────────────────────────────────────────────────────────

class ConnMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        self.conns: list = []

    def run(self):
        while True:
            try:
                raw = psutil.net_connections(kind='inet')
            except Exception:
                time.sleep(2)
                continue
            seen = []
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
                seen.append({'rip': rip, 'proc': proc})
            with self._lock:
                self.conns = seen
            time.sleep(1)

    def snapshot(self) -> list:
        with self._lock:
            return list(self.conns)


# ── Own location ──────────────────────────────────────────────────────────────

_OWN_GEO: tuple | None = None

def _fetch_own_geo():
    global _OWN_GEO
    try:
        d = requests.get('http://ip-api.com/json/', timeout=5).json()
        if d.get('status') == 'success':
            _OWN_GEO = (d['lat'], d['lon'],
                        d.get('city', ''), d.get('country', ''))
            return
    except Exception:
        pass
    _OWN_GEO = (37.77, -122.42, 'Unknown', 'US')


# ── Renderer ──────────────────────────────────────────────────────────────────

class Renderer:
    """
    Draws directly to the terminal using ANSI escape codes.
    No curses, no rich — works in any VT100-compatible terminal.
    """

    def __init__(self, geo: GeoCache, monitor: ConnMonitor):
        self.geo     = geo
        self.monitor = monitor
        self._running = True
        self._tw = self._th = 0

        signal.signal(signal.SIGWINCH, self._on_resize)

    def _on_resize(self, *_):
        self._tw, self._th = _term_size()

    # ── Drawing primitives ───────────────────────────────────────

    def _write(self, s: str):
        sys.stdout.write(s)

    def _flush(self):
        sys.stdout.flush()

    def _put(self, x: int, y: int, ch: str, color: str = ""):
        """Place a character at 1-based terminal position (x, y)."""
        self._write(_goto(x, y) + color + ch + RESET)

    def _hline(self, y: int, color: str, width: int):
        self._write(_goto(1, y) + color + ' ' * width + RESET)

    # ── Map ──────────────────────────────────────────────────────

    def _draw_base_map(self, ox: int, oy: int, scale_x: float, scale_y: float,
                       overlay: dict[tuple[int,int], tuple[str, str]]):
        """
        Render the world map scaled to fit the available area.
        overlay: {(map_x, map_y): (char, color_code)}
        """
        buf = []
        last_y = -1

        for my in range(MAP_H):
            ty = int(my * scale_y) + oy
            if ty == last_y:
                continue
            last_y = ty
            if ty < 1 or ty >= self._th:
                continue

            buf.append(_goto(ox, ty))
            last_color = None

            for mx in range(MAP_W):
                tx = int(mx * scale_x) + ox
                if tx < ox or tx >= ox + int(MAP_W * scale_x):
                    continue

                key = (mx, my)
                if key in overlay:
                    ch, col = overlay[key]
                    if col != last_color:
                        buf.append(col)
                        last_color = col
                    buf.append(ch)
                else:
                    cell = _BASE_MAP[my][mx]
                    col = C_LAND if cell == '#' else C_OCEAN
                    if col != last_color:
                        buf.append(col)
                        last_color = col
                    buf.append(cell if cell == '#' else ' ')

            buf.append(RESET)

        self._write(''.join(buf))

    def _draw_connections(self, ox, oy, scale_x, scale_y) -> list:
        """
        Build overlay dict with connection lines + markers.
        Returns list of (ip, city, proc) for the footer table.
        """
        overlay: dict[tuple[int,int], tuple[str,str]] = {}
        labels = []

        if _OWN_GEO is None:
            return overlay, labels

        olat, olon = _OWN_GEO[0], _OWN_GEO[1]
        omx, omy   = _ll_to_map(olat, olon)

        conns = self.monitor.snapshot()
        for c in conns[:60]:
            geo = self.geo.get(c['rip'])
            if not geo:
                continue
            rlat, rlon, rcity, rcountry = geo
            rmx, rmy = _ll_to_map(rlat, rlon)

            for px, py in _bresenham(omx, omy, rmx, rmy):
                if (px, py) not in overlay:
                    overlay[(px, py)] = ('*', C_LINE)

            overlay[(rmx, rmy)] = ('+', C_REMOTE + BOLD)
            loc = rcity or rcountry or c['rip']
            labels.append((c['rip'], loc, c['proc'] or '?'))

        overlay[(omx, omy)] = ('@', C_OWN + BOLD)
        return overlay, labels

    # ── Header / footer ──────────────────────────────────────────

    def _draw_header(self, width: int, n_conn: int, n_geo: int):
        ts = datetime.now().strftime('%H:%M:%S')
        self._hline(1, C_HEADER_BG, width)
        title  = f" TraceToServer  {ts} "
        stats  = f" conn:{n_conn}  geo:{n_geo} "
        hint   = " Ctrl-C to quit "
        middle = title.center(width - len(stats) - len(hint))
        line   = (C_HEADER_TXT + BOLD + title + RESET +
                  C_HEADER_BG  + middle.replace(title, '') +
                  C_DIM + stats + RESET +
                  C_DIM + hint  + RESET)
        self._write(_goto(1, 1) + C_HEADER_BG + ' ' * width + RESET)
        self._write(_goto(1, 1) + C_HEADER_TXT + BOLD +
                    f" TraceToServer " + RESET +
                    C_HEADER_BG + C_DIM +
                    f" {ts}  conn:{n_conn}  geo:{n_geo}  Ctrl-C to quit" +
                    RESET)

    def _draw_footer(self, width: int, height: int, labels: list):
        footer_y = height - 5
        # Separator
        self._write(_goto(1, footer_y) +
                    C_FOOTER_BG + C_DIM +
                    '─' * width + RESET)

        # Legend
        self._write(_goto(1, footer_y + 1) +
                    C_FOOTER_BG + C_OWN + BOLD + '@' + RESET +
                    C_FOOTER_BG + C_WHITE + ' you   ' +
                    C_REMOTE + BOLD + '+' + RESET +
                    C_FOOTER_BG + C_WHITE + ' server   ' +
                    C_LINE + BOLD + '*' + RESET +
                    C_FOOTER_BG + C_WHITE + ' connection' + RESET)

        # Connection rows
        if not labels:
            self._write(_goto(1, footer_y + 2) +
                        C_FOOTER_BG + C_DIM +
                        ' (no geolocated connections yet — '
                        'open a browser or wait a moment)' +
                        RESET)
            return

        cols = max(1, width // 3)
        for i, (ip, loc, proc) in enumerate(labels[:8]):
            row_y = footer_y + 2 + (i // 3)
            row_x = (i %  3) * cols + 1
            if row_y >= height:
                break
            entry = f"{ip} -> {loc} [{proc}]"
            self._write(_goto(row_x, row_y) +
                        C_FOOTER_BG +
                        C_YELLOW + ip + RESET +
                        C_FOOTER_BG + C_DIM + '->' + RESET +
                        C_FOOTER_BG + C_GREEN + loc[:18] + RESET +
                        C_FOOTER_BG + C_DIM + f'[{proc[:8]}]' + RESET)

    # ── Main loop ─────────────────────────────────────────────────

    def run(self):
        self._tw, self._th = _term_size()

        sys.stdout.write(HIDE + CLEAR)
        sys.stdout.flush()

        try:
            while self._running:
                tw, th = _term_size()
                if tw != self._tw or th != self._th:
                    self._tw, self._th = tw, th
                    sys.stdout.write(CLEAR)

                # Map area: between header (row 1) and footer (last 6 rows)
                map_area_h = max(5, th - 7)
                map_area_w = tw

                scale_x = map_area_w / MAP_W
                scale_y = map_area_h / MAP_H
                # Keep aspect ratio: use smaller scale
                scale = min(scale_x, scale_y)
                rendered_w = int(MAP_W * scale)
                rendered_h = int(MAP_H * scale)
                ox = (tw - rendered_w) // 2 + 1
                oy = 2   # below header

                overlay, labels = self._draw_connections(ox, oy, scale, scale)
                self._draw_base_map(ox, oy, scale, scale, overlay)
                self._draw_header(tw, len(self.monitor.snapshot()), len(labels))
                self._draw_footer(tw, th, labels)

                self._flush()
                time.sleep(0.5)

        except KeyboardInterrupt:
            pass
        finally:
            sys.stdout.write(SHOW + RESET + '\n')
            sys.stdout.write(_goto(1, self._th))
            sys.stdout.flush()
            print("TraceToServer closed.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    geo     = GeoCache()
    monitor = ConnMonitor()

    for fn in (geo.run, monitor.run, _fetch_own_geo):
        threading.Thread(target=fn, daemon=True).start()

    renderer = Renderer(geo, monitor)
    renderer.run()


if __name__ == '__main__':
    main()
