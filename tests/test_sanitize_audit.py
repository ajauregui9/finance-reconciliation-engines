#!/usr/bin/env python3
"""Pruebas del sanitizer (`tools/sanitize_audit.py`): huellas narrativas,
identificadores estructurados, excepciones versionadas y CLI.

Compatible con `pytest` y con `python3 -m unittest discover -s tests -v`.

Toda línea de este archivo que planta una huella (o un caso frontera que se
parece a una) termina con la marca `# fixture-sanitizer`. La lista de
excepciones versionada exime solo esas líneas, así que el propio archivo pasa
el sanitizer del repo (ver `test_este_archivo_pasa_el_sanitizer_del_repo`).
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import List, Optional, Sequence, Set, Tuple
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TOOLS = str(ROOT / "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import sanitize_audit as sa  # noqa: E402

REGLAS, _REEMPLAZOS = sa.load_custom_rules(None)
IDS_REGLAS = {r.id for r in REGLAS}
RUTA_ESTE_ARCHIVO = "tests/test_sanitize_audit.py"

# Cinco huellas de tipos distintos: (regla esperada, línea de un módulo .py).
HUELLAS_PLANTADAS: Tuple[Tuple[str, str], ...] = (
    ("fecha_bitacora", "    # fix 2026-07-07: se corrige el redondeo del IVA"),  # fixture-sanitizer
    ("referencia_auditoria", "    # Ver hallazgo H1 de la revision"),  # fixture-sanitizer
    ("aprobacion_cargo", "    nota = 'autorizado por el CFO'"),  # fixture-sanitizer
    ("flujo_interno", '    """Toma el reporte oficial del mes."""'),  # fixture-sanitizer
    ("seudonimo_empresa", '    entidad = "EnterpriseCorp"'),  # fixture-sanitizer
)

# Variantes que cada regla narrativa debe marcar: (regla, extensión, contenido).
VARIANTES_POSITIVAS: Tuple[Tuple[str, str, str], ...] = (
    ("fecha_bitacora", ".py", "# Fix: 2026-07-07 redondeo"),  # fixture-sanitizer
    ("fecha_bitacora", ".py", "# hotfix 2026-07-07"),  # fixture-sanitizer
    ("fecha_bitacora", ".py", "ayuda = 'netear hasta jul-2026, luego al cliente'"),  # fixture-sanitizer
    ("fecha_bitacora", ".py", "# desde el 6-jul-2026 cambia la regla"),  # fixture-sanitizer
    ("fecha_bitacora", ".py", "# Amazon (jul-2026: movio el concepto)"),  # fixture-sanitizer
    ("fecha_bitacora", ".py", "# corregido en jun 2026"),  # fixture-sanitizer
    ("fecha_bitacora", ".md", "Applies since July 2026."),  # fixture-sanitizer
    ("referencia_auditoria", ".py", "# ── H3: base real de la retencion ──"),  # fixture-sanitizer
    ("referencia_auditoria", ".py", "msg = 'le paso al generador (H1).'"),  # fixture-sanitizer
    ("referencia_auditoria", ".py", "# Ver Hallazgos v4 R3."),  # fixture-sanitizer
    ("referencia_auditoria", ".py", "# ver v4 R3"),  # fixture-sanitizer
    ("referencia_auditoria", ".py", "# hallazgo #12 pendiente"),  # fixture-sanitizer
    ("referencia_auditoria", ".py", "# se ajusto tras la auditoría Mayo"),  # fixture-sanitizer
    ("referencia_auditoria", ".py", "# auditoria 2026-08-21"),  # fixture-sanitizer
    ("referencia_auditoria", ".py", "# segun la auditoría externa"),  # fixture-sanitizer
    ("referencia_auditoria", ".md", "Confirmed by the external audit."),  # fixture-sanitizer
    ("referencia_ticket", ".py", "# cruce de libro (ticket 08)"),  # fixture-sanitizer
    ("referencia_ticket", ".md", "Confirmed in Ticket #16."),  # fixture-sanitizer
    ("referencia_ticket", ".md", "Ver docs/tickets/03-datos.md"),  # fixture-sanitizer
    ("referencia_ticket", ".md", "Segun plan-remediacion-2026-10"),  # fixture-sanitizer
    ("aprobacion_cargo", ".py", "# aprobado por Finanzas"),  # fixture-sanitizer
    ("aprobacion_cargo", ".md", "Approved by the treasury team."),  # fixture-sanitizer
    ("aprobacion_cargo", ".py", "# lo pidio el Financial Controller"),  # fixture-sanitizer
    ("aprobacion_cargo", ".py", "# revisado con la financial controller"),  # fixture-sanitizer
    ("aprobacion_cargo", ".py", "# Directora de Finanzas"),  # fixture-sanitizer
    ("aprobacion_cargo", ".py", "# lo revisa el Contralor"),  # fixture-sanitizer
    ("aprobacion_cargo", ".py", "# con VoBo de Tesoreria"),  # fixture-sanitizer
    ("aprobacion_cargo", ".py", "# el CEO lo pidio"),  # fixture-sanitizer
    ("flujo_interno", ".py", "# los meses ya promovidos no se mueven"),  # fixture-sanitizer
    ("flujo_interno", ".py", "# targets del validated period close"),  # fixture-sanitizer
    ("flujo_interno", ".py", "estado = 'oficial'"),  # fixture-sanitizer
    ("flujo_interno", ".py", "# el cierre validado del mes"),  # fixture-sanitizer
    ("seudonimo_empresa", ".py", 'ENTIDAD = "ENTERPRISE_CORP"'),  # fixture-sanitizer
    ("seudonimo_empresa", ".json", '{"receptor": "Enterprise Corp"}'),  # fixture-sanitizer
)

# Casos frontera que NO deben marcarse con ninguna regla: (extensión, contenido).
CASOS_FRONTERA: Tuple[Tuple[str, str], ...] = (
    (".py", "H1 = 3"),  # fixture-sanitizer
    (".py", 'ws["H1"] = total'),  # fixture-sanitizer
    (".py", 'rango = "A1:H20"'),  # fixture-sanitizer
    (".md", "Copy the range A1:H20 into the summary sheet."),  # fixture-sanitizer
    (".py", '# escribe el total en ws["H1"] y en H2:H9'),  # fixture-sanitizer
    (".py", "# Proyeccion del H1 2026 por semana"),  # fixture-sanitizer
    (".py", "# Cierre del H2-2026 y del H1 FY27"),  # fixture-sanitizer
    (".py", 'periodo = "jul-2026"'),  # fixture-sanitizer
    (".py", "monto_minimo_hallazgo = 10000"),  # fixture-sanitizer
    (".json", '{"monto_minimo_hallazgo": 10000, "max_hallazgos_entregable": 20}'),  # fixture-sanitizer
    (".py", "# El auditor de P&L emite hallazgos de materialidad"),  # fixture-sanitizer
    (".py", '"""Auditoría automatizada de P&L pre-cierre."""'),  # fixture-sanitizer
    (".py", "# ticket promedio por cliente"),  # fixture-sanitizer
    (".py", "# ticket de compra del cargo"),  # fixture-sanitizer
    (".md", "Each support ticket is closed in order."),  # fixture-sanitizer
    (".py", "# Crea el directorio de salida"),  # fixture-sanitizer
    (".py", "# Tipo de cambio oficial publicado cada dia"),  # fixture-sanitizer
    (".py", "# Catalogo oficial del SAT"),  # fixture-sanitizer
    (".py", "# Publicado en el Diario Oficial de la Federacion"),  # fixture-sanitizer
    (".py", "# Promocion 2x1 del marketplace"),  # fixture-sanitizer
    (".py", "# Regla R1_separa_ciudad_amex"),  # fixture-sanitizer
    (".py", 'fecha = "2026-07-10"  # fecha del cargo'),  # fixture-sanitizer
    (".py", "class PagoController:\n    pass"),  # fixture-sanitizer
    (".md", "Uses an official SAT generic RFC."),  # fixture-sanitizer
    (".md", "The enterprise corporate ledger."),  # fixture-sanitizer
    (".md", "The decision-2026 memo and the marketing-2026 budget."),  # fixture-sanitizer
)

# Identificadores estructurados (reglas previas): (regla, contenido).
IDENTIFICADORES: Tuple[Tuple[str, str], ...] = (
    ("rfc", "# emisor ABCD991231XY9"),  # fixture-sanitizer
    ("rfc", "ABCD991231XY9 = 1"),  # fixture-sanitizer
    ("uuid", "# folio 3f2b9c1e-8a4d-4f7e-9b1a-2c3d4e5f6a7b"),  # fixture-sanitizer
    ("clabe", "# cuenta 012180001234567891"),  # fixture-sanitizer
    ("correo", "# contacto ana@empresa-real.mx"),  # fixture-sanitizer
    ("ruta_macos", "# ver /Users/alguien/proyecto/"),  # fixture-sanitizer
    ("ruta_linux", "# ver /home/alguien/proyecto/"),  # fixture-sanitizer
    ("llave_secreta", "clave = 'sk-ABCDEFGHIJKLMNOPQRSTUVWX'"),  # fixture-sanitizer
)

TEXTO_LIMPIO_PY = '''\
"""Cruce de cargos contra CFDIs dentro de una ventana de fechas asimetrica.

