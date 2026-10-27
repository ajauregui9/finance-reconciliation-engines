#!/usr/bin/env python3
"""Pruebas del generador sintético determinista.

Compatibles con `pytest` y con `python3 -m unittest`. Las pruebas leen los
archivos escritos (el contrato público), no el estado interno del generador.
"""
from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for rel in ("examples", "tools"):
    p = str(ROOT / rel)
    if p not in sys.path:
        sys.path.insert(0, p)

import generador_sintetico as gs  # noqa: E402
from generador_sintetico import afinidad  # noqa: E402
from generador_sintetico.contexto import Contexto  # noqa: E402
import sanitize_audit  # noqa: E402

CENTAVO = Decimal("0.01")
GENERICOS = {"XAXX010101000", "XEXX010101000"}
DIR_VERSIONADO = ROOT / "examples" / "synthetic"

ENCABEZADO_ALFA_V1 = [
    "Fecha de operación", "Fecha de aplicación", "Descripción", "Titular", "Tarjeta",
    "Moneda origen", "Importe origen", "Tipo de cambio", "Importe MXN",
]
ENCABEZADO_BETA_V1 = [
    "Transaction Date", "Post Date", "Description", "Card Member", "Account Ending",
    "Foreign Spend Amount", "Foreign Currency", "Exchange Rate", "Charges", "Credits",
]
ARCHIVOS_GENERADOS = {
    "estado_cuenta_alfa.csv", "estado_cuenta_beta.csv", "resumen_estados_cuenta.json",
    "universo_cargos_esperado.jsonl", "cfdis.jsonl", "libro_mayor.csv", "oraculo.json",
    "veredictos_libro.csv",
}
ENCABEZADO_VEREDICTOS = ["cargo_id", "veredicto", "asiento_id", "nota"]
TIPOS_CONFLICTO = {"asiento_distinto", "motor_sin_cruce", "motor_con_cruce"}
CASOS_MINIMOS = {
    "normal": 80, "monto_tolerancia": 3, "fuera_de_tolerancia": 2, "suma_2": 3, "suma_3": 2,
    "suma_con_distractor": 2, "nota_credito_neta": 2, "nota_credito_reembolso": 2,
    "reembolso_total": 1, "empate_grupo": 6, "empate_monto_fechas_distintas": 2,
    "empate_monto_fecha_comercios_distintos": 2, "ventana_borde_inferior": 1,
    "ventana_borde_superior": 1, "fuera_ventana_inferior": 1, "fuera_ventana_superior": 1,
    "rfc_generico_receptor_unico": 1, "rfc_generico_receptor_duplicado": 1,
    "rfc_generico_emisor_suma": 1, "nomina_distractor": 2, "usd_sin_cfdi": 3,
    "usd_moneda_original": 2, "sin_cfdi": 5, "fila_ininterpretable": 2, "pago_tarjeta": 2,
    "libro_registrado": 80, "libro_cubeta": 4, "libro_cubeta_fecha_lejana": 2,
    "libro_no_registrado": 20, "libro_descartado_por_nombre": 2, "libro_nomina_distractor": 2,
}
MONTO_TXT = re.compile(r"^-?\d+\.\d{2}$")
CASOS_AFINIDAD = ("afinidad_emisor_ajeno", "afinidad_suma_emisor_ajeno", "empate_monto_afinidad",
                  "afinidad_descriptor_agregador")
PALABRA = re.compile(r"[A-Z0-9]+")


# ---------------------------------------------------------------- utilidades
def _sha256_dir(carpeta: Path) -> dict:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(carpeta.iterdir())}


def _jsonl(ruta: Path) -> list:
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines()]


def _csv(ruta: Path) -> tuple:
    with ruta.open(encoding="utf-8", newline="") as f:
        filas = list(csv.reader(f))
    return filas[0], filas[1:]


def _dec(txt: str) -> Decimal:
    return Decimal(txt.replace(",", ""))


