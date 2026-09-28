#!/usr/bin/env python3
"""
SIMBAI — Poster de TikTok via Cookies de Sesión
Sube videos procesados a TikTok usando autenticacion por cookies.

Uso:
  python tiktok_poster.py --video video.mp4 --caption "Texto..." --hashtags "#pelicula #cine"
  python tiktok_poster.py --video-id 1           (lee desde DB, sube el video editado)
  python tiktok_poster.py --procesar-pendientes   (sube todos los 'programados' cuya hora llegó)
"""

import sys, os, json, argparse, time, logging
import psycopg2

# Silence tiktok_uploader debug logs (cookie spam)
logging.getLogger("tiktok_uploader").setLevel(logging.WARNING)
from pathlib import Path

import config
from datetime import datetime, timezone

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DB_CONN = config.DB_CONN
COOKIES_PATH = config.COOKIES_PATH
OUT_DIR      = config.SALIDA_DIR

# Hashtags base para cuentas de reseñas
HASHTAGS_BASE = "#cine #peliculas #analisiscinematografico #fyp #foryou #movie #film #reseña"


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def _limpiar_navegador():
    """Mata restos de Chrome de automatización (chromedriver + chrome lanzado por
    Selenium) que quedan huérfanos tras un timeout, para que la siguiente subida
    arranque limpia. NO toca el Chrome normal del usuario (ese no lleva
    --enable-automation ni desciende de chromedriver.exe)."""
    import subprocess
    # chromedriver.exe es exclusivo de automatización → seguro matarlo con su árbol
    subprocess.run(["taskkill", "/F", "/IM", "chromedriver.exe", "/T"],
                   capture_output=True)
    # cinturón y tirantes: cerrar chrome.exe que lleve flags de automatización
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -match '--enable-automation|--test-type' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)


