#!/usr/bin/env python3
"""Pruebas de integración del universo de cargos.

Usan los insumos sintéticos de examples/synthetic como oráculo: el universo construido
desde los crudos debe ser idéntico, byte a byte, a `universo_cargos_esperado.jsonl`.
Cada prueba que altera insumos trabaja sobre una copia en una carpeta temporal.
Compatibles con `pytest` y con `python3 -m unittest`.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

RAIZ = Path(__file__).resolve().parents[1]
DIR_SKILL = RAIZ / "skills" / "credit-card-reconciliation"
if str(DIR_SKILL) not in sys.path:
    sys.path.insert(0, str(DIR_SKILL))

from conciliacion import universo as uv  # noqa: E402

DIR_SINTETICO = RAIZ / "examples" / "synthetic"
ESPERADO = DIR_SINTETICO / "universo_cargos_esperado.jsonl"
ARCHIVO_ALFA = "estado_cuenta_alfa.csv"
ARCHIVO_BETA = "estado_cuenta_beta.csv"
INSUMOS = ("resumen_estados_cuenta.json", ARCHIVO_ALFA, ARCHIVO_BETA)
BORRAR = object()  # marca para quitar un campo del resumen


def sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def copiar_insumos(destino: Path) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    for nombre in INSUMOS:
        shutil.copyfile(DIR_SINTETICO / nombre, destino / nombre)
    return destino


def editar_resumen(carpeta: Path, objetivo: str, /, **campos: object) -> None:
    """Cambia (o quita, con BORRAR) campos del estado cuyo emisor es `objetivo`."""
    ruta = carpeta / uv.NOMBRE_RESUMEN
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    nuevos = []
    for estado in datos["estados_cuenta"]:
        if estado["emisor"] == objetivo:
            estado = {**estado, **campos}
            estado = {k: v for k, v in estado.items() if v is not BORRAR}
        nuevos.append(estado)
    ruta.write_text(json.dumps({**datos, "estados_cuenta": nuevos}), encoding="utf-8")



def reescribir_lineas(carpeta: Path, archivo: str,
                      transformar: Callable[[List[str]], List[str]]) -> None:
    ruta = carpeta / archivo
    lineas = ruta.read_text(encoding="utf-8").split("\n")[:-1]
    ruta.write_text("\n".join(transformar(lineas)) + "\n", encoding="utf-8")


def correr_main(argv: Sequence[str]) -> Tuple[int, str, str]:
    salida, errores = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
        codigo = uv.main(list(argv))
    return codigo, salida.getvalue(), errores.getvalue()


def control_de(universo: "uv.Universo", emisor: str) -> Dict[str, bool]:
    control = next(c for c in universo.controles if c.emisor == emisor)
    return {comp.nombre: comp.cuadra for comp in control.comprobaciones}


class CarpetaTemporal(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.insumos = copiar_insumos(self.tmp / "crudos")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class AceptacionTest(unittest.TestCase):
    """Prueba de aceptación principal: el oráculo sintético."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.universo = uv.construir_universo(DIR_SINTETICO)

    def test_universo_identico_al_esperado(self) -> None:
        self.assertEqual(uv.serializar_universo(self.universo),
                         ESPERADO.read_text(encoding="utf-8"))

    def test_candados_cuadran(self) -> None:
        self.assertTrue(self.universo.cuadra)
        self.assertFalse(self.universo.es_provisional)
        uv.exigir_candados(self.universo)
        nombres = {"num_movimientos", "montos_legibles", "total_cargos", "total_abonos",
                   "total_neto", "saldo_al_corte"}
        for control in self.universo.controles:
            with self.subTest(emisor=control.emisor):
                self.assertEqual({c.nombre for c in control.comprobaciones}, nombres)
                self.assertTrue(all(c.cuadra for c in control.comprobaciones))

    def test_ambos_layouts_presentes(self) -> None:
        self.assertEqual({c.layout for c in self.universo.controles}, {"ALFA_V1", "BETA_V1"})

    def test_coincide_con_el_oraculo(self) -> None:
        oraculo = json.loads((DIR_SINTETICO / "oraculo.json").read_text(encoding="utf-8"))
        casos = {c["cargo_id"]: set(c["casos"]) for c in oraculo["cargos"]}
        por_id = {c.cargo_id: c for c in self.universo.cargos}
        self.assertEqual(set(por_id), set(casos))
        for cargo_id, etiquetas in casos.items():
            cargo = por_id[cargo_id]
            with self.subTest(cargo_id=cargo_id):
                self.assertEqual("fila_ininterpretable" in etiquetas,
                                 cargo.estado == "ininterpretable")
                self.assertEqual("pago_tarjeta" in etiquetas, cargo.tipo_movimiento == "pago")

    def test_filas_ininterpretables_marcadas_y_contadas(self) -> None:
        marcadas = [c for c in self.universo.cargos if c.estado == "ininterpretable"]
        self.assertEqual([c.cargo_id for c in marcadas], ["ALFA-0071", "BETA-0007"])
        self.assertTrue(all(c.motivo == "fecha_invalida" and c.fecha is None for c in marcadas))
        self.assertEqual(len(self.universo.cargos), 199)

    def test_dos_corridas_mismo_sha256(self) -> None:
        otra = uv.construir_universo(DIR_SINTETICO)
        self.assertEqual(sha256(uv.serializar_universo(self.universo)),
                         sha256(uv.serializar_universo(otra)))
        self.assertEqual(sha256(uv.serializar_control(self.universo)),
                         sha256(uv.serializar_control(otra)))

    def test_reporte_de_control(self) -> None:
        reporte = json.loads(uv.serializar_control(self.universo))
        self.assertEqual(reporte["esquema"], "control_universo/v1")
        self.assertIs(reporte["provisional"], False)
        self.assertIs(reporte["cuadra"], True)
        self.assertEqual(reporte["estados_omitidos"], [])
        self.assertEqual(reporte["num_cargos"], 199)
        self.assertEqual(reporte["filas_ininterpretables"], [
            {"cargo_id": "ALFA-0071", "motivo": "fecha_invalida"},
            {"cargo_id": "BETA-0007", "motivo": "fecha_invalida"},
        ])
        alfa = next(e for e in reporte["estados"] if e["emisor"] == "ALFA")
        neto = next(c for c in alfa["comprobaciones"] if c["nombre"] == "total_neto")
        self.assertEqual(neto, {"nombre": "total_neto", "esperado": "94460.23",
                                "calculado": "94460.23", "cuadra": True})

    def test_cargos_son_inmutables(self) -> None:
        with self.assertRaises(AttributeError):
            self.universo.cargos[0].monto = None  # type: ignore[misc]


