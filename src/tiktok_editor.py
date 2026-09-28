#!/usr/bin/env python3
"""
SIMBAI — Editor de Video para TikTok (Reseñas de Películas)
Convierte clips crudos en videos 9:16 optimizados con hooks y análisis.

Uso:
  python tiktok_editor.py <input.mp4> --inicio 30 --fin 75 --hook "El detalle que cambia todo" --analisis "Texto de análisis" --output salida.mp4
  python tiktok_editor.py --video-id 1   (lee config desde DB)
"""

import sys, os, json, argparse, textwrap
import psycopg2
from pathlib import Path

import config
from datetime import datetime

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw, ImageFont
import numpy as np

try:
    from moviepy import VideoFileClip, CompositeVideoClip, ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip
    from moviepy import TextClip
    MOVIEPY_OK = True
except ImportError:
    MOVIEPY_OK = False
    print("AVISO: moviepy no disponible, usando ffmpeg directo")

import subprocess

# ── Configuracion ─────────────────────────────────────────────────────────────
DB_CONN = config.DB_CONN
OUT_DIR   = config.EDITADOS_DIR
FFMPEG    = r"C:\SIMBAI\bin\ffmpeg.exe"   # copia local (ver tiktok_downloader.py)

TT_W, TT_H = 1080, 1920       # TikTok 9:16
FPS         = 30
MAX_DURACION = 60              # segundos maximos en TikTok
MIN_DURACION = 10

# Colores y estilos
COLOR_HOOK_BG   = (0, 0, 0, 180)       # negro semi-transparente
COLOR_HOOK_TEXT = (255, 255, 255)       # blanco
COLOR_ANALISIS  = (255, 230, 0)         # amarillo TikTok
COLOR_CTA_BG    = (254, 44, 85)         # rojo TikTok
COLOR_CTA_TEXT  = (255, 255, 255)

FONT_PATH = r"C:\Windows\Fonts\arialbd.ttf"   # Arial Bold Windows


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ── Utilidades de imagen/overlay ─────────────────────────────────────────────
def crear_imagen_overlay(ancho: int, alto: int, rgba=(0,0,0,0)) -> Image.Image:
    return Image.new("RGBA", (ancho, alto), rgba)


def get_font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except:
        return ImageFont.load_default()


def texto_con_sombra(draw: ImageDraw.Draw, pos, texto: str, font,
                     color=(255,255,255), sombra=(0,0,0), offset=3):
    x, y = pos
    draw.text((x+offset, y+offset), texto, font=font, fill=sombra)
    draw.text((x, y), texto, font=font, fill=color)


def wrap_text(texto: str, max_chars: int = 28) -> list[str]:
    return textwrap.wrap(texto, width=max_chars)


# ── Frames de overlay (generados como imagenes PNG y luego compuestos) ───────
def generar_frame_hook(hook_texto: str, w=TT_W, h=TT_H) -> Path:
    """Genera imagen PNG con el texto del hook para los primeros 3 segundos"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Barra superior semi-transparente
    bar_h = int(h * 0.22)
    bar = Image.new("RGBA", (w, bar_h), (0, 0, 0, 190))
    img.paste(bar, (0, 0), bar)

    # Texto del hook
    font_hook = get_font(62)
    font_sub  = get_font(40)

    lineas = wrap_text(hook_texto, 22)
    y = 40
    for linea in lineas:
        bbox = draw.textbbox((0, 0), linea, font=font_hook)
        lw = bbox[2] - bbox[0]
        x = (w - lw) // 2
        texto_con_sombra(draw, (x, y), linea, font_hook,
                         color=(255, 230, 0), sombra=(0, 0, 0))
        y += 75

    # Emoji o decorador abajo del hook
    etiqueta = "🎬 ANÁLISIS CINEMATOGRÁFICO"
    bbox = draw.textbbox((0, 0), etiqueta, font=font_sub)
    ew = bbox[2] - bbox[0]
    draw.text(((w - ew) // 2, y + 10), etiqueta, font=font_sub, fill=(200, 200, 200))

    out = OUT_DIR / "_hook_overlay.png"
    img.save(str(out), "PNG")
    return out


def generar_frame_analisis(analisis_texto: str, w=TT_W, h=TT_H) -> Path:
    """Overlay con texto de análisis para el cuerpo del video"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Barra inferior
    bar_h = int(h * 0.28)
    bar = Image.new("RGBA", (w, bar_h), (0, 0, 0, 200))
    img.paste(bar, (0, h - bar_h), bar)

    font_text = get_font(48)
    lineas = wrap_text(analisis_texto, 24)
    y = h - bar_h + 20
    for linea in lineas[:5]:   # max 5 lineas
        bbox = draw.textbbox((0, 0), linea, font=font_text)
        lw = bbox[2] - bbox[0]
        x = (w - lw) // 2
        texto_con_sombra(draw, (x, y), linea, font_text,
                         color=(255, 255, 255), sombra=(0, 0, 0))
        y += 56

    out = OUT_DIR / "_analisis_overlay.png"
    img.save(str(out), "PNG")
    return out


