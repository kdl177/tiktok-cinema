-- Esquema de TikTok Cinema.
--
-- El pipeline lleva el registro de qué se ha descargado, montado y publicado
-- en estas cuatro tablas. Sin ellas no arranca.
--
--   psql -U postgres -d simbai -f schema.sql
--
-- Se puede ejecutar varias veces sin romper nada.

CREATE TABLE IF NOT EXISTS tt_peliculas (
    id          SERIAL PRIMARY KEY,
    titulo      TEXT NOT NULL UNIQUE,
    año         INTEGER,
    genero      TEXT,
    archivo     TEXT,
    youtube_url TEXT,
    creado_en   TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tt_videos (
    id             SERIAL PRIMARY KEY,
    pelicula_id    INTEGER REFERENCES tt_peliculas(id) ON DELETE CASCADE,

    -- Texto del post
    titulo_post    TEXT,
    hook_texto     TEXT,
    analisis_texto TEXT,
    caption        TEXT,
    hashtags       TEXT,

    -- Origen del clip y recorte
    youtube_url    TEXT,
    yt_inicio      INTEGER,
    yt_fin         INTEGER,
    t_inicio       INTEGER,
    t_fin          INTEGER,
    duracion_s     INTEGER,

    -- Ficheros generados
    archivo_crudo  TEXT,
    archivo_final  TEXT,

    -- pendiente → listo → programado → publicado
    estado         TEXT NOT NULL DEFAULT 'pendiente',

    -- Hora a la que toca publicar; publicado_en es cuando se publicó de hecho
    publicar_en    TIMESTAMP,
    publicado_en   TIMESTAMP,
    tiktok_id      TEXT,
    creado_en      TIMESTAMP NOT NULL DEFAULT NOW(),
    actualizado_en TIMESTAMP NOT NULL DEFAULT NOW()
);

-- La consulta que busca trabajo pendiente filtra por estas dos columnas.
CREATE INDEX IF NOT EXISTS idx_tt_videos_estado ON tt_videos(estado);
CREATE INDEX IF NOT EXISTS idx_tt_videos_youtube ON tt_videos(youtube_url);
CREATE INDEX IF NOT EXISTS idx_tt_videos_publicar ON tt_videos(publicar_en);

-- Banco de ganchos. El pipeline elige uno al azar entre los activos.
CREATE TABLE IF NOT EXISTS tt_hooks (
    id        SERIAL PRIMARY KEY,
    texto     TEXT NOT NULL,
    tipo      TEXT,
    activo    BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tt_hooks_activo ON tt_hooks(activo);

-- Traza de lo que hace el pipeline, para poder revisarlo después.
CREATE TABLE IF NOT EXISTS tt_log (
    id        SERIAL PRIMARY KEY,
    video_id  INTEGER REFERENCES tt_videos(id) ON DELETE CASCADE,
    accion    TEXT NOT NULL,
    detalle   TEXT,
    creado_en TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tt_log_video ON tt_log(video_id);

-- Ganchos de arranque, para que la primera ejecución tenga de dónde elegir.
INSERT INTO tt_hooks (texto, tipo) VALUES
    ('Esta escena lo cambió todo', 'revelacion'),
    ('Nadie se dio cuenta de este detalle', 'detalle'),
    ('El plano que costó una fortuna', 'produccion'),
    ('Por qué esta escena sigue doliendo', 'emocion'),
    ('Lo que el director nunca explicó', 'misterio')
ON CONFLICT DO NOTHING;