class CandadosTest(CarpetaTemporal):
    def test_descuadre_de_un_centavo_en_el_neto(self) -> None:
        editar_resumen(self.insumos, "ALFA", total_neto="94460.24")
        universo = uv.construir_universo(self.insumos)
        self.assertFalse(universo.cuadra)
        self.assertEqual([n for n, ok in control_de(universo, "ALFA").items() if not ok],
                         ["total_neto"])
        self.assertTrue(all(control_de(universo, "BETA").values()))
        with self.assertRaises(uv.CandadoFallido) as ctx:
            uv.exigir_candados(universo)
        self.assertIn("total_neto", str(ctx.exception))

    def test_descuadre_de_conteo(self) -> None:
        editar_resumen(self.insumos, "BETA", num_movimientos=104)
        fallidas = [n for n, ok in control_de(uv.construir_universo(self.insumos), "BETA").items()
                    if not ok]
        self.assertEqual(fallidas, ["num_movimientos"])

    def test_descuadre_de_saldo(self) -> None:
        editar_resumen(self.insumos, "BETA", saldo_al_corte="0.00")
        fallidas = [n for n, ok in control_de(uv.construir_universo(self.insumos), "BETA").items()
                    if not ok]
        self.assertEqual(fallidas, ["saldo_al_corte"])

    def test_fila_eliminada_del_crudo_descuadra(self) -> None:
        reescribir_lineas(self.insumos, ARCHIVO_ALFA, lambda ls: ls[:5] + ls[6:])
        fallidas = {n for n, ok in control_de(uv.construir_universo(self.insumos), "ALFA").items()
                    if not ok}
        self.assertEqual(fallidas, {"num_movimientos", "total_cargos", "total_neto",
                                    "saldo_al_corte"})

    def test_importe_ilegible_se_marca_y_bloquea(self) -> None:
        reescribir_lineas(self.insumos, ARCHIVO_BETA,
                          lambda ls: ls[:2] + [ls[2].replace(",541.70,", ",541.7O,")] + ls[3:])
        universo = uv.construir_universo(self.insumos)
        cargo = next(c for c in universo.cargos if c.cargo_id == "BETA-0002")
        self.assertEqual((cargo.estado, cargo.motivo, cargo.monto),
                         ("ininterpretable", "monto_invalido", None))
        self.assertEqual(len([c for c in universo.cargos if c.emisor == "BETA"]), 105)
        fallidas = {n for n, ok in control_de(universo, "BETA").items() if not ok}
        self.assertIn("montos_legibles", fallidas)
        self.assertNotIn("num_movimientos", fallidas)

    def test_fila_en_blanco_no_se_descarta(self) -> None:
        reescribir_lineas(self.insumos, ARCHIVO_ALFA, lambda ls: ls + [""])
        universo = uv.construir_universo(self.insumos)
        ultima = [c for c in universo.cargos if c.emisor == "ALFA"][-1]
        self.assertEqual((ultima.cargo_id, ultima.motivo), ("ALFA-0095", "fila_vacia"))
        self.assertFalse(control_de(universo, "ALFA")["num_movimientos"])

    def test_columnas_incompletas_se_marcan(self) -> None:
        reescribir_lineas(self.insumos, ARCHIVO_BETA,
                          lambda ls: ls[:3] + [ls[3].rsplit(",", 1)[0]] + ls[4:])
        cargo = next(c for c in uv.construir_universo(self.insumos).cargos
                     if c.cargo_id == "BETA-0003")
        self.assertEqual((cargo.estado, cargo.motivo), ("ininterpretable", "columnas_incompletas"))