def generar_frame_cta(w=TT_W, h=TT_H) -> Path:
    """Overlay de Call To Action para los ultimos 3 segundos"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Barra CTA
    cta_h = 180
    bar = Image.new("RGBA", (w, cta_h), (254, 44, 85, 230))
    img.paste(bar, (0, h - cta_h), bar)

    font_cta = get_font(56)
    cta = "❤️ SEGUIME PARA MÁS ANÁLISIS"
    bbox = draw.textbbox((0, 0), cta, font=font_cta)
    cw = bbox[2] - bbox[0]
    draw.text(((w - cw) // 2, h - cta_h + 55), cta, font=font_cta,
              fill=(255, 255, 255))

    out = OUT_DIR / "_cta_overlay.png"
    img.save(str(out), "PNG")
    return out


def obtener_duracion_real(input_path: str) -> float:
    """Usa ffprobe para obtener la duración real del video."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-select_streams", "v", input_path],
            capture_output=True, text=True, timeout=15
        )
        import json as _json
        data = _json.loads(result.stdout)
        streams = data.get("streams", [])
        for s in streams:
            if s.get("codec_type") == "video" and "duration" in s:
                return float(s["duration"])
    except Exception:
        pass
    return None


# ── Pipeline principal con ffmpeg ────────────────────────────────────────────
def editar_con_ffmpeg(
    input_path: str,
    output_path: str,
    t_inicio: float,
    t_fin: float,
    hook_img: Path,
    analisis_img: Path,
    cta_img: Path,
    duracion_total: float
):
    """
    Compone el video final usando ffmpeg directamente:
    1. Recorta el clip al tiempo indicado
    2. Escala y cropea a 9:16 (1080x1920) con blur en barras si es 16:9
    3. Superpone hook (0-3s), analisis (3s-fin-3s), CTA (ultimos 3s)
    4. Exporta optimizado para TikTok
    """
    # Clampar t_fin a la duración real del video para evitar errores de trim
    dur_real = obtener_duracion_real(input_path)
    if dur_real is not None and t_fin > dur_real:
        t_fin = dur_real

    dur = t_fin - t_inicio
    dur_hook     = min(3.0, dur * 0.15)
    dur_cta      = min(3.0, dur * 0.15)
    inicio_cta   = dur - dur_cta
    inicio_anal  = dur_hook

    hook_str = str(hook_img).replace("\\", "/")
    anal_str = str(analisis_img).replace("\\", "/")
    cta_str  = str(cta_img).replace("\\", "/")
    in_str   = str(input_path).replace("\\", "/")
    out_str  = str(output_path).replace("\\", "/")

    # Filtro ffmpeg para 9:16 con blur background
    # force_divisible_by=2 evita dimensiones impares (libx264 yuv420p requiere pares)
    filtro_escala = (
        "[0:v]trim=start={ts}:end={te},setpts=PTS-STARTPTS,"
        "scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        "pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black[base];"
        "[1:v]scale={w}:{h}[hook];"
        "[2:v]scale={w}:{h}[anal];"
        "[3:v]scale={w}:{h}[cta];"
        "[base][hook]overlay=0:0:enable='between(t,0,{dh})'[v1];"
        "[v1][anal]overlay=0:0:enable='between(t,{ia},{ic})'[v2];"
        "[v2][cta]overlay=0:0:enable='between(t,{ic},{dur})'[vout]"
    ).format(
        ts=t_inicio, te=t_fin,
        w=TT_W, h=TT_H,
        dh=dur_hook,
        ia=inicio_anal, ic=inicio_cta,
        dur=dur
    )

    cmd = [
        FFMPEG, "-y",
        "-i", in_str,
        "-i", hook_str,
        "-i", anal_str,
        "-i", cta_str,
        "-filter_complex", filtro_escala,
        "-map", "[vout]",
        "-map", "0:a?",          # audio original si existe
        "-ss", str(t_inicio),
        "-t", str(dur),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "128k",
        "-af", "apad",           # rellenar audio corto con silencio hasta duración del video
        "-movflags", "+faststart",
        "-r", str(FPS),
        out_str
    ]

    log(f"Ejecutando ffmpeg... (duracion clip: {dur:.1f}s)")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"ERROR ffmpeg: {result.stderr[-500:]}")
        return False
    log(f"Video editado: {output_path}")
    return True


