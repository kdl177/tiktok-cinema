#!/usr/bin/env python3
"""
SIMBAI — Descargador automático de clips para TikTok
Descarga segmentos específicos de YouTube para el pipeline de reseñas.

Uso:
  python tiktok_downloader.py --todos          (descarga todos los pendientes con youtube_url)
  python tiktok_downloader.py --video-id 1     (descarga para un video específico)
  python tiktok_downloader.py --url URL --inicio 60 --fin 120 --salida clip.mp4
"""

import sys, os, json, argparse, subprocess, time
import psycopg2
from pathlib import Path

import config
from datetime import datetime

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DB_CONN = config.DB_CONN
OUT_DIR  = config.PELICULAS_DIR
_FFMPEG_SRC = r"C:\Users\hidra\AppData\Roaming\Python\Python314\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
_FFMPEG_DIR = r"C:\SIMBAI\bin"
FFMPEG_PATH = os.path.join(_FFMPEG_DIR, "ffmpeg.exe")

# Asegurar que ffmpeg.exe este disponible con el nombre correcto
if not os.path.exists(FFMPEG_PATH):
    import shutil
    os.makedirs(_FFMPEG_DIR, exist_ok=True)
    shutil.copy2(_FFMPEG_SRC, FFMPEG_PATH)
os.environ["PATH"] = _FFMPEG_DIR + os.pathsep + os.environ.get("PATH", "")

import yt_dlp


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def db():
    return psycopg2.connect(DB_CONN)