class EncabezadoTest(CarpetaTemporal):
    def test_encabezado_desconocido_detiene_la_corrida(self) -> None:
        reescribir_lineas(self.insumos, ARCHIVO_BETA,
                          lambda ls: [ls[0].replace("Post Date", "Posting Date")] + ls[1:])
        with self.assertRaises(uv.EncabezadoDesconocido) as ctx:
            uv.construir_universo(self.insumos)
        self.assertIn(ARCHIVO_BETA, str(ctx.exception))

    def test_layout_distinto_al_declarado(self) -> None:
        editar_resumen(self.insumos, "ALFA", layout="BETA_V1")
        with self.assertRaises(uv.ErrorInsumo) as ctx:
            uv.construir_universo(self.insumos)
        self.assertIn("ALFA_V1", str(ctx.exception))
        self.assertIn("BETA_V1", str(ctx.exception))

    def test_bom_utf8_se_tolera(self) -> None:
        ruta = self.insumos / ARCHIVO_ALFA
        ruta.write_bytes(b"\xef\xbb\xbf" + ruta.read_bytes())
        universo = uv.construir_universo(self.insumos)
        self.assertEqual(uv.serializar_universo(universo), ESPERADO.read_text(encoding="utf-8"))

    def test_archivo_vacio(self) -> None:
        (self.insumos / ARCHIVO_ALFA).write_bytes(b"")
        with self.assertRaises(uv.ErrorInsumo) as ctx:
            uv.construir_universo(self.insumos)
        self.assertIn(ARCHIVO_ALFA, str(ctx.exception))

    def test_archivo_no_utf8(self) -> None:
        ruta = self.insumos / ARCHIVO_ALFA
        ruta.write_bytes(ruta.read_text(encoding="utf-8").encode("latin-1"))
        with self.assertRaises(uv.ErrorInsumo) as ctx:
            uv.construir_universo(self.insumos)
        self.assertIn("UTF-8", str(ctx.exception))