def _fecha_alfa(txt: str):
    try:
        d, m, a = txt.split("/")
        return date(int(a), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _fecha_beta(txt: str):
    try:
        m, d, a = txt.split("/")
        return date(int(a), int(m), int(d)).isoformat()
    except ValueError:
        return None


def _tipo(monto: Decimal, descripcion: str, marca_pago: str) -> str:
    if monto > 0:
        return "cargo"
    return "pago" if descripcion.startswith(marca_pago) else "abono"


def _parsear_alfa(celdas: list) -> dict:
    monto = _dec(celdas[8])
    descripcion = " ".join(celdas[2].split())
    fecha = _fecha_alfa(celdas[0])
    return {
        "fecha": fecha, "fecha_aplicacion": _fecha_alfa(celdas[1]), "descripcion": descripcion,
        "titular": celdas[3], "tarjeta_ultimos4": celdas[4][-4:], "moneda_original": celdas[5],
        "monto_original": _dec(celdas[6]), "tipo_cambio": celdas[7] or None, "monto": monto,
        "tipo_movimiento": _tipo(monto, descripcion, "PAGO RECIBIDO"),
        "estado": "ok" if fecha else "ininterpretable",
    }


def _parsear_beta(celdas: list) -> dict:
    monto = _dec(celdas[8]) if celdas[8] else -_dec(celdas[9])
    signo = 1 if monto > 0 else -1
    descripcion = " ".join(celdas[2].split())
    fecha = _fecha_beta(celdas[0])
    extranjera = bool(celdas[6])
    return {
        "fecha": fecha, "fecha_aplicacion": _fecha_beta(celdas[1]), "descripcion": descripcion,
        "titular": celdas[3], "tarjeta_ultimos4": celdas[4],
        "moneda_original": celdas[6] if extranjera else "MXN",
        "monto_original": signo * _dec(celdas[5]) if extranjera else monto,
        "tipo_cambio": celdas[7] or None, "monto": monto,
        "tipo_movimiento": _tipo(monto, descripcion, "PAYMENT RECEIVED"),
        "estado": "ok" if fecha else "ininterpretable",
    }


def _delta(cfdi: dict, cargo: dict) -> int:
    return (date.fromisoformat(cfdi["fecha_emision"]) - date.fromisoformat(cargo["fecha"])).days


def _valor_firmado(cfdi: dict) -> Decimal:
    total = Decimal(cfdi["total_mxn"])
    return -total if cfdi["tipo_comprobante"] == "E" else total


def _iniciales(texto: str) -> set:
    """Iniciales de las palabras de 3+ caracteres que no son solo dígitos (la afinidad exige inicial común)."""
    return {p[0] for p in PALABRA.findall(texto.upper()) if len(p) >= 3 and not p.isdigit()}


def _recorrer(valor):
    if isinstance(valor, dict):
        for v in valor.values():
            yield from _recorrer(v)
    elif isinstance(valor, list):
        for v in valor:
            yield from _recorrer(v)
    else:
        yield valor


class _ConSalida(unittest.TestCase):
    """Genera una vez la salida por defecto (solo lectura en las pruebas)."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls._tmp.name)
        cls.datos = gs.generar(gs.ConfigGenerador())
        gs.escribir_salida(cls.datos, cls.dir)
        cls.universo = {c["cargo_id"]: c for c in _jsonl(cls.dir / "universo_cargos_esperado.jsonl")}
        cls.cfdis = {c["uuid"]: c for c in _jsonl(cls.dir / "cfdis.jsonl")}
        cls.oraculo = json.loads((cls.dir / "oraculo.json").read_text(encoding="utf-8"))
        cls.por_cargo = {o["cargo_id"]: o for o in cls.oraculo["cargos"]}
        with (cls.dir / "libro_mayor.csv").open(encoding="utf-8", newline="") as f:
            cls.lineas = list(csv.DictReader(f))
        asientos = defaultdict(list)
        for linea in cls.lineas:
            asientos[linea["asiento_id"]].append(linea)
        cls.asientos = dict(asientos)
        cls.resumen = json.loads((cls.dir / "resumen_estados_cuenta.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _con_caso(self, caso: str) -> list:
        return [o for o in self.oraculo["cargos"] if caso in o["casos"]]

    def _linea_tarjeta(self, asiento_id: str) -> dict:
        lineas = [x for x in self.asientos[asiento_id] if x["cuenta"].startswith("2105-")]
        self.assertEqual(len(lineas), 1, asiento_id)
        return lineas[0]


# ------------------------------------------------------------- determinismo
class TestDeterminismo(unittest.TestCase):
    def test_dos_corridas_misma_semilla_dan_sha256_identico(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            gs.escribir_salida(gs.generar(gs.ConfigGenerador()), Path(a))
            gs.escribir_salida(gs.generar(gs.ConfigGenerador()), Path(b))
            sha_a, sha_b = _sha256_dir(Path(a)), _sha256_dir(Path(b))
        self.assertEqual(set(sha_a), ARCHIVOS_GENERADOS)
        self.assertEqual(sha_a, sha_b)

    def test_semilla_distinta_cambia_la_salida(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            gs.escribir_salida(gs.generar(gs.ConfigGenerador()), Path(a))
            gs.escribir_salida(gs.generar(gs.ConfigGenerador(semilla=7)), Path(b))
            self.assertNotEqual(_sha256_dir(Path(a))["cfdis.jsonl"], _sha256_dir(Path(b))["cfdis.jsonl"])

    def test_otras_semillas_tambien_generan_datos_validos(self):
        for semilla in (1, 2, 3):
            with self.subTest(semilla=semilla):
                self.assertEqual(gs.verificar(gs.generar(gs.ConfigGenerador(semilla=semilla))), ())

    def test_salida_versionada_coincide_con_una_regeneracion(self):
        with tempfile.TemporaryDirectory() as tmp:
            gs.escribir_salida(gs.generar(gs.ConfigGenerador()), Path(tmp))
            nuevo = _sha256_dir(Path(tmp))
        versionado = {k: v for k, v in _sha256_dir(DIR_VERSIONADO).items() if k in ARCHIVOS_GENERADOS}
        self.assertEqual(versionado, nuevo, "Regenera con: python3 examples/generate.py")


# ------------------------------------------------------------- configuración
class TestConfig(unittest.TestCase):
    def test_ventana_debe_contener_el_dia_del_cargo(self):
        with self.assertRaises(ValueError):
            gs.ConfigGenerador(ventana_min=1, ventana_max=15)
        with self.assertRaises(ValueError):
            gs.ConfigGenerador(ventana_min=-5, ventana_max=-1)

    def test_tolerancia_debe_ser_decimal_positiva(self):
        with self.assertRaises(ValueError):
            gs.ConfigGenerador(tolerancia_monto=Decimal("0.00"))
        with self.assertRaises(TypeError):
            gs.ConfigGenerador(tolerancia_monto=1.0)

    def test_semilla_debe_ser_entero_no_negativo(self):
        with self.assertRaises(ValueError):
            gs.ConfigGenerador(semilla=-1)


# ----------------------------------------------------- estado de cuenta crudo
class TestEstadoCuentaCrudo(_ConSalida):
    def test_dos_emisores_con_layouts_de_encabezado_distintos(self):
        enc_alfa, _ = _csv(self.dir / "estado_cuenta_alfa.csv")
        enc_beta, _ = _csv(self.dir / "estado_cuenta_beta.csv")
        self.assertEqual(enc_alfa, ENCABEZADO_ALFA_V1)
        self.assertEqual(enc_beta, ENCABEZADO_BETA_V1)
        emisores = {e["emisor"]: e["layout"] for e in self.resumen["estados_cuenta"]}
        self.assertEqual(emisores, {"ALFA": "ALFA_V1", "BETA": "BETA_V1"})

    def test_universo_esperado_se_deriva_fila_por_fila_del_crudo(self):
        for archivo, parser in (("estado_cuenta_alfa.csv", _parsear_alfa),
                                ("estado_cuenta_beta.csv", _parsear_beta)):
            _, filas = _csv(self.dir / archivo)
            esperados = sorted((c for c in self.universo.values() if c["archivo"] == archivo),
                               key=lambda c: c["fila"])
            self.assertEqual(len(filas), len(esperados), archivo)
            for n, (celdas, esp) in enumerate(zip(filas, esperados), 1):
                with self.subTest(archivo=archivo, fila=n):
                    self.assertEqual(esp["fila"], n)
                    self.assertEqual(esp["cargo_id"], f"{esp['emisor']}-{n:04d}")
                    for campo, valor in parser(celdas).items():
                        crudo = esp[campo]
                        if isinstance(valor, Decimal):
                            crudo = Decimal(crudo)
                        self.assertEqual(crudo, valor, campo)

    def test_resumen_cuadra_al_centavo_con_el_universo(self):
        for edc in self.resumen["estados_cuenta"]:
            with self.subTest(emisor=edc["emisor"]):
                filas = [c for c in self.universo.values() if c["emisor"] == edc["emisor"]]
                montos = [Decimal(c["monto"]) for c in filas]
                self.assertEqual(edc["num_movimientos"], len(filas))
                self.assertEqual(Decimal(edc["total_neto"]), sum(montos))
                self.assertEqual(Decimal(edc["total_cargos"]), sum(m for m in montos if m > 0))
                self.assertEqual(Decimal(edc["total_abonos"]), sum(m for m in montos if m < 0))
                self.assertEqual(Decimal(edc["saldo_al_corte"]),
                                 Decimal(edc["saldo_anterior"]) + Decimal(edc["total_neto"]))
                self.assertTrue(all(c["corte"] == edc["corte"] for c in filas))

    def test_filas_ininterpretables_se_conservan_con_motivo(self):
        malas = [c for c in self.universo.values() if c["estado"] == "ininterpretable"]
        self.assertEqual({c["emisor"] for c in malas}, {"ALFA", "BETA"})
        for c in malas:
            self.assertIsNone(c["fecha"])
            self.assertEqual(c["motivo"], "fecha_invalida")
            self.assertTrue(MONTO_TXT.match(c["monto"]))
        self.assertTrue(all(c["motivo"] is None for c in self.universo.values() if c["estado"] == "ok"))

    def test_cargos_en_usd_traen_tipo_de_cambio_y_monto_en_pesos(self):
        usd = [c for c in self.universo.values() if c["moneda_original"] == "USD"]
        self.assertGreaterEqual(len(usd), 5)
        for c in usd:
            esperado = (Decimal(c["monto_original"]) * Decimal(c["tipo_cambio"])).quantize(
                CENTAVO, rounding=ROUND_HALF_UP)
            self.assertEqual(Decimal(c["monto"]), esperado, c["cargo_id"])
            self.assertEqual(c["moneda"], "MXN")


# ------------------------------------------------------ volumen y casos borde
class TestVolumenYCasosBorde(_ConSalida):
    def test_volumen_aproximado_de_cargos_y_cfdis(self):
        self.assertTrue(190 <= len(self.universo) <= 215, len(self.universo))
        self.assertTrue(235 <= len(self.cfdis) <= 265, len(self.cfdis))

    def test_cubre_cada_caso_borde_del_catalogo(self):
        conteo = Counter(caso for o in self.oraculo["cargos"] for caso in o["casos"])
        for caso, minimo in CASOS_MINIMOS.items():
            with self.subTest(caso=caso):
                self.assertGreaterEqual(conteo[caso], minimo)
        self.assertEqual(self.oraculo["resumen"]["casos"], dict(sorted(conteo.items())))

    def test_oraculo_cubre_cada_cargo_y_referencia_ids_existentes(self):
        self.assertEqual(set(self.por_cargo), set(self.universo))
        for o in self.oraculo["cargos"]:
            for uuid in o["cfdi"]["esperados"] + o["cfdi"]["prohibidos"]:
                self.assertIn(uuid, self.cfdis)
            for asiento in o["libro_mayor"]["prohibidos"] + [o["libro_mayor"]["esperado"]]:
                if asiento is not None:
                    self.assertIn(asiento, self.asientos)

    def test_asignacion_esperada_es_exclusiva(self):
        uuids = [u for o in self.oraculo["cargos"] for u in o["cfdi"]["esperados"]]
        asientos = [o["libro_mayor"]["esperado"] for o in self.oraculo["cargos"]
                    if o["libro_mayor"]["esperado"]]
        self.assertEqual(len(uuids), len(set(uuids)))
        self.assertEqual(len(asientos), len(set(asientos)))

    def test_sin_cruce_siempre_trae_motivo_y_con_cruce_nunca(self):
        for o in self.oraculo["cargos"]:
            with self.subTest(cargo=o["cargo_id"]):
                self.assertEqual(not o["cfdi"]["esperados"], o["cfdi"]["motivo_sin_cruce"] is not None)
                self.assertEqual(not o["cfdi"]["esperados"], o["cfdi"]["evidencia"] is None)
                lm = o["libro_mayor"]
                self.assertEqual(lm["esperado"] is None, lm["motivo_sin_cruce"] is not None)

    def test_evidencia_esperada_es_coherente_con_los_datos(self):
        ventana = self.oraculo["parametros"]["ventana_dias"]
        tol = Decimal(self.oraculo["parametros"]["tolerancia_monto"])
        for o in self.oraculo["cargos"]:
            cfdis = [self.cfdis[u] for u in o["cfdi"]["esperados"]]
            if not cfdis:
                continue
            cargo = self.universo[o["cargo_id"]]
            monto = Decimal(cargo["monto"])
            with self.subTest(cargo=o["cargo_id"], evidencia=o["cfdi"]["evidencia"]):
                for c in cfdis:
                    self.assertTrue(ventana["min"] <= _delta(c, cargo) <= ventana["max"])
                    self.assertEqual(c["direccion"], "recibido")
                    self.assertNotIn(c["rfc_receptor"], GENERICOS)
                evidencia = o["cfdi"]["evidencia"]
                diferencia = abs(sum(_valor_firmado(c) for c in cfdis) - monto)
                if evidencia == "monto_exacto":
                    self.assertEqual((len(cfdis), diferencia), (1, Decimal("0")))
                elif evidencia == "monto_tolerancia":
                    self.assertEqual(len(cfdis), 1)
                    self.assertTrue(Decimal("0") < diferencia <= tol)
                elif evidencia == "suma":
                    self.assertIn(len(cfdis), (2, 3))
                    self.assertEqual(len({c["rfc_emisor"] for c in cfdis}), 1)
                    self.assertEqual(diferencia, Decimal("0"))
                elif evidencia == "moneda_original":
                    self.assertEqual(cfdis[0]["moneda"], "USD")
                    self.assertEqual(Decimal(cfdis[0]["total"]), Decimal(cargo["monto_original"]))
                    self.assertGreater(diferencia, tol)
                elif evidencia == "monto_sin_afinidad":
                    self.assertIn(len(cfdis), (1, 2, 3))
                    self.assertEqual(len({c["rfc_emisor"] for c in cfdis}), 1)
                    self.assertLessEqual(diferencia, tol)
                else:
                    self.fail(f"evidencia desconocida: {evidencia}")

    def test_empates_forman_grupos_intercambiables(self):
        grupos = self.oraculo["grupos_empate"]
        self.assertGreaterEqual(len(grupos), 3)
        self.assertTrue(any(len(g["cargos"]) == 3 for g in grupos))
        for g in grupos:
            with self.subTest(grupo=g["grupo"]):
                cargos = [self.universo[c] for c in g["cargos"]]
                cfdis = [self.cfdis[u] for u in g["cfdis"]]
                self.assertEqual(len(cargos), len(cfdis))
                self.assertEqual(len(cargos), len(g["asientos"]))
                self.assertEqual(len({(c["monto"], c["fecha"], c["descripcion"]) for c in cargos}), 1)
                self.assertEqual(len({(c["total"], c["fecha_emision"], c["rfc_emisor"]) for c in cfdis}), 1)
                for cid in g["cargos"]:
                    self.assertEqual(self.por_cargo[cid]["grupo_empate"], g["grupo"])
                    self.assertIn(self.por_cargo[cid]["cfdi"]["esperados"][0], g["cfdis"])

    def test_casos_de_ventana_caen_exactamente_en_los_bordes(self):
        ventana = self.oraculo["parametros"]["ventana_dias"]
        casos = {
            "ventana_borde_inferior": ("esperados", ventana["min"]),
            "ventana_borde_superior": ("esperados", ventana["max"]),
            "fuera_ventana_inferior": ("prohibidos", ventana["min"] - 1),
            "fuera_ventana_superior": ("prohibidos", ventana["max"] + 1),
        }
        for caso, (lista, delta) in casos.items():
            for o in self._con_caso(caso):
                with self.subTest(caso=caso, cargo=o["cargo_id"]):
                    cfdi = self.cfdis[o["cfdi"][lista][0]]
                    self.assertEqual(_delta(cfdi, self.universo[o["cargo_id"]]), delta)
                    if lista == "prohibidos":
                        self.assertEqual(o["cfdi"]["motivo_sin_cruce"], "fuera_de_ventana")

    def test_ventana_es_un_parametro_del_generador(self):
        datos = gs.generar(gs.ConfigGenerador(ventana_min=-3, ventana_max=10))
        self.assertEqual(gs.verificar(datos), ())
        with tempfile.TemporaryDirectory() as tmp:
            gs.escribir_salida(datos, Path(tmp))
            oraculo = json.loads((Path(tmp) / "oraculo.json").read_text(encoding="utf-8"))
            universo = {c["cargo_id"]: c for c in _jsonl(Path(tmp) / "universo_cargos_esperado.jsonl")}
            cfdis = {c["uuid"]: c for c in _jsonl(Path(tmp) / "cfdis.jsonl")}
        self.assertEqual(oraculo["parametros"]["ventana_dias"], {"min": -3, "max": 10})
        fuera = [o for o in oraculo["cargos"] if "fuera_ventana_superior" in o["casos"]]
        self.assertTrue(fuera)
        for o in fuera:
            self.assertEqual(_delta(cfdis[o["cfdi"]["prohibidos"][0]], universo[o["cargo_id"]]), 11)

    def test_notas_de_credito_netas_y_reembolsos(self):
        for o in self._con_caso("nota_credito_neta"):
            cfdis = sorted((self.cfdis[u] for u in o["cfdi"]["esperados"]),
                           key=lambda c: c["tipo_comprobante"])
            self.assertEqual([c["tipo_comprobante"] for c in cfdis], ["E", "I"])
            self.assertEqual(cfdis[0]["uuid_relacionado"], cfdis[1]["uuid"])
        for o in self._con_caso("nota_credito_reembolso"):
            cargo = self.universo[o["cargo_id"]]
            self.assertEqual(cargo["tipo_movimiento"], "abono")
            (uuid,) = o["cfdi"]["esperados"]
            self.assertEqual(self.cfdis[uuid]["tipo_comprobante"], "E")
            self.assertIsNotNone(self.cfdis[uuid]["uuid_relacionado"])
        for o in self._con_caso("reembolso_total"):
            nota = self.cfdis[o["cfdi"]["esperados"][0]]
            original = self.cfdis[nota["uuid_relacionado"]]
            self.assertEqual(nota["total"], original["total"])

    def test_oraculo_publica_la_banda_de_casi_cruces_fuera_de_tolerancia(self):
        banda = self.oraculo["parametros"]["banda_fuera_de_tolerancia"]
        self.assertEqual(banda, {"min": "2.50", "max": "4.50"})
        minimo, maximo = Decimal(banda["min"]), Decimal(banda["max"])
        tol = Decimal(self.oraculo["parametros"]["tolerancia_monto"])
        self.assertGreater(minimo, tol)
        casos = self._con_caso("fuera_de_tolerancia")
        self.assertTrue(casos)
        for o in casos:
            (uuid,) = o["cfdi"]["prohibidos"]
            diferencia = abs(_valor_firmado(self.cfdis[uuid]) - Decimal(self.universo[o["cargo_id"]]["monto"]))
            self.assertTrue(minimo <= diferencia <= maximo, (o["cargo_id"], diferencia))

    def test_banda_fuera_de_tolerancia_sigue_a_la_tolerancia(self):
        datos = gs.generar(gs.ConfigGenerador(tolerancia_monto=Decimal("2.00")))
        with tempfile.TemporaryDirectory() as tmp:
            gs.escribir_salida(datos, Path(tmp))
            oraculo = json.loads((Path(tmp) / "oraculo.json").read_text(encoding="utf-8"))
        self.assertEqual(oraculo["parametros"]["banda_fuera_de_tolerancia"], {"min": "4.50", "max": "6.50"})

    def test_rfc_generico_no_cuenta_como_evidencia(self):
        for caso in ("rfc_generico_receptor_unico", "rfc_generico_receptor_duplicado"):
            for o in self._con_caso(caso):
                señuelo = self.cfdis[o["cfdi"]["prohibidos"][0]]
                self.assertEqual(señuelo["rfc_receptor"], "XAXX010101000")
                monto = Decimal(self.universo[o["cargo_id"]]["monto"])
                self.assertEqual(Decimal(señuelo["total_mxn"]), monto)
                if caso.endswith("unico"):
                    self.assertEqual(o["cfdi"]["motivo_sin_cruce"], "solo_rfc_generico")
                else:
                    (valido,) = o["cfdi"]["esperados"]
                    self.assertEqual(self.cfdis[valido]["rfc_emisor"], señuelo["rfc_emisor"])
        for o in self._con_caso("rfc_generico_emisor_suma"):
            par = [self.cfdis[u] for u in o["cfdi"]["prohibidos"]]
            self.assertEqual({c["rfc_emisor"] for c in par}, {"XEXX010101000"})
            self.assertEqual(len({c["nombre_emisor"] for c in par}), 2)
            monto = Decimal(self.universo[o["cargo_id"]]["monto"])
            self.assertEqual(sum(Decimal(c["total_mxn"]) for c in par), monto)
            self.assertEqual(o["cfdi"]["motivo_sin_cruce"], "solo_rfc_generico")

    def test_nomina_nunca_respalda_cargos(self):
        esperados = {u for o in self.oraculo["cargos"] for u in o["cfdi"]["esperados"]}
        nomina = {u for u, c in self.cfdis.items() if c["tipo_comprobante"] == "N"}
        self.assertGreaterEqual(len(nomina), 10)
        self.assertFalse(esperados & nomina)
        for o in self._con_caso("nomina_distractor"):
            (uuid,) = o["cfdi"]["prohibidos"]
            self.assertEqual(self.cfdis[uuid]["tipo_comprobante"], "N")
            self.assertEqual(self.cfdis[uuid]["direccion"], "emitido")
            monto = Decimal(self.universo[o["cargo_id"]]["monto"])
            self.assertEqual(Decimal(self.cfdis[uuid]["total"]), monto)
        for o in self._con_caso("libro_nomina_distractor"):
            (asiento,) = o["libro_mayor"]["prohibidos"]
            self.assertEqual({x["origen"] for x in self.asientos[asiento]}, {"NOMINA"})

    def test_proveedor_cubeta_exige_monto_y_fecha(self):
        cubeta = self.oraculo["parametros"]["proveedor_cubeta"]["id"]
        for o in self._con_caso("libro_cubeta"):
            linea = self._linea_tarjeta(o["libro_mayor"]["esperado"])
            self.assertEqual(linea["proveedor_id"], cubeta)
            self.assertTrue(o["libro_mayor"]["riesgo_cubeta"])
        for o in self._con_caso("libro_cubeta_fecha_lejana"):
            cargo = self.universo[o["cargo_id"]]
            linea = self._linea_tarjeta(o["libro_mayor"]["prohibidos"][0])
            self.assertEqual(linea["proveedor_id"], cubeta)
            self.assertEqual(Decimal(linea["haber"]), Decimal(cargo["monto"]))
            dias = (date.fromisoformat(linea["fecha"]) - date.fromisoformat(cargo["fecha"])).days
            self.assertGreaterEqual(abs(dias), 20)
            self.assertEqual(o["libro_mayor"]["motivo_sin_cruce"], "cubeta_evidencia_insuficiente")
        self.assertFalse(any(o["libro_mayor"]["riesgo_cubeta"] for o in self.oraculo["cargos"]
                             if "libro_cubeta" not in o["casos"]))

    def test_descartado_por_nombre_tiene_candidato_de_otro_proveedor(self):
        cubeta = self.oraculo["parametros"]["proveedor_cubeta"]["id"]
        for o in self._con_caso("libro_descartado_por_nombre"):
            cargo = self.universo[o["cargo_id"]]
            linea = self._linea_tarjeta(o["libro_mayor"]["prohibidos"][0])
            self.assertEqual(Decimal(linea["haber"]), Decimal(cargo["monto"]))
            self.assertNotEqual(linea["proveedor_id"], cubeta)
            self.assertEqual(o["libro_mayor"]["motivo_sin_cruce"], "descartado_por_nombre")

    def test_registro_esperado_en_libro_coincide_en_monto_y_cuenta_de_la_tarjeta(self):
        cuentas = self.oraculo["parametros"]["cuentas_tarjeta"]
        for o in self.oraculo["cargos"]:
            asiento = o["libro_mayor"]["esperado"]
            if asiento is None:
                continue
            cargo = self.universo[o["cargo_id"]]
            linea = self._linea_tarjeta(asiento)
            lado = "haber" if cargo["tipo_movimiento"] == "cargo" else "debe"
            with self.subTest(cargo=o["cargo_id"]):
                self.assertEqual(linea["cuenta"], cuentas[cargo["emisor"]])
                self.assertEqual(Decimal(linea[lado]), abs(Decimal(cargo["monto"])))

    def test_autoverificacion_no_encuentra_violaciones(self):
        self.assertEqual(gs.verificar(self.datos), ())

    def test_autoverificacion_detecta_un_candidato_accidental(self):
        normal = self._con_caso("normal")[0]
        original = next(c for c in self.datos.cfdis if c.uuid == normal["cfdi"]["esperados"][0])
        clon = dataclasses.replace(original, uuid="SINTFFFF-FFFF-4FFF-8FFF-FFFFFFFFFFFF")
        corrupto = dataclasses.replace(self.datos, cfdis=self.datos.cfdis + (clon,))
        violaciones = gs.verificar(corrupto)
        self.assertTrue(any(normal["cargo_id"] in v for v in violaciones), violaciones)


# ------------------------------------------------ veredictos humanos
def _conflicto_esperado(veredicto: dict, esperado) -> object:
    """Tabla de la spec del cruce con libro mayor: veredicto contra la propuesta correcta."""
    if veredicto["veredicto"] == "registrado":
        if esperado is None:
            return "motor_sin_cruce"
        return None if esperado == veredicto["asiento_id"] else "asiento_distinto"
    return "motor_con_cruce" if esperado is not None else None


class TestVeredictosHumanos(_ConSalida):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        encabezado, filas = _csv(cls.dir / "veredictos_libro.csv")
        cls.encabezado_veredictos = encabezado
        cls.veredictos = [dict(zip(encabezado, f)) for f in filas]

    def test_archivo_con_encabezado_fijo_y_filas_ordenadas(self):
        self.assertEqual(self.encabezado_veredictos, ENCABEZADO_VEREDICTOS)
        ids = [v["cargo_id"] for v in self.veredictos]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)), "un veredicto por cargo")
        self.assertGreaterEqual(len(ids), 8)

    def test_cada_veredicto_es_valido_contra_universo_y_libro(self):
        citados = []
        for v in self.veredictos:
            with self.subTest(cargo=v["cargo_id"]):
                self.assertIn(v["cargo_id"], self.universo)
                self.assertIn(v["veredicto"], ("registrado", "no_registrado"))
                self.assertEqual(v["veredicto"] == "registrado", bool(v["asiento_id"]))
                if v["asiento_id"]:
                    self.assertIn(v["asiento_id"], self.asientos)
                    citados.append(v["asiento_id"])
                self.assertTrue(v["nota"])
        self.assertEqual(len(citados), len(set(citados)), "dos veredictos no citan el mismo asiento")

    def test_oraculo_trae_veredicto_y_conflicto_de_cada_cargo(self):
        por_cargo = {v["cargo_id"]: v for v in self.veredictos}
        for o in self.oraculo["cargos"]:
            lm = o["libro_mayor"]
            with self.subTest(cargo=o["cargo_id"]):
                self.assertIn("veredicto", lm)
                self.assertIn("conflicto", lm)
                v = por_cargo.get(o["cargo_id"])
                if v is None:
                    self.assertIsNone(lm["veredicto"])
                    self.assertIsNone(lm["conflicto"])
                    continue
                self.assertEqual(lm["veredicto"], {"veredicto": v["veredicto"], "asiento_id": v["asiento_id"] or None})
                self.assertEqual(lm["conflicto"], _conflicto_esperado(v, lm["esperado"]))

    def test_hay_conflictos_plantados_de_cada_tipo_y_tambien_acuerdos(self):
        conflictos = Counter(o["libro_mayor"]["conflicto"] for o in self.oraculo["cargos"]
                             if o["libro_mayor"]["veredicto"] is not None)
        for tipo in TIPOS_CONFLICTO:
            self.assertGreaterEqual(conflictos[tipo], 1, tipo)
        self.assertGreaterEqual(conflictos[None], 3, "también hay veredictos que coinciden")
        resumen = self.oraculo["veredictos_libro"]
        self.assertEqual(resumen["archivo"], "veredictos_libro.csv")
        self.assertEqual(resumen["filas"], len(self.veredictos))
        self.assertEqual(resumen["conflictos"], {k: n for k, n in conflictos.items() if k is not None})
        self.assertEqual(resumen["sin_conflicto"], conflictos[None])

    def test_ningun_veredicto_desplaza_el_registro_esperado_de_otro_cargo(self):
        esperado_de = {o["libro_mayor"]["esperado"]: o["cargo_id"] for o in self.oraculo["cargos"]
                       if o["libro_mayor"]["esperado"]}
        for v in self.veredictos:
            dueno = esperado_de.get(v["asiento_id"])
            self.assertIn(dueno, (None, v["cargo_id"]), v)

    def test_veredictos_no_tocan_grupos_de_empate(self):
        en_grupo = {c for g in self.oraculo["grupos_empate"] for c in g["cargos"]}
        self.assertFalse(en_grupo & {v["cargo_id"] for v in self.veredictos})

    def test_otras_semillas_tambien_plantan_veredictos_validos(self):
        for semilla in (1, 2, 3):
            with self.subTest(semilla=semilla):
                datos = gs.generar(gs.ConfigGenerador(semilla=semilla))
                self.assertTrue(datos.veredictos)
                self.assertEqual(gs.verificar(datos), ())

    def test_autoverificacion_detecta_veredicto_incoherente(self):
        primero = self.datos.veredictos[0]
        roto = dataclasses.replace(primero, conflicto="asiento_distinto" if primero.conflicto is None else None)
        corrupto = dataclasses.replace(self.datos, veredictos=(roto,) + self.datos.veredictos[1:])
        self.assertTrue(any(primero.cargo_id in v for v in gs.verificar(corrupto)))

    def test_autoverificacion_detecta_asiento_citado_dos_veces(self):
        con_asiento = [v for v in self.datos.veredictos if v.asiento_id]
        clon = dataclasses.replace(con_asiento[1], asiento_id=con_asiento[0].asiento_id)
        resto = tuple(v for v in self.datos.veredictos if v is not con_asiento[1])
        corrupto = dataclasses.replace(self.datos, veredictos=resto + (clon,))
        self.assertTrue(any("citado" in v for v in gs.verificar(corrupto)))


# --------------------------------------------------- dinero y datos ficticios
class TestDineroYDatosFicticios(_ConSalida):
    CAMPOS_MONTO_CFDI = ("subtotal", "iva", "total", "total_mxn")

    def test_todo_monto_es_texto_decimal_con_dos_decimales(self):
        for c in self.universo.values():
            for campo in ("monto", "monto_original"):
                self.assertTrue(MONTO_TXT.match(c[campo]), (c["cargo_id"], campo))
        for c in self.cfdis.values():
            for campo in self.CAMPOS_MONTO_CFDI:
                self.assertTrue(MONTO_TXT.match(c[campo]), (c["uuid"], campo))
        for linea in self.lineas:
            self.assertTrue(MONTO_TXT.match(linea["debe"]) and MONTO_TXT.match(linea["haber"]))
        documentos = [self.oraculo, self.resumen, *self.universo.values(), *self.cfdis.values()]
        self.assertFalse([v for d in documentos for v in _recorrer(d) if isinstance(v, float)])

    def test_cada_asiento_cuadra_debe_contra_haber(self):
        for asiento, lineas in self.asientos.items():
            debe = sum(Decimal(x["debe"]) for x in lineas)
            haber = sum(Decimal(x["haber"]) for x in lineas)
            self.assertEqual(debe, haber, asiento)

    def test_cfdis_subtotal_mas_iva_es_total(self):
        for c in self.cfdis.values():
            self.assertEqual(Decimal(c["subtotal"]) + Decimal(c["iva"]), Decimal(c["total"]), c["uuid"])

    def test_rfcs_y_uuids_son_ficticios(self):
        rfcs = {c[k] for c in self.cfdis.values() for k in ("rfc_emisor", "rfc_receptor")}
        rfcs |= {x["proveedor_rfc"] for x in self.lineas if x["proveedor_rfc"]}
        self.assertTrue(all(r in GENERICOS or r.startswith("RFC_") for r in rfcs), rfcs)
        # El último grupo empieza con dígito: así nunca tiene forma de RFC.
        patron = re.compile(r"^SINT[0-9A-F]{4}-[0-9A-F]{4}-4[0-9A-F]{3}-[89AB][0-9A-F]{3}-[0-9][0-9A-F]{11}$")
        self.assertTrue(all(patron.match(u) for u in self.cfdis))

    def test_sanitizer_pasa_limpio_en_toda_la_salida(self):
        reglas, _ = sanitize_audit.load_custom_rules(None)
        for ruta in sorted(self.dir.iterdir()):
            with self.subTest(archivo=ruta.name):
                self.assertEqual(list(sanitize_audit.audit_file(str(ruta), reglas)), [])

    def test_sanitizer_pasa_limpio_con_otras_semillas(self):
        reglas, _ = sanitize_audit.load_custom_rules(None)
        for semilla in (1, 2, 3):
            with tempfile.TemporaryDirectory() as tmp:
                rutas = gs.escribir_salida(gs.generar(gs.ConfigGenerador(semilla=semilla)), Path(tmp))
                alertas = [(r.name, a) for r in rutas for a in sanitize_audit.audit_file(str(r), reglas)]
            self.assertEqual(alertas, [], semilla)


# ------------------------------------------------ afinidad de nombre
class TestAfinidadSembrada(_ConSalida):
    """Casos donde solo coincide el monto: el cruce queda por revisar y el emisor ajeno nunca respalda."""

    def _ajeno(self, cargo_id: str, uuid: str) -> bool:
        return not _iniciales(self.universo[cargo_id]["descripcion"]) & _iniciales(self.cfdis[uuid]["nombre_emisor"])

    def test_siembra_un_caso_de_cada_tipo(self):
        for caso in CASOS_AFINIDAD:
            with self.subTest(caso=caso):
                self.assertEqual(len(self._con_caso(caso)), 1)

    def test_monto_exacto_de_un_emisor_ajeno(self):
        (o,) = self._con_caso("afinidad_emisor_ajeno")
        cargo, (uuid,) = self.universo[o["cargo_id"]], o["cfdi"]["esperados"]
        self.assertEqual((o["cfdi"]["evidencia"], o["cfdi"]["prohibidos"]), ("monto_sin_afinidad", []))
        self.assertEqual(Decimal(self.cfdis[uuid]["total_mxn"]), Decimal(cargo["monto"]))
        self.assertTrue(self._ajeno(o["cargo_id"], uuid))
        self.assertNotIn("sin_cfdi", o["casos"])

    def test_suma_de_un_emisor_ajeno(self):
        (o,) = self._con_caso("afinidad_suma_emisor_ajeno")
        cfdis = [self.cfdis[u] for u in o["cfdi"]["esperados"]]
        self.assertEqual((o["cfdi"]["evidencia"], len(cfdis)), ("monto_sin_afinidad", 2))
        self.assertEqual(len({c["rfc_emisor"] for c in cfdis}), 1)
        self.assertEqual(sum(_valor_firmado(c) for c in cfdis), Decimal(self.universo[o["cargo_id"]]["monto"]))
        self.assertTrue(all(self._ajeno(o["cargo_id"], c["uuid"]) for c in cfdis))

    def test_empate_de_monto_gana_el_cfdi_del_comercio(self):
        (o,) = self._con_caso("empate_monto_afinidad")
        cargo = self.universo[o["cargo_id"]]
        (propio,), (ajeno,) = o["cfdi"]["esperados"], o["cfdi"]["prohibidos"]
        self.assertEqual(o["cfdi"]["evidencia"], "monto_exacto")
        self.assertEqual(self.cfdis[propio]["total_mxn"], self.cfdis[ajeno]["total_mxn"])
        self.assertEqual(_delta(self.cfdis[ajeno], cargo), 0)
        self.assertGreater(abs(_delta(self.cfdis[propio], cargo)), 0)
        self.assertTrue(self._ajeno(o["cargo_id"], ajeno))
        self.assertFalse(self._ajeno(o["cargo_id"], propio))

    def test_descriptor_de_pasarela_que_no_nombra_al_comercio(self):
        (o,) = self._con_caso("afinidad_descriptor_agregador")
        (uuid,) = o["cfdi"]["esperados"]
        self.assertTrue(self.universo[o["cargo_id"]]["descripcion"].startswith("PGDEMO *PEDIDO "))
        self.assertEqual(o["cfdi"]["evidencia"], "monto_sin_afinidad")
        self.assertTrue(self._ajeno(o["cargo_id"], uuid))
        self.assertIsNone(o["libro_mayor"]["esperado"])

    def test_no_toca_veredictos_inyecciones_ni_empates(self):
        sembrados = {o["cargo_id"] for caso in CASOS_AFINIDAD for o in self._con_caso(caso)}
        self.assertEqual(len(sembrados), len(CASOS_AFINIDAD))
        self.assertFalse(sembrados & {v.cargo_id for v in self.datos.veredictos})
        self.assertFalse(sembrados & {s.cargo_id for s in self.datos.inyecciones})
        self.assertTrue(all(self.por_cargo[c]["grupo_empate"] is None for c in sembrados))

    def test_los_cfdis_nuevos_continuan_el_folio_de_su_serie(self):
        series = Counter((c["rfc_emisor"], c["nombre_emisor"], c["serie"], c["folio"]) for c in self.cfdis.values())
        self.assertEqual([k for k, n in series.items() if n > 1], [])

    def test_autoverificacion_detecta_un_emisor_que_si_se_parece(self):
        (o,) = self._con_caso("afinidad_emisor_ajeno")
        (uuid,) = o["cfdi"]["esperados"]
        inicial = self.universo[o["cargo_id"]]["descripcion"][0]
        cfdis = tuple(dataclasses.replace(c, nombre_emisor=f"{inicial}XYZ DEMO SA DE CV") if c.uuid == uuid else c
                      for c in self.datos.cfdis)
        violaciones = gs.verificar(dataclasses.replace(self.datos, cfdis=cfdis))
        self.assertTrue(any(o["cargo_id"] in v and "afinidad" in v for v in violaciones), violaciones)

    def test_autoverificacion_detecta_una_suma_ajena_accidental(self):
        (o,) = self._con_caso("afinidad_emisor_ajeno")
        (uuid,) = o["cfdi"]["esperados"]
        original = next(c for c in self.datos.cfdis if c.uuid == uuid)
        mitad = (original.total_mxn / 2).quantize(CENTAVO)
        partes = tuple(dataclasses.replace(original, uuid=f"SINTEEEE-EEEE-4EEE-8EEE-{n}EEEEEEEEEEE", total=m,
                                           total_mxn=m) for n, m in ((1, mitad), (2, original.total_mxn - mitad)))
        violaciones = gs.verificar(dataclasses.replace(self.datos, cfdis=self.datos.cfdis + partes))
        self.assertTrue(any(o["cargo_id"] in v and "suma no prevista" in v for v in violaciones), violaciones)


class TestAfinidadBordes(unittest.TestCase):
    def test_iniciales_ignoran_palabras_cortas_y_numeros(self):
        self.assertEqual(afinidad.iniciales("PGDEMO *PEDIDO 4471 WEB"), {"P", "W"})
        self.assertTrue(afinidad.nombres_ajenos("TIENDITA LA ESQUINA GDL", "FLORERIA JARDIN DEMO SA DE CV"))
        self.assertFalse(afinidad.nombres_ajenos("CAFE LUNA AZUL CDMX", "CAFETERIA LUNA AZUL SA DE CV"))

    def test_sin_cargos_elegibles_no_siembra_y_lo_dice(self):
        datos = gs.generar(gs.ConfigGenerador())
        with self.assertRaisesRegex(RuntimeError, "sin cargos elegibles"):
            afinidad.sembrar_afinidad(datos.config, 0, datos.cargos, datos.cfdis, (), (), ())

    def test_una_descripcion_con_todas_las_iniciales_no_tiene_comercio_ajeno(self):
        todas = " ".join(letra * 3 for letra in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        with self.assertRaisesRegex(RuntimeError, "ningún comercio"):
            afinidad._comercio_ajeno(Contexto(gs.ConfigGenerador(), 0), todas)


# ---------------------------------------------------------------------- CLI
class TestCLI(unittest.TestCase):
    SCRIPT = ROOT / "examples" / "generate.py"

    def test_cli_genera_en_el_directorio_indicado(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = subprocess.run([sys.executable, str(self.SCRIPT), "--salida", tmp],
                                 capture_output=True, text=True, check=False)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual({p.name for p in Path(tmp).iterdir()}, ARCHIVOS_GENERADOS)
            self.assertIn("cargos", res.stdout)

    def test_cli_rechaza_ventana_invalida_con_codigo_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = subprocess.run([sys.executable, str(self.SCRIPT), "--salida", tmp,
                                  "--ventana-min", "3"], capture_output=True, text=True, check=False)
        self.assertEqual(res.returncode, 2)
        self.assertIn("ventana", res.stderr.lower())


if __name__ == "__main__":
    unittest.main()
