#!/usr/bin/env python3
"""
SIMBAI — Agente de Cine TikTok
Busca escenas iconicas de peliculas en YouTube y las agrega al pipeline.
Los clips salen LIMPIOS (sin texto), igual que futbol.

Uso:
  python cine_agente.py --max 8
"""
import sys, os, time, argparse, random
import psycopg2
import yt_dlp
from pathlib import Path

import config
from datetime import datetime

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DB_CONN = config.DB_CONN
OUT_DIR  = config.GUIONES_DIR

QUERIES = [
    "best movie scenes",
    "iconic movie scene",
    "escena de pelicula legendaria",
    "greatest movie moments",
    "best film scenes ever",
    "escena epica pelicula",
    "unforgettable movie scene",
    "mejores escenas del cine",
    "famous movie scene",
    "cine escenas iconicas",
]

HOOKS = [
    "Una de las mejores escenas del cine 🎬",
    "Esta escena es puro cine 🍿",
    "El cine en su maxima expresion 🎥",
    "Nunca pasa de moda 🎞️",
    "Cine del bueno 🎬",
    "Esta escena lo dice todo ✨",
    "Obras maestras del cine 🏆",
    "Para verla mil veces 👀",
    "Cine que emociona 🎭",
    "Momentos que quedan para siempre 🎬",
]

HASHTAGS = "#cine #pelicula #movie #film #escena #cinema #fyp #foryou #peliculas #moviescene"

DUR_MIN, DUR_MAX = 20, 600
CLIP_DUR = 45


def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}")


def db():
    return psycopg2.connect(DB_CONN)


def url_ya_existe(url):
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT id FROM tt_videos WHERE youtube_url = %s LIMIT 1", (url,))
    e = cur.fetchone() is not None
    cur.close(); conn.close()
    return e


def pelicula_id():
    conn = db(); cur = conn.cursor()
    cur.execute("SELECT id FROM tt_peliculas WHERE titulo = 'Cine Escenas'")
    row = cur.fetchone()
    if row:
        pid = row[0]
    else:
        cur.execute("INSERT INTO tt_peliculas (titulo, año, genero) VALUES ('Cine Escenas', 2026, 'drama') RETURNING id")
        pid = cur.fetchone()[0]; conn.commit()
    cur.close(); conn.close()
    return pid


def elegir_segmento(dur):
    if dur <= 60:
        ini = max(0, dur * 0.05)
    elif dur <= 180:
        ini = dur * 0.1
    else:
        ini = 5.0
    return float(ini), float(min(dur, ini + CLIP_DUR))


def registrar(pid, titulo_yt, url, ini, fin):
    hook = random.choice(HOOKS)
    caption = (f"{hook}\n\n🎬 {titulo_yt[:80]}\n\n"
               f"Que pelicula es? Comenta 👇\n\n{HASHTAGS}")[:2200]
    conn = db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO tt_videos
          (pelicula_id, titulo_post, hook_texto, analisis_texto, caption, hashtags,
           youtube_url, yt_inicio, yt_fin, t_inicio, t_fin, duracion_s, estado)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pendiente')
        RETURNING id
    """, (pid, hook[:100], hook, "Escena de cine", caption, HASHTAGS,
          url, ini, fin, ini, fin, int(fin - ini)))
    vid = cur.fetchone()[0]
    cur.execute("INSERT INTO tt_log (video_id, accion, detalle) VALUES (%s,'clip_registrado',%s)",
                (vid, f"Cine: {titulo_yt[:100]} — {ini:.0f}s-{fin:.0f}s"))
    conn.commit(); cur.close(); conn.close()
    return vid


def buscar(query, maxr=5):
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    res = []
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{maxr}:{query}", download=False)
            for e in info.get("entries", []):
                if not e:
                    continue
                dur = e.get("duration") or 0
                url = e.get("webpage_url") or e.get("url", "")
                tit = e.get("title", "")
                if not url or not tit or dur < DUR_MIN or dur > DUR_MAX:
                    continue
                tl = tit.lower()
                if not any(w in tl for w in ["scene", "movie", "film", "pelicula", "cine", "escena"]):
                    continue
                res.append({"url": url, "titulo": tit, "dur": dur})
    except Exception as ex:
        log(f"  Error '{query}': {str(ex)[:100]}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=8)
    ap.add_argument("--query", default=None)
    args = ap.parse_args()

    log("=" * 55); log("SIMBAI Cine Agente"); log("=" * 55)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pid = pelicula_id()
    queries = [args.query] if args.query else random.sample(QUERIES, min(5, len(QUERIES)))
    total, vistos = 0, set()

    for q in queries:
        if total >= args.max:
            break
        log(f"\nBuscando: '{q}'")
        for c in buscar(q, 5):
            if total >= args.max:
                break
            if c["url"] in vistos or url_ya_existe(c["url"]):
                continue
            vistos.add(c["url"])
            ini, fin = elegir_segmento(c["dur"])
            vid = registrar(pid, c["titulo"], c["url"], ini, fin)
            log(f"  ✅ [{vid}] {c['titulo'][:55]}")
            total += 1
            time.sleep(0.5)
        time.sleep(1)

    log(f"\nTotal cine agregados: {total}")


if __name__ == "__main__":
    main()