class ResumenTest(CarpetaTemporal):
    def assert_rechaza(self, fragmento: str) -> None:
        with self.assertRaises(uv.ErrorInsumo) as ctx:
            uv.construir_universo(self.insumos)
        self.assertIn(fragmento, str(ctx.exception))

    def test_resumen_faltante(self) -> None:
        (self.insumos / uv.NOMBRE_RESUMEN).unlink()
        self.assert_rechaza(uv.NOMBRE_RESUMEN)

    def test_resumen_no_es_json(self) -> None:
        (self.insumos / uv.NOMBRE_RESUMEN).write_text("{no", encoding="utf-8")
        self.assert_rechaza(uv.NOMBRE_RESUMEN)

    def test_esquema_desconocido(self) -> None:
        (self.insumos / uv.NOMBRE_RESUMEN).write_text(
            json.dumps({"esquema": "otro/v9", "estados_cuenta": []}), encoding="utf-8")
        self.assert_rechaza("esquema")

    def test_sin_estados(self) -> None:
        (self.insumos / uv.NOMBRE_RESUMEN).write_text(
            json.dumps({"esquema": "resumen_estados_cuenta/v1", "estados_cuenta": []}),
            encoding="utf-8")
        self.assert_rechaza("estados_cuenta")

    def test_raiz_no_es_objeto(self) -> None:
        (self.insumos / uv.NOMBRE_RESUMEN).write_text("[]", encoding="utf-8")
        self.assert_rechaza("objeto")

    def test_campos_invalidos(self) -> None:
        casos = {
            "archivo_con_carpeta": ("archivo", "../estado_cuenta_alfa.csv"),
            "archivo_oculto": ("archivo", ".estado.csv"),
            "archivo_no_texto": ("archivo", 7),
            "emisor_minusculas": ("emisor", "alfa"),
            "emisor_con_guion": ("emisor", "AL-FA"),
            "monto_numero_json": ("total_neto", 94460.23),
            "monto_sin_centavos": ("total_cargos", "176673.4"),
            "conteo_booleano": ("num_movimientos", True),
            "conteo_negativo": ("num_movimientos", -1),
            "conteo_texto": ("num_movimientos", "94"),
            "fecha_no_iso": ("corte", "31/07/2026"),
            "fecha_imposible": ("periodo_inicio", "2026-02-30"),
            "periodo_invertido": ("periodo_inicio", "2026-08-01"),
            "layout_desconocido": ("layout", "GAMMA_V1"),
            "moneda_distinta_al_layout": ("moneda", "USD"),
            "campo_faltante": ("saldo_anterior", BORRAR),
        }
        for nombre, (campo, valor) in casos.items():
            with self.subTest(caso=nombre):
                copiar_insumos(self.insumos)
                editar_resumen(self.insumos, "ALFA", **{campo: valor})
                self.assert_rechaza(campo)

    def test_estado_no_es_objeto(self) -> None:
        ruta = self.insumos / uv.NOMBRE_RESUMEN
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        ruta.write_text(json.dumps({**datos, "estados_cuenta": ["x"]}), encoding="utf-8")
        self.assert_rechaza("objeto")

    def test_emisor_o_archivo_repetido(self) -> None:
        for campo, valor in (("emisor", "BETA"), ("archivo", ARCHIVO_BETA)):
            with self.subTest(campo=campo):
                copiar_insumos(self.insumos)
                editar_resumen(self.insumos, "ALFA", **{campo: valor})
                self.assert_rechaza("repetido")

    def test_estado_listado_sin_archivo(self) -> None:
        (self.insumos / ARCHIVO_BETA).unlink()
        self.assert_rechaza(ARCHIVO_BETA)

    def test_carpeta_inexistente(self) -> None:
        with self.assertRaises(uv.ErrorInsumo):
            uv.construir_universo(self.tmp / "no_existe")

    def test_resumen_que_es_carpeta(self) -> None:
        (self.insumos / uv.NOMBRE_RESUMEN).unlink()
        (self.insumos / uv.NOMBRE_RESUMEN).mkdir()
        self.assert_rechaza("no se pudo leer")

    def test_csv_con_campo_gigante_es_ilegible(self) -> None:
        reescribir_lineas(self.insumos, ARCHIVO_ALFA,
                          lambda ls: ls[:1] + ['"' + "X" * 300_000 + '"'] + ls[2:])
        self.assert_rechaza("CSV ilegible")