def editar_limpio(input_path: str, output_path: str, t_inicio: float, t_fin: float):
    """
    Version SIN texto ni overlays: recorta y reformatea a 9:16 (1080x1920) con
    barras negras (RAPIDO, sin blur). Para clips de futbol/cine ('solo el clip').
    """
    dur_real = obtener_duracion_real(input_path)
    if dur_real is not None and t_fin > dur_real:
        t_fin = dur_real
    dur = t_fin - t_inicio

    in_str  = str(input_path).replace("\\", "/")
    out_str = str(output_path).replace("\\", "/")

    # Solo escala a 9:16 con pad negro — sin blur (mucho mas rapido)
    vf = (
        "scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        "pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"
    ).format(w=TT_W, h=TT_H)

    cmd = [
        FFMPEG, "-y",
        "-ss", str(t_inicio),
        "-i", in_str,
        "-t", str(dur),
        "-vf", vf,
        "-map", "0:v:0",
        "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-af", "apad",
        "-movflags", "+faststart", "-r", str(FPS),
        out_str
    ]
    log(f"Ejecutando ffmpeg LIMPIO (sin texto, rapido)... (duracion: {dur:.1f}s)")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"ERROR ffmpeg: {result.stderr[-500:]}")
        return False
    log(f"Video editado (limpio): {output_path}")
    return True


# ── Guardar en DB ─────────────────────────────────────────────────────────────
def guardar_en_db(video_id: int, archivo_editado: str):
    conn = psycopg2.connect(DB_CONN)
    cur  = conn.cursor()
    cur.execute("""
        UPDATE tt_videos SET
            archivo_editado = %s,
            estado = 'listo',
            actualizado_en = NOW()
        WHERE id = %s
    """, (archivo_editado, video_id))
    cur.execute("""
        INSERT INTO tt_log (video_id, accion, detalle)
        VALUES (%s, 'video_editado', %s)
    """, (video_id, f"Archivo: {archivo_editado}"))
    conn.commit()
    cur.close()
    conn.close()