def descargar_clip(url: str, t_inicio: float, t_fin: float, salida: Path) -> bool:
    """
    Descarga el video completo y corta el segmento con ffmpeg.
    """
    salida.parent.mkdir(parents=True, exist_ok=True)
    dur = t_fin - t_inicio
    tmp = salida.with_name(salida.stem + "_tmp.mp4")

    log(f"Descargando: {url}")
    log(f"  Segmento: {t_inicio:.0f}s → {t_fin:.0f}s ({dur:.0f}s)")

    ydl_opts = {
        "format":   "worst[ext=mp4]/worst",
        "outtmpl":  str(tmp),
        "quiet":    True,
        "no_warnings": True,
        "ffmpeg_location": FFMPEG_PATH,
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if not tmp.exists():
            # buscar cualquier mp4 temporal generado
            tmps = list(salida.parent.glob(f"{salida.stem}_tmp*.mp4"))
            if tmps:
                tmps[0].rename(tmp)

        if not tmp.exists():
            log("  ⚠ Video temporal no encontrado post-descarga")
            return False

        log(f"  Cortando segmento con ffmpeg...")
        cmd = [
            FFMPEG_PATH, "-y",
            "-ss", str(t_inicio),
            "-i", str(tmp),
            "-t", str(dur),
            "-c", "copy",
            str(salida)
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=60)
        tmp.unlink(missing_ok=True)

        if salida.exists() and salida.stat().st_size > 10000:
            log(f"  ✅ Descargado: {salida.name} ({salida.stat().st_size/1024/1024:.1f} MB)")
            return True

        log("  ⚠ Archivo final no generado o muy pequeño")
        return False

    except Exception as e:
        log(f"  ❌ Error: {e}")
        return False


def descargar_pelicula_completa(url: str, titulo: str) -> Path | None:
    """Descarga la película completa (para clips múltiples del mismo archivo)"""
    nombre = titulo.lower().replace(" ", "").replace("ñ","n").replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u")[:20]
    salida = OUT_DIR / f"{nombre}.mp4"

    if salida.exists():
        log(f"  Ya existe: {salida.name}")
        return salida

    log(f"Descargando película completa: {titulo}")
    ydl_opts = {
        "format":    "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl":   str(salida.with_suffix("")) + ".%(ext)s",
        "quiet":     False,
        "progress":  True,
        "merge_output_format": "mp4",
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        if salida.exists():
            log(f"  ✅ {salida.name} ({salida.stat().st_size/1024/1024:.0f} MB)")
            return salida
        # Buscar el archivo si se guardó con extensión diferente
        for f in OUT_DIR.glob(f"{nombre}*"):
            if f.suffix in (".mp4", ".mkv", ".webm"):
                f.rename(salida)
                return salida
    except Exception as e:
        log(f"  ❌ {e}")
    return None


def procesar_pendientes_db():
    """Descarga todos los clips que tienen youtube_url pero no tienen archivo_crudo válido"""
    conn = db()
    cur  = conn.cursor()

    # Clips con URL de video individual
    cur.execute("""
        SELECT v.id, v.youtube_url, v.yt_inicio, v.yt_fin, v.titulo_post,
               p.titulo, p.youtube_url AS peli_url, p.archivo AS peli_archivo
        FROM tt_videos v
        JOIN tt_peliculas p ON p.id = v.pelicula_id
        WHERE v.estado = 'pendiente'
          AND (v.archivo_crudo IS NULL OR v.archivo_crudo = '' OR
               NOT (v.archivo_crudo LIKE '%.mp4' AND pg_catalog.length(v.archivo_crudo) > 5))
          AND (v.youtube_url IS NOT NULL OR p.youtube_url IS NOT NULL)
        ORDER BY v.id
    """)
    pendientes = cur.fetchall()
    cur.close(); conn.close()

    if not pendientes:
        log("Sin clips con URL para descargar")
        return 0

    log(f"{len(pendientes)} clip(s) para descargar...")
    descargados = 0

    # Agrupar por pelicula para descargar el archivo una sola vez
    peliculas_descargadas = {}

    for vid_id, yt_url, yt_ini, yt_fin, titulo_post, peli_titulo, peli_url, peli_archivo in pendientes:
        log(f"\n--- [{vid_id}] {titulo_post[:50]} ---")

        url_usar = yt_url or peli_url
        ini_usar = float(yt_ini) if yt_ini is not None else None
        fin_usar = float(yt_fin) if yt_fin is not None else None

        # Si hay URL de pelicula completa y tiempos definidos
        # Primero checar si la pelicula ya fue descargada (o tiene archivo)
        archivo_peli = None
        if peli_archivo and Path(peli_archivo).exists():
            archivo_peli = Path(peli_archivo)
        elif peli_titulo in peliculas_descargadas:
            archivo_peli = peliculas_descargadas[peli_titulo]
        elif peli_url and not yt_url:
            # Descargar pelicula completa una vez
            archivo_peli = descargar_pelicula_completa(peli_url, peli_titulo)
            if archivo_peli:
                peliculas_descargadas[peli_titulo] = archivo_peli
                # Actualizar ruta en DB
                conn = db()
                cur  = conn.cursor()
                cur.execute("UPDATE tt_peliculas SET archivo=%s, descargada=true WHERE titulo=%s",
                            (str(archivo_peli), peli_titulo))
                conn.commit(); cur.close(); conn.close()

        if archivo_peli:
            # El clip ya tiene su fuente — solo actualizar archivo_crudo en tt_videos
            conn = db()
            cur  = conn.cursor()
            cur.execute("UPDATE tt_videos SET archivo_crudo=%s, actualizado_en=NOW() WHERE id=%s",
                        (str(archivo_peli), vid_id))
            conn.commit(); cur.close(); conn.close()
            log(f"  ✅ [{vid_id}] Usando archivo existente: {archivo_peli.name}")
            descargados += 1
            continue

        # Descargar clip específico directamente
        if yt_url and ini_usar is not None and fin_usar is not None:
            nombre_clip = f"clip_{vid_id}_{peli_titulo[:15].replace(' ','_')}.mp4"
            salida = OUT_DIR / nombre_clip
            exito  = descargar_clip(yt_url, ini_usar, fin_usar, salida)
            if exito:
                # Actualizar DB: el clip descargado ES el archivo_crudo y también el editado
                conn = db()
                cur  = conn.cursor()
                cur.execute("""
                    UPDATE tt_videos SET archivo_crudo=%s, t_inicio=0,
                    t_fin=%s, actualizado_en=NOW() WHERE id=%s
                """, (str(salida), float(fin_usar - ini_usar), vid_id))
                conn.commit(); cur.close(); conn.close()
                descargados += 1
        else:
            log(f"  ⚠ Sin URL o tiempos suficientes para [{vid_id}]")

        time.sleep(2)

    log(f"\n→ {descargados}/{len(pendientes)} clips listos para edición")
    return descargados


def main():
    parser = argparse.ArgumentParser(description="SIMBAI TikTok Downloader")
    parser.add_argument("--todos",    action="store_true", help="Descargar todos los pendientes con URL")
    parser.add_argument("--video-id", type=int,  help="Descargar para video específico de DB")
    parser.add_argument("--url",      type=str,  help="URL directa de YouTube")
    parser.add_argument("--inicio",   type=float, default=0)
    parser.add_argument("--fin",      type=float, default=60)
    parser.add_argument("--salida",   type=str,  help="Ruta de salida del clip")
    args = parser.parse_args()

    if args.todos or args.video_id:
        procesar_pendientes_db()
    elif args.url:
        salida = Path(args.salida) if args.salida else OUT_DIR / f"clip_{int(args.inicio)}.mp4"
        descargar_clip(args.url, args.inicio, args.fin, salida)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