class UniversoParcialTest(CarpetaTemporal):
    def test_estado_declarado_ausente_marca_provisional(self) -> None:
        (self.insumos / ARCHIVO_BETA).unlink()
        universo = uv.construir_universo(self.insumos, omitidos=("BETA",))
        self.assertTrue(universo.es_provisional)
        self.assertTrue(universo.cuadra)
        self.assertEqual(universo.estados_omitidos, ("BETA",))
        self.assertEqual({c.emisor for c in universo.cargos}, {"ALFA"})
        esperadas = [linea for linea in ESPERADO.read_text(encoding="utf-8").splitlines(True)
                     if '"emisor": "ALFA"' in linea]
        self.assertEqual(uv.serializar_universo(universo), "".join(esperadas))
        reporte = json.loads(uv.serializar_control(universo))
        self.assertIs(reporte["provisional"], True)
        self.assertEqual(reporte["estados_omitidos"], ["BETA"])
        self.assertEqual([e["emisor"] for e in reporte["estados"]], ["ALFA"])

    def test_declarado_ausente_no_se_lee_aunque_exista(self) -> None:
        reescribir_lineas(self.insumos, ARCHIVO_ALFA, lambda ls: ["encabezado,raro"] + ls[1:])
        universo = uv.construir_universo(self.insumos, omitidos=["ALFA"])
        self.assertEqual({c.emisor for c in universo.cargos}, {"BETA"})

    def test_declaraciones_invalidas(self) -> None:
        for omitidos in (("GAMMA",), ("ALFA", "ALFA"), ("ALFA", "BETA"), ("",)):
            with self.subTest(omitidos=omitidos):
                with self.assertRaises(uv.ErrorInsumo):
                    uv.construir_universo(self.insumos, omitidos=omitidos)

    def test_omitidos_como_texto_se_rechaza(self) -> None:
        with self.assertRaises(uv.ErrorInsumo):
            uv.construir_universo(self.insumos, omitidos="BETA")

    def test_universo_completo_no_es_provisional(self) -> None:
        self.assertFalse(uv.construir_universo(self.insumos).es_provisional)


