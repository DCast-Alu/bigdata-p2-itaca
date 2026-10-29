import os
import json
import hashlib
import logging
from collections import defaultdict
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingesta_itaca_bd")

RUTA_RAW = "data/raw"

# Columnas a extraer de cada tabla, renombradas al esquema del proyecto
CONSULTAS = {
    "alumnos": """
        SELECT anyo, nia, curso, turno, grupo
        FROM alumnos
    """,
    "contenidos": """
        SELECT anyo, curso, codigo AS modulo, nombre_cas AS nombre_modulo
        FROM contenidos
    """,
    "calificaciones": """
        SELECT anyo, alumno AS nia, curso, contenido AS modulo,
               nota_numerica AS nota, evaluacion
        FROM calificaciones
    """,
    "cursos": """
        SELECT anyo, codigo, nombre_cas, padre
        FROM cursos
    """,
}

# Caché de hashes: cada NIA original se anonimiza una única vez y se reutiliza
# en todas las tablas, de modo que alumnos y calificaciones siguen cruzándose.
_nias_anonimizados: dict[str, str] = {}


def anonimizar_nia(nia: str) -> str:
    return hashlib.sha256(str(nia).encode()).hexdigest()[:10]


def nia_anonimo(nia: str) -> str:
    if nia not in _nias_anonimizados:
        _nias_anonimizados[nia] = anonimizar_nia(nia)
    return _nias_anonimizados[nia]


def carpeta_curso(anyo: int) -> str:
    """2021 -> '2021_22'"""
    return f"{anyo}_{(anyo + 1) % 100:02d}"


def conectar():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"), user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def extraer_tabla(conexion, tabla: str) -> list[dict]:
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(CONSULTAS[tabla])
        filas = [dict(fila) for fila in cur.fetchall()]
    for fila in filas:
        if "nia" in fila:
            fila["nia"] = nia_anonimo(fila["nia"])
    return filas


def guardar(datos: list[dict], nombre: str) -> None:
    por_anyo = defaultdict(list)
    for fila in datos:
        por_anyo[fila["anyo"]].append(fila)

    for anyo, filas in sorted(por_anyo.items()):
        carpeta = os.path.join(RUTA_RAW, carpeta_curso(anyo))
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, f"{nombre}.json")
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(filas, f, ensure_ascii=False, indent=2, default=str)
        logger.info("Guardados %d registros en %s", len(filas), ruta)


if __name__ == "__main__":
    conexion = conectar()
    try:
        for tabla in CONSULTAS:
            guardar(extraer_tabla(conexion, tabla), tabla)
    finally:
        conexion.close()
    logger.info("NIA distintos anonimizados: %d", len(_nias_anonimizados))
