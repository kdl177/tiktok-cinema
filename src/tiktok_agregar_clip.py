#!/usr/bin/env python3
"""
SIMBAI — Agregar clip al pipeline TikTok (para uso del Agente Externo)
Registra una película y un clip en la DB con hook automático.

Uso:
  python tiktok_agregar_clip.py --pelicula "Interstellar" --archivo "C:\...\interstellar.mp4" --inicio 2820 --fin 2865 --hook-tipo revelacion
  python tiktok_agregar_clip.py --pelicula "El Padrino" --archivo "ruta.mp4" --inicio 3600 --fin 3650
"""

import sys, os, json, argparse, random
import psycopg2

import config
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DB_CONN = config.DB_CONN

HASHTAGS_POR_GENERO = {
    "accion":    "#fyp #pelicula #accion #cine #foryou #movieanalysis #thriller",
    "drama":     "#fyp #drama #cine #oscar #pelicula #analisis #foryou",
    "terror":    "#fyp #horror #terror #cine #peliculadeterror #foryou #scary",
    "scifi":     "#fyp #scifi #cienciayficcion #cine #nolan #pelicula #foryou",
    "thriller":  "#fyp #thriller #suspenso #cine #pelicula #foryou",
    "comedia":   "#fyp #comedia #cine #pelicula #humor #foryou",
    "animacion": "#fyp #animacion #disney #pixar #cine #pelicula #foryou",
    "default":   "#fyp #cine #pelicula #analisiscinematografico #foryou #film",
}

ANALISIS_POR_TIPO = {
    "revelacion":   "Nadie nota este detalle la primera vez",
    "dato_oculto":  "El director escondió esto intencionalmente",
    "pregunta":     "¿Por qué esta escena genera esta reacción?",
    "prediccion":   "Esta escena predijo algo que pasó en la realidad",
    "controversia": "Esta es la escena más malinterpretada del film",
    "urgencia":     "Necesitás ver esto antes de volver a verla",
}


def db():
    return psycopg2.connect(DB_CONN)


def obtener_hook(tipo: str, pelicula: str, año: int = None) -> str:
    conn = db()
    cur  = conn.cursor()
    filtro = f"AND tipo = '{tipo}'" if tipo else ""
    cur.execute(f"""
        SELECT texto FROM tt_hooks
        WHERE activo = true {filtro}
        ORDER BY RANDOM() LIMIT 1
    """)
    row = cur.fetchone()
    cur.close(); conn.close()

    if not row:
        return f"Este detalle de {pelicula} lo cambia todo 🤯"

    hook = row[0].replace("{PELICULA}", pelicula)
    if año:
        hook = hook.replace("{AÑO}", str(año))
    return hook


def registrar_pelicula(titulo: str, archivo: str = None, año: int = None,
                        genero: str = None, youtube_url: str = None) -> int:
    conn = db()
    cur  = conn.cursor()
    cur.execute("SELECT id FROM tt_peliculas WHERE titulo = %s", (titulo,))
    row = cur.fetchone()
    if row:
        pid = row[0]
        if youtube_url:
            cur.execute("UPDATE tt_peliculas SET youtube_url=%s WHERE id=%s",
                        (youtube_url, pid))
            conn.commit()
        cur.close(); conn.close()
        return pid

    cur.execute("""
        INSERT INTO tt_peliculas (titulo, año, genero, archivo, youtube_url)
        VALUES (%s, %s, %s, %s, %s) RETURNING id
    """, (titulo, año, genero, archivo, youtube_url))
    pid = cur.fetchone()[0]
    conn.commit(); cur.close(); conn.close()
    print(f"  ✅ Película registrada: {titulo} (id={pid})")
    return pid