class DatosGrandesYEspecialesTest(CarpetaTemporal):
    def _resumen_unico(self, filas: int, neto: str) -> None:
        estado = {
            "archivo": ARCHIVO_ALFA, "emisor": "ALFA", "nombre_emisor": "BANCO DEMO",
            "layout": "ALFA_V1", "moneda": "MXN", "periodo_inicio": "2026-07-01",
            "periodo_fin": "2026-07-31", "corte": "2026-07-31", "num_movimientos": filas,
            "total_cargos": neto, "total_abonos": "0.00", "total_neto": neto,
            "saldo_anterior": "0.00", "saldo_al_corte": neto,
        }
        (self.insumos / uv.NOMBRE_RESUMEN).write_text(
            json.dumps({"esquema": "resumen_estados_cuenta/v1", "estados_cuenta": [estado]}),
            encoding="utf-8")

    def test_doce_mil_filas_en_orden_numerico(self) -> None:
        n = 12000
        encabezado = (DIR_SINTETICO / ARCHIVO_ALFA).read_text(encoding="utf-8").split("\n")[0]
        fila = '05/07/2026,06/07/2026,CAFE DEMO CDMX,ANA DEMO,****1001,MXN,"1,000.01",,"1,000.01"'
        (self.insumos / ARCHIVO_ALFA).write_text(
            "\n".join([encabezado] + [fila] * n) + "\n", encoding="utf-8")
        self._resumen_unico(n, "12000120.00")
        inicio = time.perf_counter()
        universo = uv.construir_universo(self.insumos)
        self.assertLess(time.perf_counter() - inicio, 20.0)
        self.assertTrue(universo.cuadra)
        ids = [c.cargo_id for c in universo.cargos]
        self.assertEqual(len(ids), n)
        self.assertEqual(ids[9998:10000], ["ALFA-9999", "ALFA-10000"])
        self.assertEqual(ids[-1], "ALFA-12000")

    def test_descripcion_con_unicode_comas_y_comillas(self) -> None:
        encabezado = (DIR_SINTETICO / ARCHIVO_ALFA).read_text(encoding="utf-8").split("\n")[0]
        fila = ('05/07/2026,06/07/2026,"CAFÉ ""EL, ÑANDÚ"" \U0001F600  \'; DROP",'
                'ANA DEMO,****1001,MXN,10.00,,10.00')
        (self.insumos / ARCHIVO_ALFA).write_text(encabezado + "\n" + fila + "\n",
                                                 encoding="utf-8")
        self._resumen_unico(1, "10.00")
        universo = uv.construir_universo(self.insumos)
        self.assertEqual(universo.cargos[0].descripcion, "CAFÉ \"EL, ÑANDÚ\" \U0001F600 '; DROP")
        linea = uv.serializar_universo(universo)
        self.assertIn("\U0001F600", linea)
        self.assertEqual(json.loads(linea)["descripcion"], universo.cargos[0].descripcion)


