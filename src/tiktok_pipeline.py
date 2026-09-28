#!/usr/bin/env python3
"""
SIMBAI — Pipeline Automático TikTok
Corre diariamente vía Task Scheduler.
1. Edita todos los clips pendientes con archivo_crudo registrado
2. Programa los videos listos en horarios óptimos
3. Publica los videos cuya hora llegó
"""

import sys, os, json, time, subprocess
import psycopg2
from pathlib import Path

import config
from datetime import datetime, date, timedelta

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

DB_CONN = config.DB_CONN
COOKIES_PATH = config.COOKIES_PATH
DOWNLOADER   = r"C:\SIMBAI\scripts\tiktok_downloader.py"
EDITOR       = r"C:\SIMBAI\scripts\tiktok_editor.py"
POSTER       = r"C:\SIMBAI\scripts\tiktok_poster.py"
LOG_FILE     = config.LOG_FILE

# Horarios óptimos para publicar (hora local)
HORARIOS_OPTIMOS = ["07:00", "12:30", "18:00", "20:00", "22:00"]
MAX_POSTS_DIA    = 3   # máximo posts por día para no triggear spam detection


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linea = f"[{ts}] {msg}"
    print(linea)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except:
        pass


def db():
    return psycopg2.connect(DB_CONN)


# ── FASE 0: Descargar clips con youtube_url pero sin archivo ─────────────────
def descargar_pendientes():
    conn = db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM tt_videos
        WHERE estado = 'pendiente'
          AND (archivo_crudo IS NULL OR archivo_crudo = '')
          AND (youtube_url IS NOT NULL)
    """)
    total = cur.fetchone()[0]
    cur.close(); conn.close()

    if total == 0:
        log("Sin clips para descargar")
        return 0

    log(f"Descargando {total} clip(s) desde YouTube...")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        ["python", DOWNLOADER, "--todos"],
        capture_output=True, text=True, encoding="utf-8",
        timeout=3600, env=env
    )
    # Imprimir salida del downloader al log
    for line in result.stdout.splitlines():
        log(f"  {line}")
    if result.returncode != 0:
        log(f"  ⚠ Downloader salió con código {result.returncode}")
    return total


# ── FASE 1: Editar pendientes ─────────────────────────────────────────────────
def editar_pendientes():
    conn = db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, titulo_post, archivo_crudo, t_inicio, t_fin, hook_texto, analisis_texto
        FROM tt_videos
        WHERE estado = 'pendiente' AND archivo_crudo IS NOT NULL
        ORDER BY creado_en ASC
        LIMIT 5
    """)
    pendientes = cur.fetchall()
    cur.close(); conn.close()

    if not pendientes:
        log("Sin clips pendientes de edición")
        return 0

    log(f"Editando {len(pendientes)} clip(s)...")
    editados = 0

    for vid_id, titulo, archivo, t_ini, t_fin, hook, analisis in pendientes:
        if not archivo or not Path(archivo).exists():
            log(f"  ⚠ [{vid_id}] Archivo no encontrado: {archivo}")
            continue

        log(f"  Editando [{vid_id}] {titulo[:50]}")

        # Marcar como editando
        conn = db()
        cur  = conn.cursor()
        cur.execute("UPDATE tt_videos SET estado='editando', actualizado_en=NOW() WHERE id=%s", (vid_id,))
        conn.commit(); cur.close(); conn.close()

        # Llamar al editor
        cmd = [
            "python", EDITOR,
            "--video-id", str(vid_id)
        ]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                timeout=300, env=env)

        if result.returncode == 0:
            log(f"  ✅ [{vid_id}] Editado correctamente")
            editados += 1
        else:
            log(f"  ❌ [{vid_id}] Error: {result.stderr[-200:]}")
            conn = db()
            cur  = conn.cursor()
            cur.execute("UPDATE tt_videos SET estado='pendiente', actualizado_en=NOW() WHERE id=%s", (vid_id,))
            conn.commit(); cur.close(); conn.close()

        time.sleep(2)

    return editados