def cargar_config_db(video_id: int) -> dict:
    conn = psycopg2.connect(DB_CONN)
    cur  = conn.cursor()
    cur.execute("""
        SELECT v.archivo_crudo, v.t_inicio, v.t_fin, v.hook_texto,
               v.analisis_texto, v.titulo_post, p.titulo
        FROM tt_videos v
        LEFT JOIN tt_peliculas p ON p.id = v.pelicula_id
        WHERE v.id = %s
    """, (video_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise ValueError(f"Video ID {video_id} no encontrado en DB")
    return {
        "input":    row[0], "t_inicio": float(row[1] or 0),
        "t_fin":    float(row[2] or 30), "hook":    row[3] or "Este detalle lo cambia todo",
        "analisis": row[4] or "", "titulo":  row[5] or row[6] or "video",
        "pelicula": row[6] or "",
    }


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="SIMBAI TikTok Editor")
    parser.add_argument("input", nargs="?", help="Archivo de video fuente")
    parser.add_argument("--video-id",  type=int, help="ID del video en DB (lee config automaticamente)")
    parser.add_argument("--inicio",    type=float, default=0,   help="Tiempo de inicio en segundos")
    parser.add_argument("--fin",       type=float, default=45,  help="Tiempo de fin en segundos")
    parser.add_argument("--hook",      type=str,   default="Este detalle lo cambia todo 🤯")
    parser.add_argument("--analisis",  type=str,   default="Explicacion en los comentarios 👇")
    parser.add_argument("--output",    type=str,   help="Ruta del archivo de salida")
    args = parser.parse_args()

    # Cargar config
    limpio = False
    if args.video_id:
        cfg = cargar_config_db(args.video_id)
        input_path  = cfg["input"]
        t_inicio    = cfg["t_inicio"]
        t_fin       = cfg["t_fin"]
        hook_texto  = cfg["hook"]
        analisis    = cfg["analisis"]
        titulo      = cfg["titulo"].replace(" ", "_")[:40]
        # Clips de futbol y cine (agentes automaticos) → sin texto, solo el clip
        if cfg.get("pelicula", "").strip().lower() in ("mundial 2026", "cine escenas"):
            limpio = True
    else:
        if not args.input:
            parser.error("Especifica un archivo de entrada o --video-id")
        input_path = args.input
        t_inicio   = args.inicio
        t_fin      = args.fin
        hook_texto = args.hook
        analisis   = args.analisis
        titulo     = Path(input_path).stem[:40]

    # Validar
    dur = t_fin - t_inicio
    if not (MIN_DURACION <= dur <= MAX_DURACION):
        log(f"AVISO: duracion {dur:.1f}s fuera del rango optimo ({MIN_DURACION}-{MAX_DURACION}s)")

    if not Path(input_path).exists():
        log(f"ERROR: archivo no encontrado: {input_path}")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Output path
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output or str(OUT_DIR / f"{titulo}_{ts}.mp4")

    log(f"=== SIMBAI TikTok Editor ===")
    log(f"Input:    {input_path}")
    log(f"Clip:     {t_inicio:.1f}s → {t_fin:.1f}s ({dur:.1f}s)")
    log(f"Hook:     {hook_texto[:60]}")
    log(f"Analisis: {analisis[:60]}")
    log(f"Output:   {output_path}")

    if limpio:
        log("Modo LIMPIO: solo el clip, sin texto ni overlays")
        exito = editar_limpio(input_path, output_path, t_inicio, t_fin)
    else:
        # Generar overlays
        log("Generando overlays...")
        hook_img    = generar_frame_hook(hook_texto)
        analisis_img= generar_frame_analisis(analisis)
        cta_img     = generar_frame_cta()

        # Editar video
        exito = editar_con_ffmpeg(
            input_path, output_path,
            t_inicio, t_fin,
            hook_img, analisis_img, cta_img,
            dur
        )

    if exito:
        size_mb = Path(output_path).stat().st_size / 1024 / 1024
        log(f"✅ Video listo: {output_path} ({size_mb:.1f} MB)")
        if args.video_id:
            guardar_en_db(args.video_id, output_path)
            log("✅ DB actualizada")
    else:
        log("❌ Error en la edicion")
        sys.exit(1)


if __name__ == "__main__":
    main()