class CliEnProcesoTest(CarpetaTemporal):
    def test_exito_escribe_universo_y_control(self) -> None:
        salida = self.tmp / "out" / "universo.jsonl"
        codigo, stdout, _ = correr_main([str(self.insumos), "--salida", str(salida)])
        self.assertEqual(codigo, uv.SALIDA_OK)
        self.assertEqual(salida.read_bytes(), ESPERADO.read_bytes())
        control = json.loads((self.tmp / "out" / "universo.control.json")
                             .read_text(encoding="utf-8"))
        self.assertIs(control["provisional"], False)
        self.assertIn("CANDADO", stdout)

    def test_ruta_de_control_explicita(self) -> None:
        salida, control = self.tmp / "u.jsonl", self.tmp / "c" / "control.json"
        codigo, _, _ = correr_main([str(self.insumos), "--salida", str(salida),
                                    "--control", str(control)])
        self.assertEqual(codigo, uv.SALIDA_OK)
        self.assertEqual(control.read_text(encoding="utf-8"),
                         uv.serializar_control(uv.construir_universo(self.insumos)))

    def test_descuadre_sale_con_3_y_no_escribe(self) -> None:
        editar_resumen(self.insumos, "BETA", total_cargos="1.00")
        salida = self.tmp / "u.jsonl"
        codigo, stdout, stderr = correr_main([str(self.insumos), "--salida", str(salida)])
        self.assertEqual(codigo, uv.SALIDA_CANDADO)
        self.assertNotEqual(codigo, 0)
        self.assertFalse(salida.exists())
        self.assertFalse((self.tmp / "u.control.json").exists())
        self.assertIn("total_cargos", stdout + stderr)

    def test_encabezado_desconocido_sale_con_2(self) -> None:
        reescribir_lineas(self.insumos, ARCHIVO_ALFA, lambda ls: ["a,b,c"] + ls[1:])
        salida = self.tmp / "u.jsonl"
        codigo, _, stderr = correr_main([str(self.insumos), "--salida", str(salida)])
        self.assertEqual(codigo, uv.SALIDA_INSUMO)
        self.assertIn("encabezado", stderr.lower())
        self.assertFalse(salida.exists())

    def test_archivo_faltante_y_declaracion(self) -> None:
        (self.insumos / ARCHIVO_BETA).unlink()
        salida = self.tmp / "u.jsonl"
        codigo, _, stderr = correr_main([str(self.insumos), "--salida", str(salida)])
        self.assertEqual(codigo, uv.SALIDA_INSUMO)
        self.assertIn(ARCHIVO_BETA, stderr)
        codigo, stdout, _ = correr_main([str(self.insumos), "--salida", str(salida),
                                         "--sin-estado", "BETA"])
        self.assertEqual(codigo, uv.SALIDA_OK)
        self.assertIn("PROVISIONAL", stdout)
        control = json.loads((self.tmp / "u.control.json").read_text(encoding="utf-8"))
        self.assertIs(control["provisional"], True)

    def test_salida_con_extension_distinta(self) -> None:
        salida = self.tmp / "universo.txt"
        codigo, _, _ = correr_main([str(self.insumos), "--salida", str(salida)])
        self.assertEqual(codigo, uv.SALIDA_OK)
        self.assertTrue((self.tmp / "universo.txt.control.json").exists())

    def test_salida_y_control_iguales_se_rechaza(self) -> None:
        salida = self.tmp / "u.jsonl"
        codigo, _, stderr = correr_main([str(self.insumos), "--salida", str(salida),
                                         "--control", str(salida)])
        self.assertEqual(codigo, uv.SALIDA_INSUMO)
        self.assertIn("--control", stderr)

    def test_salida_no_escribible_sale_con_2(self) -> None:
        bloqueo = self.tmp / "soy_archivo"
        bloqueo.write_text("x", encoding="utf-8")
        codigo, _, stderr = correr_main([str(self.insumos), "--salida",
                                         str(bloqueo / "u.jsonl")])
        self.assertEqual(codigo, uv.SALIDA_INSUMO)
        self.assertIn("no se pudo escribir", stderr)

    def test_argumentos_invalidos_salen_con_2(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(correr_main([str(self.insumos)])[0], uv.SALIDA_INSUMO)


class CliSubprocesoTest(unittest.TestCase):
    """El punto de entrada `python3 -m conciliacion.universo` con cwd en la skill."""

    def correr(self, *args: str) -> "subprocess.CompletedProcess[str]":
        return subprocess.run(
            [sys.executable, "-m", "conciliacion.universo", *args],
            cwd=str(DIR_SKILL), capture_output=True, text=True, check=False)

    def test_dos_corridas_identicas_al_esperado(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hashes = []
            for n in (1, 2):
                salida = Path(tmp) / f"universo_{n}.jsonl"
                proceso = self.correr(str(DIR_SINTETICO), "--salida", str(salida))
                self.assertEqual(proceso.returncode, 0, proceso.stderr)
                self.assertEqual(salida.read_bytes(), ESPERADO.read_bytes())
                hashes.append(hashlib.sha256(salida.read_bytes()).hexdigest())
            self.assertEqual(hashes[0], hashes[1])

    def test_ruta_relativa_desde_la_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            salida = Path(tmp) / "u.jsonl"
            proceso = self.correr("../../examples/synthetic", "--salida", str(salida))
            self.assertEqual(proceso.returncode, 0, proceso.stderr)
            self.assertEqual(salida.read_bytes(), ESPERADO.read_bytes())

    def test_descuadre_codigo_distinto_de_cero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            insumos = copiar_insumos(Path(tmp) / "crudos")
            editar_resumen(insumos, "ALFA", total_neto="0.00")
            proceso = self.correr(str(insumos), "--salida", str(Path(tmp) / "u.jsonl"))
            self.assertEqual(proceso.returncode, 3)


if __name__ == "__main__":
    unittest.main()
