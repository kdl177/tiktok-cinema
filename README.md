# TikTok Cinema

Pipeline que descarga clips de cine, los monta en vertical con subtítulos y voz
en off, y los publica en TikTok sin intervención.

Construido por [SIMBAI](https://simbai.vercel.app). Se cede sin coste.

---

## Qué hace

1. **Descarga** clips de YouTube con `yt-dlp`, con control de duplicados.
2. **Monta** el vídeo en 9:16 con `ffmpeg`: recorte, escalado y overlays.
3. **Transcribe** en local con Whisper y quema los subtítulos sobre el vídeo.
4. **Genera la locución** con `edge-tts`, sin API de pago ni coste por carácter.
5. **Publica** en el horario configurado, mediante Task Scheduler o cron.

---

## Requisitos

- **Python 3.11 o superior**
- **ffmpeg** en el PATH (o indicado en `TIKTOK_FFMPEG`)
- **PostgreSQL 14 o superior**. No es opcional: el pipeline lleva en la base
  qué se ha descargado, montado y publicado, y sin ella no arranca.
- Una sesión de TikTok exportada del navegador, si quieres publicación automática.

---

## Instalación

```bash
git clone https://github.com/kdl177/tiktok-cinema
cd tiktok-cinema

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
```

Después crea la base de datos y sus tablas:

```bash
createdb tiktok_cinema
psql -d tiktok_cinema -f schema.sql
```

Después copia la configuración y ajústala:

```bash
copy .env.example .env        # Windows
# cp .env.example .env        # macOS / Linux
```

Funciona sin tocar nada: por defecto usa las carpetas `datos/` y `salida/`
dentro del propio proyecto.

---

## Las cookies de TikTok

Para publicar automáticamente hace falta tu sesión de TikTok:

1. Inicia sesión en tiktok.com en tu navegador.
2. Con una extensión de exportación de cookies, guarda las del dominio en
   formato JSON.
3. Déjalo en `datos/cookies.json`, o indica otra ruta en `TIKTOK_COOKIES`.

**Ese fichero son credenciales.** Quien lo tenga puede publicar en tu cuenta.
Está en `.gitignore` y no debe compartirse ni subirse a ningún repositorio.

Sin cookies el pipeline funciona igual: monta los vídeos y los deja en
`salida/editados/` para que los subas a mano.

---

## Uso

```bash
# Pipeline completo: descarga, monta y publica
python src/tiktok_pipeline.py

# Solo descargar clips
python src/tiktok_downloader.py

# Solo montar un vídeo ya descargado
python src/tiktok_editor.py

# Añadir un clip concreto al banco
python src/tiktok_agregar_clip.py --pelicula "Interstellar" --inicio 2820 --fin 2865
```

### Automatizarlo

En Windows, con el Programador de tareas:

```
Programa:   C:\ruta\al\proyecto\.venv\Scripts\python.exe
Argumentos: C:\ruta\al\proyecto\src\tiktok_pipeline.py
Iniciar en: C:\ruta\al\proyecto
```

En Linux o macOS, con cron:

```
0 9,13,17,20,23 * * * cd /ruta/al/proyecto && .venv/bin/python src/tiktok_pipeline.py
```

---

## Configuración

Todo se ajusta por variables de entorno. Ninguna es obligatoria:

| Variable | Para qué | Por defecto |
|---|---|---|
| `TIKTOK_DATOS_DIR` | Clips descargados y guiones | `./datos` |
| `TIKTOK_SALIDA_DIR` | Vídeos montados y log | `./salida` |
| `TIKTOK_COOKIES` | Sesión de TikTok | `./datos/cookies.json` |
| `TIKTOK_FFMPEG` | Binario de ffmpeg propio | el de `imageio-ffmpeg` |
| `TIKTOK_FUENTE_NEGRITA` | Fuente de los subtítulos | Arial Bold del sistema |
| `DATABASE_URL` | Conexión a PostgreSQL | `postgresql://postgres@localhost:5432/tiktok_cinema` |

---

## Derechos de autor

Este pipeline descarga y reutiliza fragmentos de películas. Que el uso encaje
en cita o parodia depende de la legislación de cada país y del uso concreto que
le des. Revísalo antes de publicar: la responsabilidad es de quien publica.

---

## Estado

Código cedido tal cual, sin garantía ni soporte comprometido. Funciona en
Windows, que es donde se ha usado en producción; en Linux y macOS debería
funcionar pero no está probado a fondo.

Si te atascas, escribe a hidra.lucas.g45@gmail.com.