def cargar_cookies() -> list[dict]:
    if not COOKIES_PATH.exists():
        raise FileNotFoundError(
            f"Cookies no encontradas en {COOKIES_PATH}\n"
            "Instrucciones:\n"
            "  1. Instala la extension 'Cookie-Editor' en Chrome/Firefox\n"
            "  2. Ve a tiktok.com logueado con tu cuenta\n"
            "  3. Abre Cookie-Editor → Export → Export as JSON\n"
            f"  4. Guarda el archivo en: {COOKIES_PATH}"
        )
    with open(COOKIES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def subir_video(
    video_path: str,
    caption: str,
    hashtags: str = "",
    schedule_time: datetime = None
) -> dict:
    """
    Sube un video a TikTok usando tiktok-uploader con cookies de sesion.
    Retorna dict con resultado.
    """
    if not Path(video_path).exists():
        return {"exito": False, "error": f"Archivo no encontrado: {video_path}"}

    # Validar tamaño (TikTok max 287MB)
    size_mb = Path(video_path).stat().st_size / 1024 / 1024
    if size_mb > 280:
        return {"exito": False, "error": f"Archivo demasiado grande: {size_mb:.1f}MB (max 280MB)"}

    cookies = cargar_cookies()

    caption_final = caption
    if hashtags:
        caption_final = f"{caption}\n\n{hashtags}"
    if HASHTAGS_BASE not in caption_final:
        caption_final += f"\n{HASHTAGS_BASE}"

    # Limitar caption a 2200 caracteres (limite TikTok)
    caption_final = caption_final[:2200]

    log(f"Subiendo: {Path(video_path).name} ({size_mb:.1f}MB)")
    log(f"Caption: {caption_final[:100]}...")

    from tiktok_uploader.upload import upload_video

    kwargs = {
        "filename":     video_path,
        "description":  caption_final,
        "cookies_list": cookies,
        "headless":     True,
    }
    if schedule_time:
        kwargs["schedule"] = schedule_time

    # UN solo intento por proceso: tiktok_uploader usa Playwright Sync API y no
    # se puede reinvocar en el mismo proceso (peta con "Sync API inside the
    # asyncio loop"). El reintento lo hace quien llama, en un proceso NUEVO.
    _limpiar_navegador()  # navegador limpio antes de subir (mata restos huérfanos)
    try:
        result = upload_video(**kwargs)
        # upload_video returns list of FAILED videos; empty = success
        if result:  # non-empty = failure
            log(f"❌ Upload fallido (library): {str(result)[:200]}")
            return {"exito": False, "error": f"Upload failed: {str(result)[:500]}"}
        log("✅ Video subido exitosamente")
        return {"exito": True, "tiktok_id": "ok", "caption": caption_final}
    except Exception as e:
        log(f"❌ Error subiendo: {e}")
        return {"exito": False, "error": str(e)}
    finally:
        _limpiar_navegador()  # no dejar Chrome huérfano para el siguiente proceso


# ── Flujo desde DB ─────────────────────────────────────────────────────────────
def subir_por_id(video_id: int) -> bool:
    conn = psycopg2.connect(DB_CONN)
    cur  = conn.cursor()
    cur.execute("""
        SELECT v.archivo_editado, v.caption, v.hashtags, v.titulo_post, v.estado
        FROM tt_videos v WHERE v.id = %s
    """, (video_id,))
    row = cur.fetchone()
    if not row:
        log(f"Video {video_id} no encontrado en DB")
        cur.close(); conn.close()
        return False

    archivo, caption, hashtags, titulo, estado = row

    if estado == "publicado":
        log(f"Video {video_id} ya fue publicado")
        cur.close(); conn.close()
        return False

    if not archivo or not Path(archivo).exists():
        log(f"Archivo editado no encontrado: {archivo}")
        log("Primero edita el video con: python tiktok_editor.py --video-id {video_id}")
        cur.close(); conn.close()
        return False

    caption_uso = caption or titulo or "Análisis cinematográfico 🎬"
    hashtags_uso = hashtags or HASHTAGS_BASE

    cur.close(); conn.close()

    try:
        resultado = subir_video(archivo, caption_uso, hashtags_uso)
    except Exception as e:
        resultado = {"exito": False, "error": str(e)}

    conn = psycopg2.connect(DB_CONN)
    cur  = conn.cursor()

    if resultado["exito"]:
        cur.execute("""
            UPDATE tt_videos SET
                estado = 'publicado',
                publicado_en = NOW(),
                tiktok_id = %s,
                actualizado_en = NOW()
            WHERE id = %s
        """, (resultado.get("tiktok_id",""), video_id))
        cur.execute("""
            INSERT INTO tt_log (video_id, accion, detalle)
            VALUES (%s, 'publicado', %s)
        """, (video_id, f"TikTok ID: {resultado.get('tiktok_id','')}"))
        conn.commit()
        log(f"✅ Video {video_id} publicado en TikTok")
    else:
        cur.execute("UPDATE tt_videos SET estado='fallido', actualizado_en=NOW() WHERE id=%s", (video_id,))
        cur.execute("""
            INSERT INTO tt_log (video_id, accion, detalle)
            VALUES (%s, 'error_upload', %s)
        """, (video_id, resultado.get("error","")))
        conn.commit()
        log(f"❌ Error publicando video {video_id}: {resultado.get('error','')}")

    cur.close()
    conn.close()
    return resultado["exito"]


def procesar_pendientes():
    """Sube todos los videos programados cuya hora de publicacion ya llegó"""
    conn = psycopg2.connect(DB_CONN)
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, titulo_post FROM tt_videos
        WHERE estado = 'programado'
          AND publicar_en IS NOT NULL
          AND publicar_en <= NOW()
        ORDER BY publicar_en ASC
    """)
    pendientes = cur.fetchall()
    cur.close()
    conn.close()

    if not pendientes:
        log("Sin videos programados para publicar ahora")
        return

    log(f"{len(pendientes)} video(s) listos para publicar")
    for vid_id, titulo in pendientes:
        log(f"--- Publicando: [{vid_id}] {titulo} ---")
        subir_por_id(vid_id)
        time.sleep(10)  # pausa entre uploads para evitar rate limit


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="SIMBAI TikTok Poster")
    parser.add_argument("--video",               help="Ruta directa al video a subir")
    parser.add_argument("--caption",             help="Caption del post")
    parser.add_argument("--hashtags",            help="Hashtags adicionales")
    parser.add_argument("--video-id", type=int,  help="ID del video en DB")
    parser.add_argument("--procesar-pendientes", action="store_true", help="Procesar cola de programados")
    args = parser.parse_args()

    if args.procesar_pendientes:
        procesar_pendientes()
    elif args.video_id:
        ok = subir_por_id(args.video_id)
        if not ok:
            sys.exit(1)
    elif args.video:
        r = subir_video(args.video, args.caption or "🎬 Análisis cinematográfico", args.hashtags or "")
        if not r["exito"]:
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