def registrar_clip(
    pelicula_id: int,
    pelicula_nombre: str,
    archivo: str = None,
    t_inicio: float = 0,
    t_fin: float = 45,
    hook_tipo: str = "revelacion",
    genero: str = "default",
    año: int = None,
    youtube_url: str = None,
    yt_inicio: float = None,
    yt_fin: float = None,
) -> int:
    hook        = obtener_hook(hook_tipo, pelicula_nombre, año)
    analisis    = ANALISIS_POR_TIPO.get(hook_tipo, "Un análisis que te va a sorprender")
    hashtags    = HASHTAGS_POR_GENERO.get(genero, HASHTAGS_POR_GENERO["default"])
    dur         = t_fin - t_inicio
    titulo_post = hook[:100]
    caption     = (
        f"{hook}\n\n"
        f"🎬 {pelicula_nombre}{f' ({año})' if año else ''}\n\n"
        f"¿Lo habías notado? Contame en los comentarios 👇\n\n"
        f"{hashtags} #analisiscinematografico"
    )

    conn = db()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO tt_videos
          (pelicula_id, titulo_post, hook_texto, analisis_texto, caption, hashtags,
           t_inicio, t_fin, duracion_s, archivo_crudo, youtube_url, yt_inicio, yt_fin, estado)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pendiente')
        RETURNING id
    """, (pelicula_id, titulo_post, hook, analisis, caption, hashtags,
          t_inicio, t_fin, int(dur), archivo, youtube_url,
          yt_inicio if yt_inicio is not None else t_inicio,
          yt_fin    if yt_fin    is not None else t_fin))
    vid_id = cur.fetchone()[0]
    cur.execute("""
        INSERT INTO tt_log (video_id, accion, detalle)
        VALUES (%s, 'clip_registrado', %s)
    """, (vid_id, f"Clip {t_inicio:.0f}s-{t_fin:.0f}s de {pelicula_nombre}"))
    conn.commit(); cur.close(); conn.close()
    return vid_id


def main():
    parser = argparse.ArgumentParser(
        description="Agregar clip al pipeline TikTok (con archivo local o YouTube URL)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Con archivo local:
  python tiktok_agregar_clip.py --pelicula "Matrix" --archivo "C:\\...\\matrix.mp4" --inicio 0 --fin 45

  # Con YouTube (descarga automática):
  python tiktok_agregar_clip.py --pelicula "Matrix" --youtube-url "https://youtube.com/watch?v=..." --yt-inicio 10 --yt-fin 55
        """
    )
    parser.add_argument("--pelicula",     required=True, help="Nombre de la película")
    parser.add_argument("--archivo",      default=None,  help="Ruta al archivo MP4 local (opcional si hay --youtube-url)")
    parser.add_argument("--inicio",       type=float, default=0,  help="Segundo de inicio del clip en el archivo")
    parser.add_argument("--fin",          type=float, default=45, help="Segundo de fin del clip en el archivo")
    parser.add_argument("--youtube-url",  default=None,  help="URL del clip en YouTube (si no hay archivo local)")
    parser.add_argument("--yt-inicio",    type=float, default=None, help="Segundo de inicio en el video de YouTube")
    parser.add_argument("--yt-fin",       type=float, default=None, help="Segundo de fin en el video de YouTube")
    parser.add_argument("--año",          type=int,   default=None)
    parser.add_argument("--genero",       default="default", choices=list(HASHTAGS_POR_GENERO.keys()))
    parser.add_argument("--hook-tipo",    default="revelacion",
                        choices=["revelacion","pregunta","dato_oculto","controversia","urgencia","prediccion"])
    args = parser.parse_args()

    if not args.archivo and not args.youtube_url:
        print("❌ Necesitás --archivo o --youtube-url")
        sys.exit(1)

    if args.archivo and not Path(args.archivo).exists():
        print(f"❌ Archivo no encontrado: {args.archivo}")
        sys.exit(1)

    # Si solo hay youtube_url, usar yt_inicio/yt_fin como t_inicio/t_fin
    if not args.archivo and args.youtube_url:
        inicio = args.yt_inicio if args.yt_inicio is not None else 0
        fin    = args.yt_fin    if args.yt_fin    is not None else 45
    else:
        inicio = args.inicio
        fin    = args.fin

    dur = fin - inicio
    if not (10 <= dur <= 180):
        print(f"⚠ Duración {dur:.0f}s fuera del rango óptimo (10-180s). Continuando igual...")

    print(f"\n🎬 Registrando clip: {args.pelicula}")
    if args.youtube_url:
        print(f"   Fuente: YouTube ({args.youtube_url[:60]}...)")
    print(f"   Clip: {inicio:.0f}s → {fin:.0f}s ({dur:.0f}s)")

    pid    = registrar_pelicula(args.pelicula, args.archivo, args.año, args.genero, args.youtube_url)
    vid_id = registrar_clip(
        pid, args.pelicula,
        archivo     = args.archivo,
        t_inicio    = inicio,
        t_fin       = fin,
        hook_tipo   = args.hook_tipo,
        genero      = args.genero,
        año         = args.año,
        youtube_url = args.youtube_url,
        yt_inicio   = args.yt_inicio,
        yt_fin      = args.yt_fin,
    )

    print(f"  ✅ Video registrado en pipeline (id={vid_id})")
    if args.youtube_url:
        print(f"  El pipeline descargará el clip automáticamente desde YouTube")
    print(f"  Estado: pendiente → el pipeline lo editará y publicará automáticamente")
    print(f"\n  Para procesar ahora mismo:")
    print(f"  python C:\\SIMBAI\\scripts\\tiktok_pipeline.py")


if __name__ == "__main__":
    main()