# ── FASE 2: Programar listos en horarios óptimos ─────────────────────────────
def programar_listos():
    conn = db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, titulo_post FROM tt_videos
        WHERE estado = 'listo' AND publicar_en IS NULL
        ORDER BY creado_en ASC
    """)
    listos = cur.fetchall()

    if not listos:
        cur.close(); conn.close()
        return 0

    # Anti-shadowban desactivado: programar todo para NOW (publicación inmediata)
    programados = 0
    for vid_id, titulo in listos:
        cur.execute("""
            UPDATE tt_videos SET estado='programado', publicar_en=NOW(), actualizado_en=NOW()
            WHERE id=%s
        """, (vid_id,))
        cur.execute("""
            INSERT INTO tt_log (video_id, accion, detalle)
            VALUES (%s, 'programado', %s)
        """, (vid_id, "Programado para publicación inmediata (sin anti-shadowban)"))
        log(f"  📅 [{vid_id}] {titulo[:40]} → NOW")
        programados += 1

    conn.commit()
    cur.close(); conn.close()
    return programados


# ── FASE 3: Publicar los que ya llegó su hora ────────────────────────────────
def publicar_programados():
    if not COOKIES_PATH.exists():
        log(f"⚠ Cookies no encontradas en {COOKIES_PATH} — subida omitida")
        log("  Copiá cookies.json ahí para activar la publicación automática")
        return 0

    conn = db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, titulo_post, publicar_en FROM tt_videos
        WHERE estado = 'programado'
          AND publicar_en IS NOT NULL
          AND publicar_en <= NOW()
        ORDER BY publicar_en ASC
    """)
    a_publicar = cur.fetchall()
    cur.close(); conn.close()

    if not a_publicar:
        log("Sin videos para publicar ahora")
        return 0

    log(f"Publicando {len(a_publicar)} video(s)...")
    publicados = 0

    for vid_id, titulo, pub_en in a_publicar:
        log(f"  Publicando [{vid_id}] {titulo[:50]}")
        cmd = ["python", POSTER, "--video-id", str(vid_id)]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        # Hasta 2 intentos, cada uno en un PROCESO NUEVO (el poster no se puede
        # reinvocar en el mismo proceso por Playwright Sync API).
        ok = False
        for intento in (1, 2):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                        timeout=420, env=env)
                if result.returncode == 0:
                    ok = True
                    break
                log(f"  ❌ [{vid_id}] intento {intento}: {(result.stderr or '')[-160:]}")
            except subprocess.TimeoutExpired:
                log(f"  ⏱ [{vid_id}] Timeout (>420s) intento {intento}")
            # limpiar Chrome huérfano y esperar antes del reintento
            subprocess.run(["taskkill", "/F", "/IM", "chromedriver.exe", "/T"],
                           capture_output=True)
            if intento == 1:
                time.sleep(20)

        if ok:
            log(f"  ✅ [{vid_id}] Publicado en TikTok")
            publicados += 1
        else:
            log(f"  ❌ [{vid_id}] Falló tras 2 intentos — sigo con el resto")

        time.sleep(15)  # pausa entre posts

    return publicados


# ── Resumen en DB ─────────────────────────────────────────────────────────────
def resumen_pipeline() -> str:
    conn = db()
    cur  = conn.cursor()
    cur.execute("""
        SELECT estado, COUNT(*) FROM tt_videos GROUP BY estado ORDER BY estado
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return " | ".join(f"{e}: {n}" for e, n in rows)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log("=" * 55)
    log("SIMBAI TikTok Pipeline — iniciando")
    log("=" * 55)

    # Fase 0
    log("\n[FASE 0] Descargar clips desde YouTube")
    descargar_pendientes()

    # Fase 1
    log("\n[FASE 1] Editar clips pendientes")
    editados = editar_pendientes()
    log(f"  → {editados} clip(s) editados")

    # Fase 2
    log("\n[FASE 2] Programar videos listos")
    programados = programar_listos()
    log(f"  → {programados} video(s) programados")

    # Fase 3
    log("\n[FASE 3] Publicar videos en horario")
    publicados = publicar_programados()
    log(f"  → {publicados} video(s) publicados")

    # Resumen
    log(f"\n[RESUMEN] {resumen_pipeline()}")
    log("=" * 55)


if __name__ == "__main__":
    main()