Cada cargo del universo de cargos se asigna a lo sumo a un CFDI. El tier
indica que evidencia coincide: monto exacto, monto con tolerancia o suma.
"""
from __future__ import annotations

from decimal import Decimal

TOLERANCIA = Decimal("0.50")  # tolerancia del tier 2, en pesos
RFC_GENERICO = "XAXX010101000"  # RFC generico: no sirve como evidencia
UUID_SINTETICO = "00000000-0000-0000-0000-000000000001"
CONTACTO = "soporte@example.com"
VENTANA_DIAS = (-5, 15)


def cruzar(cargo: dict, cfdis: list) -> dict:
    """Devuelve el cruce del cargo o un veredicto pendiente.

    Un candado detiene la corrida si el universo es parcial.
    """
    if not cfdis:
        raise ValueError(f"Sin CFDIs candidatos para el cargo {cargo['id']}")
    fecha = "2026-07-10"  # fecha del cargo en el ejemplo sintetico
    return {"cargo": cargo["id"], "tier": 1, "fecha": fecha}
'''

TEXTO_LIMPIO_MD = """\
# Cierre de marketplaces

La liquidacion neta ventas, comisiones, publicidad y retenciones. El devengo
reconoce la venta en el periodo en que ocurre; la cohorte cola se liquida en
el periodo siguiente. Los datos de `examples/` son sinteticos.
"""

EXCEPCION_VALIDA = {
    "reglas": ["seudonimo_empresa"],
    "ruta": "datos/*.py",
    "coincide": "entidad_demo",
    "justificacion": "Nombre de demostracion acordado para la prueba.",
}


def _escribir(directorio: str, nombre: str, contenido: str) -> str:
    ruta = os.path.join(directorio, nombre)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(contenido)
    return ruta


def _escribir_json(directorio: str, nombre: str, datos: object) -> str:
    return _escribir(directorio, nombre, json.dumps(datos, ensure_ascii=False))


def _escribir_xlsx(directorio: str, nombre: str, partes: Sequence[Tuple[str, str]]) -> str:
    ruta = os.path.join(directorio, nombre)
    with zipfile.ZipFile(ruta, "w") as zf:
        for miembro, contenido in partes:
            zf.writestr(miembro, contenido)
    return ruta


def _ids(alertas: Sequence[sa.Alerta]) -> Set[str]:
    return {a.regla for a in alertas}


def _correr_main(argv: List[str]) -> Tuple[int, str, str]:
    salida, errores = io.StringIO(), io.StringIO()
    codigo: Optional[int] = None
    with redirect_stdout(salida), redirect_stderr(errores):
        try:
            sa.main(argv)
        except SystemExit as exc:
            codigo = int(exc.code or 0)
    return (0 if codigo is None else codigo), salida.getvalue(), errores.getvalue()


class BaseTemporal(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def auditar(self, extension: str, contenido: str) -> List[sa.Alerta]:
        ruta = _escribir(self.tmp, "muestra" + extension, contenido + "\n")
        return sa.audit_file(ruta, REGLAS)


class TestHuellasNarrativas(BaseTemporal):
    def _modulo_con_huellas(self) -> str:
        cuerpo = "\n".join(linea for _, linea in HUELLAS_PLANTADAS)
        return f"def calcular_total(total):\n{cuerpo}\n    return total"

    def test_detecta_las_cinco_huellas_plantadas_de_tipos_distintos(self):
        alertas = self.auditar(".py", self._modulo_con_huellas())
        esperadas = {(i + 2, regla) for i, (regla, _) in enumerate(HUELLAS_PLANTADAS)}
        self.assertEqual({(a.linea, a.regla) for a in alertas}, esperadas)
        self.assertEqual(len(alertas), 5)
        self.assertEqual(len(_ids(alertas)), 5)

    def test_detecta_las_cinco_huellas_en_markdown(self):
        lineas = "\n".join(linea.strip() for _, linea in HUELLAS_PLANTADAS)
        alertas = self.auditar(".md", lineas)
        self.assertEqual(_ids(alertas), {regla for regla, _ in HUELLAS_PLANTADAS})
        self.assertEqual(len(alertas), 5)

    def test_cada_variante_se_marca_con_su_regla(self):
        for regla, extension, contenido in VARIANTES_POSITIVAS:
            with self.subTest(contenido=contenido):
                self.assertEqual(_ids(self.auditar(extension, contenido)), {regla})

    def test_texto_limpio_no_genera_falsos_positivos(self):
        self.assertEqual(self.auditar(".py", TEXTO_LIMPIO_PY), [])
        self.assertEqual(self.auditar(".md", TEXTO_LIMPIO_MD), [])

    def test_casos_frontera_no_se_marcan(self):
        for extension, contenido in CASOS_FRONTERA:
            with self.subTest(contenido=contenido):
                self.assertEqual(self.auditar(extension, contenido), [])

    def test_docstring_multilinea_reporta_la_linea_fisica_exacta(self):
        contenido = 'def f():\n    """Resumen.\n\n    Usa el reporte oficial.\n    """\n'  # fixture-sanitizer
        alertas = self.auditar(".py", contenido)
        self.assertEqual([(a.linea, a.regla) for a in alertas], [(4, "flujo_interno")])

    def test_una_alerta_por_regla_y_linea_aunque_coincidan_varios_patrones(self):
        alertas = self.auditar(".py", "# Ver hallazgo H1 en v4 R3")  # fixture-sanitizer
        self.assertEqual([(a.linea, a.regla) for a in alertas], [(1, "referencia_auditoria")])

    def test_python_que_no_tokeniza_se_revisa_por_linea_completa(self):
        alertas = self.auditar(".py", "H1 = (")  # fixture-sanitizer
        self.assertEqual(_ids(alertas), {"referencia_auditoria"})

    def test_reglas_narrativas_no_revisan_codigo_fuera_de_strings(self):
        alertas = self.auditar(".py", "promovido = oficial + 1")  # fixture-sanitizer
        self.assertEqual(alertas, [])


class TestIdentificadoresEstructurados(BaseTemporal):
    def test_cada_identificador_se_sigue_detectando(self):
        for regla, contenido in IDENTIFICADORES:
            with self.subTest(contenido=contenido):
                self.assertEqual(_ids(self.auditar(".py", contenido)), {regla})

    def test_marcadores_sinteticos_permitidos_no_se_marcan(self):
        contenido = "\n".join((
            "# RFC XAXX010101000 y XEXX010101000",
            "# UUID 00000000-0000-0000-0000-000000000042",
            "# correo ana@example.com y 123+bot@users.noreply.github.com",
            "# ruta /home/user/proyecto/",
        ))
        self.assertEqual(self.auditar(".py", contenido), [])

    def test_utf8_invalido_genera_alerta(self):
        ruta = os.path.join(self.tmp, "latin1.txt")
        with open(ruta, "wb") as f:
            f.write("Café".encode("latin-1"))
        self.assertEqual(_ids(sa.audit_file(ruta, REGLAS)), {"utf8"})

    def test_extension_binaria_se_omite(self):
        ruta = _escribir(self.tmp, "imagen.png", "ana@empresa-real.mx")  # fixture-sanitizer
        self.assertEqual(sa.audit_file(ruta, REGLAS), [])

    def test_archivo_ilegible_genera_alerta_en_vez_de_omitirse(self):
        ruta = os.path.join(self.tmp, "carpeta.txt")
        os.makedirs(ruta)
        self.assertEqual(_ids(sa.audit_file(ruta, REGLAS)), {"lectura"})


class TestXlsx(BaseTemporal):
    def test_revisa_textos_y_metadatos_sin_marcar_celdas_ni_formulas(self):
        ruta = _escribir_xlsx(self.tmp, "libro.xlsx", (
            ("xl/worksheets/sheet1.xml",
             '<worksheet><dimension ref="A1:H9"/><sheetData><row r="1">'
             '<c r="H1" t="s"><v>0</v></c><c r="I1"><f>SUM(H1, H2)</f></c>'  # fixture-sanitizer
             "</row></sheetData></worksheet>"),
            ("xl/sharedStrings.xml",
             "<sst><si><t>H1</t></si><si><t>jul-2026</t></si>"  # fixture-sanitizer
             "<si><t>Cargo de prueba</t></si><si><t>ana@empresa-real.mx</t></si></sst>"),  # fixture-sanitizer
            ("docProps/app.xml", "<Properties><Company>EnterpriseCorp</Company></Properties>"),  # fixture-sanitizer
            ("docProps/core.xml", "<cp><dc:creator>Financial Controller</dc:creator></cp>"),  # fixture-sanitizer
            ("xl/media/nota.bin", "EnterpriseCorp"),  # fixture-sanitizer
        ))
        alertas = sa.audit_file(ruta, REGLAS)
        obtenidas = {(a.regla, a.descripcion.split("]")[0] + "]") for a in alertas}
        self.assertEqual(obtenidas, {
            ("correo", "[xl/sharedStrings.xml]"),
            ("seudonimo_empresa", "[docProps/app.xml]"),
            ("aprobacion_cargo", "[docProps/core.xml]"),
        })

    def test_xlsx_corrupto_genera_alerta(self):
        ruta = _escribir(self.tmp, "roto.xlsx", "no es un zip")
        self.assertEqual(_ids(sa.audit_file(ruta, REGLAS)), {"xlsx"})


class TestExcepciones(BaseTemporal):
    def _cargar(self, entradas: object) -> Tuple[sa.Excepcion, ...]:
        ruta = _escribir_json(self.tmp, "excepciones.json", {"excepciones": entradas})
        return sa.cargar_excepciones(ruta, IDS_REGLAS)

    def test_carga_una_excepcion_valida(self):
        (exc,) = self._cargar([EXCEPCION_VALIDA])
        self.assertEqual(exc.reglas, ("seudonimo_empresa",))
        self.assertEqual(exc.ruta, "datos/*.py")
        self.assertEqual(exc.coincide, "entidad_demo")

    def test_rechaza_excepciones_invalidas(self):
        invalidas = (
            {**EXCEPCION_VALIDA, "justificacion": "   "},
            {k: v for k, v in EXCEPCION_VALIDA.items() if k != "justificacion"},
            {**EXCEPCION_VALIDA, "reglas": []},
            {**EXCEPCION_VALIDA, "reglas": ["regla_inexistente"]},
            {**EXCEPCION_VALIDA, "reglas": "seudonimo_empresa"},
            {**EXCEPCION_VALIDA, "ruta": ""},
            {**EXCEPCION_VALIDA, "coincide": "(sin cerrar"},
            {**EXCEPCION_VALIDA, "coincide": 7},
            "no es un objeto",
        )
        for entrada in invalidas:
            with self.subTest(entrada=entrada):
                with self.assertRaises(ValueError):
                    self._cargar([entrada])

    def test_rechaza_estructura_invalida_del_archivo(self):
        for datos in ([], {"excepciones": "x"}, {"otra_llave": []}):
            with self.subTest(datos=datos):
                ruta = _escribir_json(self.tmp, "estructura.json", datos)
                with self.assertRaises(ValueError):
                    sa.cargar_excepciones(ruta, IDS_REGLAS)

    def test_rechaza_json_mal_formado(self):
        ruta = _escribir(self.tmp, "roto.json", "{no es json")
        with self.assertRaises(ValueError):
            sa.cargar_excepciones(ruta, IDS_REGLAS)

    def test_excepcion_exime_solo_su_regla_su_ruta_y_sus_lineas(self):
        excepciones = self._cargar([EXCEPCION_VALIDA])
        contenido = "\n".join((
            'entidad_demo = "EnterpriseCorp"',  # fixture-sanitizer
            'otra = "EnterpriseCorp"',  # fixture-sanitizer
            "entidad_demo = 'autorizado por el CFO'",  # fixture-sanitizer
        ))
        ruta = _escribir(self.tmp, "datos/modulo.py", contenido)
        aplicables = sa.excepciones_para_ruta("datos/modulo.py", excepciones)
        alertas = sa.audit_file(ruta, REGLAS, aplicables)
        self.assertEqual(
            {(a.linea, a.regla) for a in alertas},
            {(2, "seudonimo_empresa"), (3, "aprobacion_cargo")},
        )
        self.assertEqual(sa.excepciones_para_ruta("otros/modulo.py", excepciones), ())

    def test_excepcion_sin_coincide_exime_todo_el_archivo_para_su_regla(self):
        entrada = {k: v for k, v in EXCEPCION_VALIDA.items() if k != "coincide"}
        excepciones = self._cargar([entrada])
        ruta = _escribir(self.tmp, "datos/modulo.py", 'x = "EnterpriseCorp"')  # fixture-sanitizer
        aplicables = sa.excepciones_para_ruta(os.path.join("datos", "modulo.py"), excepciones)
        self.assertEqual(sa.audit_file(ruta, REGLAS, aplicables), [])

    def test_lista_versionada_del_repo_es_valida_y_justificada(self):
        excepciones = sa.cargar_excepciones(sa.RUTA_EXCEPCIONES_DEFAULT, IDS_REGLAS)
        self.assertGreaterEqual(len(excepciones), 1)
        for exc in excepciones:
            self.assertGreaterEqual(len(exc.justificacion), sa.LARGO_MINIMO_JUSTIFICACION)

    def test_este_archivo_pasa_el_sanitizer_del_repo(self):
        excepciones = sa.cargar_excepciones(sa.RUTA_EXCEPCIONES_DEFAULT, IDS_REGLAS)
        aplicables = sa.excepciones_para_ruta(RUTA_ESTE_ARCHIVO, excepciones)
        self.assertEqual(sa.audit_file(__file__, REGLAS, aplicables), [])


class TestReglasPersonalizadas(BaseTemporal):
    def test_agrega_reglas_del_json_con_id_y_alcance(self):
        ruta = _escribir_json(self.tmp, "reglas.json", {
            "forbidden_patterns": [
                {"id": "proyecto_x", "pattern": "PROYECTO-X", "description": "Nombre clave"},
                {"pattern": "zeta", "description": "Sin id", "alcance": "texto"},
            ],
            "replacements": [{"pattern": "PROYECTO-X", "replacement": "PROYECTO"}],
        })
        reglas, reemplazos = sa.load_custom_rules(ruta)
        ids = {r.id for r in reglas}
        self.assertIn("proyecto_x", ids)
        self.assertIn("personalizada_2", ids)
        self.assertIn(("PROYECTO-X", "PROYECTO"), reemplazos)
        self.assertTrue(IDS_REGLAS <= ids)

    def test_rechaza_reglas_invalidas(self):
        invalidas = (
            {"forbidden_patterns": [{"pattern": "(sin cerrar", "description": "x"}]},
            {"forbidden_patterns": [{"description": "sin patron"}]},
            {"forbidden_patterns": [{"pattern": "x", "description": "y", "alcance": "otro"}]},
            {"replacements": [{"pattern": "x"}]},
            ["no es un objeto"],
        )
        for datos in invalidas:
            with self.subTest(datos=datos):
                ruta = _escribir_json(self.tmp, "reglas.json", datos)
                with self.assertRaises(ValueError):
                    sa.load_custom_rules(ruta)

    def test_ruta_de_reglas_inexistente_falla(self):
        with self.assertRaises(FileNotFoundError):
            sa.load_custom_rules(os.path.join(self.tmp, "no_existe.json"))


class TestSanitizar(BaseTemporal):
    def test_sanitize_text_reemplaza_rutas_y_uuids(self):
        texto = "ver /Users/alguien/x y 3f2b9c1e-8a4d-4f7e-9b1a-2c3d4e5f6a7b"  # fixture-sanitizer
        limpio = sa.sanitize_text(texto, _REEMPLAZOS)
        self.assertEqual(limpio, "ver ~/x y 00000000-0000-0000-0000-000000000000")

    def test_sanitize_file_escribe_destino_y_cuenta_alertas_restantes(self):
        origen = _escribir(self.tmp, "origen.md", "ver /Users/alguien/x\nemisor ABCD991231XY9\n")  # fixture-sanitizer
        destino = os.path.join(self.tmp, "salida", "limpio.md")
        restantes = sa.sanitize_file(origen, destino, REGLAS, _REEMPLAZOS)
        self.assertEqual(restantes, 1)
        with open(destino, encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("ver ~/x\n"))


class TestAuditDirectory(BaseTemporal):
    def _arbol(self) -> None:
        _escribir(self.tmp, "limpio.py", TEXTO_LIMPIO_PY)
        _escribir(self.tmp, "src/huellas.py", "# fix 2026-07-07\nx = 'reporte oficial'\n")  # fixture-sanitizer
        _escribir(self.tmp, ".git", "gitdir: /Users/alguien/repo/.git/worktrees/w\n")  # fixture-sanitizer
        _escribir(self.tmp, "sub/.git/config", "url = /Users/alguien/repo/\n")  # fixture-sanitizer
        _escribir(self.tmp, "__pycache__/x.txt", "EnterpriseCorp\n")  # fixture-sanitizer
        _escribir(self.tmp, ".DS_Store", "EnterpriseCorp\n")  # fixture-sanitizer
        _escribir(self.tmp, ".github/workflows/ci.yml", "# autorizado por el CFO\n")  # fixture-sanitizer

    def _auditar(self, **kwargs: object) -> Tuple[int, str]:
        salida = io.StringIO()
        with redirect_stdout(salida):
            total = sa.audit_directory(self.tmp, REGLAS, **kwargs)
        return total, salida.getvalue()

    def test_cuenta_alertas_omite_internos_y_resume_por_regla(self):
        self._arbol()
        total, salida = self._auditar()
        self.assertEqual(total, 3)
        self.assertIn("src/huellas.py", salida)
        self.assertIn(".github/workflows/ci.yml", salida)
        self.assertNotIn("__pycache__", salida)
        self.assertIn("fecha_bitacora: 1", salida)
        self.assertIn("flujo_interno: 1", salida)
        self.assertIn("aprobacion_cargo: 1", salida)

    def test_aplica_excepciones_por_ruta_relativa(self):
        self._arbol()
        ruta_exc = _escribir_json(self.tmp, "conf/excepciones.json", {"excepciones": [{
            "reglas": ["fecha_bitacora", "flujo_interno"],
            "ruta": "src/huellas.py",
            "justificacion": "Archivo de demostracion con huellas a proposito.",
        }]})
        excepciones = sa.cargar_excepciones(ruta_exc, IDS_REGLAS)
        total, _ = self._auditar(excepciones=excepciones, ruta_excepciones=ruta_exc)
        self.assertEqual(total, 1)

    def test_archivo_de_excepciones_solo_se_revisa_con_reglas_estructuradas(self):
        ruta_exc = _escribir_json(self.tmp, "excepciones.json", {"excepciones": [{
            "reglas": ["flujo_interno"],
            "ruta": "README.md",
            "coincide": "version oficial",  # fixture-sanitizer
            "justificacion": "Ejemplo: el README cita la regla para explicarla.",
        }]})
        _escribir(self.tmp, "README.md", "La version oficial del ejemplo.\n")  # fixture-sanitizer
        excepciones = sa.cargar_excepciones(ruta_exc, IDS_REGLAS)
        total, salida = self._auditar(excepciones=excepciones, ruta_excepciones=ruta_exc)
        self.assertEqual(total, 0, salida)
        _escribir(self.tmp, "excepciones.json", '{"excepciones": [], "x": "ana@empresa-real.mx"}')  # fixture-sanitizer
        total, _ = self._auditar(excepciones=excepciones, ruta_excepciones=ruta_exc)
        self.assertEqual(total, 1)

    def test_trunca_el_detalle_tras_cinco_alertas_por_archivo(self):
        _escribir(self.tmp, "muchas.md", "EnterpriseCorp\n" * 7)  # fixture-sanitizer
        total, salida = self._auditar()
        self.assertEqual(total, 7)
        self.assertEqual(salida.count("[seudonimo_empresa]"), 5)
        self.assertIn("2 alerta(s) más", salida)

    def test_omite_el_propio_sanitizer(self):
        propio = _escribir(self.tmp, "tools/sanitize_audit.py", "# EnterpriseCorp\n")  # fixture-sanitizer
        with mock.patch.object(sa, "RUTA_PROPIA", os.path.realpath(propio)):
            total, salida = self._auditar()
        self.assertEqual(total, 0)
        self.assertNotIn("sanitize_audit.py", salida)


class TestMain(BaseTemporal):
    def test_audit_directorio_con_y_sin_alertas(self):
        _escribir(self.tmp, "limpio/a.md", TEXTO_LIMPIO_MD)
        _escribir(self.tmp, "sucio/a.md", "Ver hallazgo H1\n")  # fixture-sanitizer
        self.assertEqual(_correr_main(["audit", os.path.join(self.tmp, "limpio")])[0], 0)
        self.assertEqual(_correr_main(["audit", os.path.join(self.tmp, "sucio")])[0], 1)

    def test_audit_archivo_con_y_sin_alertas(self):
        limpio = _escribir(self.tmp, "limpio.md", TEXTO_LIMPIO_MD)
        sucio = _escribir(self.tmp, "sucio.md", "entidad EnterpriseCorp\n")  # fixture-sanitizer
        self.assertEqual(_correr_main(["audit", limpio])[0], 0)
        codigo, salida, _ = _correr_main(["audit", sucio])
        self.assertEqual(codigo, 1)
        self.assertIn("seudonimo_empresa", salida)

    def test_audit_archivo_usa_excepciones_relativas_al_directorio_actual(self):
        directorio_previo = os.getcwd()
        self.addCleanup(os.chdir, directorio_previo)
        os.chdir(str(ROOT))
        self.assertEqual(_correr_main(["audit", RUTA_ESTE_ARCHIVO])[0], 0)

    def test_configuracion_invalida_sale_con_codigo_2(self):
        mala = _escribir_json(self.tmp, "mala.json", {"excepciones": [{"reglas": ["x"]}]})
        objetivo = _escribir(self.tmp, "a.md", TEXTO_LIMPIO_MD)
        faltante = os.path.join(self.tmp, "no_existe.json")
        for argv in (
            ["audit", objetivo, "--exceptions", mala],
            ["audit", objetivo, "--exceptions", faltante],
            ["audit", objetivo, "--rules", faltante],
        ):
            with self.subTest(argv=argv):
                codigo, _, errores = _correr_main(argv)
                self.assertEqual(codigo, 2)
                self.assertIn("configuración", errores)

    def test_reglas_personalizadas_desde_cli(self):
        reglas = _escribir_json(self.tmp, "reglas.json", {
            "forbidden_patterns": [{"id": "clave", "pattern": "PROYECTO-X", "description": "Nombre clave"}],
        })
        objetivo = _escribir(self.tmp, "a.md", "PROYECTO-X\n")
        codigo, salida, _ = _correr_main(["audit", objetivo, "--rules", reglas])
        self.assertEqual(codigo, 1)
        self.assertIn("Nombre clave", salida)

    def test_sanitize_requiere_output_y_reporta_restantes(self):
        origen = _escribir(self.tmp, "origen.md", "ver /Users/alguien/x\n")  # fixture-sanitizer
        self.assertEqual(_correr_main(["sanitize", origen])[0], 1)
        destino = os.path.join(self.tmp, "limpio.md")
        codigo, salida, _ = _correr_main(["sanitize", origen, "-o", destino])
        self.assertEqual(codigo, 0)
        self.assertIn(destino, salida)
        sucio = _escribir(self.tmp, "sucio.md", "emisor ABCD991231XY9\n")  # fixture-sanitizer
        codigo, salida, _ = _correr_main(["sanitize", sucio, "-o", destino])
        self.assertEqual(codigo, 0)
        self.assertIn("1 alerta", salida)

    def test_cli_de_punta_a_punta_por_subproceso(self):
        _escribir(self.tmp, "a.md", TEXTO_LIMPIO_MD)
        _escribir(self.tmp, "b.md", "aprobado por el Director\n")  # fixture-sanitizer
        resultado = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "sanitize_audit.py"), "audit", self.tmp],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(resultado.returncode, 1, resultado.stderr)
        self.assertIn("aprobacion_cargo: 1", resultado.stdout)


if __name__ == "__main__":
    unittest.main()
