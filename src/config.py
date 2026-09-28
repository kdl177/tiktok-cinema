"""Rutas y ajustes del pipeline.

Todo sale de variables de entorno con un valor por defecto relativo a la
carpeta de instalación, para que el proyecto funcione desde cualquier sitio.
Antes estaban escritas a mano apuntando a C:\\SIMBAI y a una carpeta de
usuario concreta.
"""

import os
from pathlib import Path


def _ruta(variable: str, por_defecto: Path) -> Path:
    valor = os.getenv(variable)
    return Path(valor) if valor else por_defecto


# Raíz del proyecto: la carpeta que contiene src/
RAIZ = Path(__file__).resolve().parent.parent

DATOS_DIR = _ruta("TIKTOK_DATOS_DIR", RAIZ / "datos")
SALIDA_DIR = _ruta("TIKTOK_SALIDA_DIR", RAIZ / "salida")

# Dónde se descargan los clips y dónde quedan los vídeos montados
PELICULAS_DIR = DATOS_DIR / "peliculas"
GUIONES_DIR = DATOS_DIR / "guiones"
EDITADOS_DIR = SALIDA_DIR / "editados"
LOG_FILE = SALIDA_DIR / "pipeline.log"

# Sesión de TikTok. Nunca se versiona: cada instalación aporta la suya.
COOKIES_PATH = _ruta("TIKTOK_COOKIES", DATOS_DIR / "cookies.json")

# Fuentes para los subtítulos. En Windows están en C:\Windows\Fonts.
FUENTE_NEGRITA = _ruta(
    "TIKTOK_FUENTE_NEGRITA", Path(r"C:\Windows\Fonts\arialbd.ttf")
)
FUENTE_NORMAL = _ruta("TIKTOK_FUENTE_NORMAL", Path(r"C:\Windows\Fonts\arial.ttf"))

# ffmpeg: si no se indica, se usa el que trae imageio-ffmpeg.
FFMPEG = os.getenv("TIKTOK_FFMPEG")

# Conexión a PostgreSQL. Antes estaba escrita a mano en seis ficheros, con
# usuario y contraseña incluidos: eso no puede vivir en un repositorio.
DB_CONN = os.getenv(
    "DATABASE_URL", "postgresql://postgres@localhost:5432/tiktok_cinema"
)


def preparar_carpetas() -> None:
    """Crea las carpetas de trabajo si no existen."""
    for carpeta in (PELICULAS_DIR, GUIONES_DIR, EDITADOS_DIR):
        carpeta.mkdir(parents=True, exist_ok=True)
