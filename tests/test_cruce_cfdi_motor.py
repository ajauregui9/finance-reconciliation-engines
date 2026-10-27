"""Pruebas unitarias del motor de cruce cargo ↔ CFDI (tiers, ventana, sumas, empates)."""
from __future__ import annotations

import dataclasses
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "credit-card-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from conciliacion.cruce_cfdi_config import ConfigCruce  # noqa: E402
from conciliacion.cruce_cfdi_modelo import Cargo, Cfdi, ResultadoCargo, ResultadoCruce  # noqa: E402
from conciliacion.cruce_cfdi_motor import cruzar  # noqa: E402

EMPRESA = "RFC_EMPRESA_DEMO"
PUBLICO = "XAXX010101000"
EXTRANJERO = "XEXX010101000"
DIA_CERO = date(2026, 7, 10)
CAFE = "CAFE LUNA AZUL CDMX"
RAZON_CAFE = "CAFETERIA LUNA AZUL SA DE CV"
CONFIG = ConfigCruce()


def cargo(
    cid: str = "ALFA-0001",
    monto: str = "100.00",
    dia: int = 0,
    desc: str = CAFE,
    tipo: Optional[str] = None,
    estado: str = "ok",
    moneda_original: str = "MXN",
    monto_original: Optional[str] = None,
) -> Cargo:
    valor = Decimal(monto)
    return Cargo(
        cargo_id=cid,
        fecha=DIA_CERO + timedelta(days=dia) if estado == "ok" else None,
        descripcion=desc,
        monto=valor,
        moneda_original=moneda_original,
        monto_original=Decimal(monto_original) if monto_original else valor,
        tipo_movimiento=tipo or ("cargo" if valor > 0 else "abono"),
        estado=estado,
    )


def cfdi(
    uuid: str,
    total: str = "100.00",
    dia: int = 0,
    tipo: str = "I",
    rfc: str = "RFC_COM_01",
    nombre: str = RAZON_CAFE,
    receptor: str = EMPRESA,
    direccion: str = "recibido",
    moneda: str = "MXN",
    total_mxn: Optional[str] = None,
) -> Cfdi:
    return Cfdi(
        uuid=uuid,
        fecha_emision=DIA_CERO + timedelta(days=dia),
        tipo_comprobante=tipo,
        direccion=direccion,
        rfc_emisor=rfc,
        nombre_emisor=nombre,
        rfc_receptor=receptor,
        moneda=moneda,
        total=Decimal(total),
        total_mxn=Decimal(total_mxn) if total_mxn else Decimal(total),
    )


def uno(resultado: ResultadoCruce, cid: str = "ALFA-0001") -> ResultadoCargo:
    return resultado.buscar(cid)


class TestTiersUnoAUno:
    def test_monto_exacto(self) -> None:
        r = uno(cruzar([cargo()], [cfdi("U-1", dia=1)], CONFIG))
        assert (r.cfdis, r.evidencia, r.motivo) == (("U-1",), "monto_exacto", None)
        assert r.diferencia == Decimal("0.00") and r.moneda_diferencia == "MXN"
        assert r.deltas == (1,)

    def test_monto_con_tolerancia(self) -> None:
        r = uno(cruzar([cargo()], [cfdi("U-1", total="100.40")], CONFIG))
        assert (r.cfdis, r.evidencia) == (("U-1",), "monto_tolerancia")
        assert r.diferencia == Decimal("0.40")

    def test_tolerancia_incluye_el_borde(self) -> None:
        r = uno(cruzar([cargo()], [cfdi("U-1", total="99.00")], CONFIG))
        assert r.evidencia == "monto_tolerancia"

    def test_un_centavo_fuera_de_tolerancia_se_diagnostica(self) -> None:
        r = uno(cruzar([cargo()], [cfdi("U-1", total="101.01")], CONFIG))
        assert (r.cfdis, r.evidencia, r.motivo) == ((), None, "fuera_de_tolerancia")
        assert [(d.uuid, d.motivo) for d in r.descartados] == [("U-1", "fuera_de_tolerancia")]

    def test_mas_alla_de_la_banda_de_diagnostico_no_hay_candidato(self) -> None:
        r = uno(cruzar([cargo()], [cfdi("U-1", total="105.01")], CONFIG))
        assert (r.motivo, r.descartados) == ("sin_candidato", ())

    def test_fuera_de_tolerancia_exige_afinidad_de_nombre(self) -> None:
        ajeno = cfdi("U-1", total="103.00", rfc="RFC_COM_09", nombre="HOTEL PLAZA CENTRAL SA DE CV")
        assert uno(cruzar([cargo()], [ajeno], CONFIG)).motivo == "sin_candidato"

    def test_moneda_original(self) -> None:
        c = cargo(monto="1900.00", moneda_original="USD", monto_original="100.00", desc="HOTEL PLAYA DEMO QROO")
        f = cfdi("U-1", total="100.00", total_mxn="1870.00", moneda="USD", nombre="HOTEL PLAYA DEMO SA DE CV")
        r = uno(cruzar([c], [f], CONFIG))
        assert (r.cfdis, r.evidencia) == (("U-1",), "moneda_original")
        assert (r.diferencia, r.moneda_diferencia) == (Decimal("0.00"), "USD")

    def test_exacto_en_pesos_gana_la_etiqueta_sobre_moneda_original(self) -> None:
        c = cargo(monto="1900.00", moneda_original="USD", monto_original="100.00")
        f = cfdi("U-1", total="100.00", total_mxn="1900.00", moneda="USD")
        assert uno(cruzar([c], [f], CONFIG)).evidencia == "monto_exacto"

    def test_cfdi_en_pesos_no_se_compara_en_moneda_original(self) -> None:
        c = cargo(monto="1900.00", moneda_original="USD", monto_original="100.00")
        r = uno(cruzar([c], [cfdi("U-1", total="100.00")], CONFIG))
        assert (r.evidencia, r.motivo) == (None, "sin_candidato")

    def test_exacto_gana_sobre_tolerancia_y_deja_libre_al_otro(self) -> None:
        res = cruzar([cargo()], [cfdi("U-1", total="100.50"), cfdi("U-2")], CONFIG)
        assert uno(res).cfdis == ("U-2",)
        assert res.cfdis_asignados() == frozenset({"U-2"})


class TestVentana:
    @pytest.mark.parametrize("dia", [-3, 0, 10])
    def test_dentro_de_la_ventana_incluye_bordes(self, dia: int) -> None:
        assert uno(cruzar([cargo()], [cfdi("U-1", dia=dia)], CONFIG)).evidencia == "monto_exacto"

    @pytest.mark.parametrize("dia", [-4, -13, 11, 20])
    def test_fuera_de_ventana_dentro_del_margen(self, dia: int) -> None:
        r = uno(cruzar([cargo()], [cfdi("U-1", dia=dia)], CONFIG))
        assert (r.cfdis, r.motivo) == ((), "fuera_de_ventana")
        assert [(d.uuid, d.motivo) for d in r.descartados] == [("U-1", "fuera_de_ventana")]

    @pytest.mark.parametrize("dia", [-16, 26])
    def test_mas_alla_del_margen_no_hay_candidato(self, dia: int) -> None:
        assert uno(cruzar([cargo()], [cfdi("U-1", dia=dia)], CONFIG)).motivo == "sin_candidato"

    def test_fuera_de_ventana_exige_afinidad(self) -> None:
        ajeno = cfdi("U-1", dia=16, rfc="RFC_COM_09", nombre="OPERADORA HOTEL MIRADOR SA DE CV")
        assert uno(cruzar([cargo()], [ajeno], CONFIG)).motivo == "sin_candidato"

    def test_ventana_configurable(self) -> None:
        estrecha = dataclasses.replace(CONFIG, ventana_min=-2, ventana_max=3)
        assert uno(cruzar([cargo()], [cfdi("U-1", dia=3)], estrecha)).evidencia == "monto_exacto"
        assert uno(cruzar([cargo()], [cfdi("U-1", dia=-3)], estrecha)).motivo == "fuera_de_ventana"


class TestRfcGenerico:
    def test_receptor_generico_unico(self) -> None:
        r = uno(cruzar([cargo()], [cfdi("U-1", receptor=PUBLICO)], CONFIG))
        assert (r.cfdis, r.motivo) == ((), "solo_rfc_generico")
        assert [(d.uuid, d.motivo) for d in r.descartados] == [("U-1", "solo_rfc_generico")]

    def test_receptor_generico_duplicado_gana_el_valido(self) -> None:
        pool = [cfdi("U-1", receptor=PUBLICO), cfdi("U-2", dia=3)]
        r = uno(cruzar([cargo()], pool, CONFIG))
        assert (r.cfdis, r.evidencia) == (("U-2",), "monto_exacto")

    def test_emisor_generico_uno_a_uno_no_es_evidencia(self) -> None:
        r = uno(cruzar([cargo()], [cfdi("U-1", rfc=EXTRANJERO)], CONFIG))
        assert r.motivo == "solo_rfc_generico"

    def test_emisores_genericos_no_se_suman(self) -> None:
        pool = [
            cfdi("U-1", total="60.00", rfc=EXTRANJERO, nombre="DEMO CLOUD TOOLS LLC"),
            cfdi("U-2", total="40.00", rfc=EXTRANJERO, nombre="CAFE LUNA AZUL INC"),
        ]
        r = uno(cruzar([cargo()], pool, CONFIG))
        assert (r.cfdis, r.motivo) == ((), "solo_rfc_generico")
        assert sorted(d.uuid for d in r.descartados) == ["U-1", "U-2"]

    def test_nomina_emitida_no_es_candidata(self) -> None:
        nomina = cfdi("U-1", tipo="N", direccion="emitido", rfc=EMPRESA, receptor="RFC_EMPLEADO_01")
        assert uno(cruzar([cargo()], [nomina], CONFIG)).motivo == "sin_candidato"

    def test_factura_emitida_no_es_candidata(self) -> None:
        emitida = cfdi("U-1", direccion="emitido", rfc=EMPRESA, receptor="RFC_CLIENTE_01")
        assert uno(cruzar([cargo()], [emitida], CONFIG)).motivo == "sin_candidato"

    def test_receptor_de_otra_empresa_no_es_candidato(self) -> None:
        assert uno(cruzar([cargo()], [cfdi("U-1", receptor="RFC_OTRA_EMPRESA")], CONFIG)).motivo == "sin_candidato"


class TestNotasDeCredito:
    def test_factura_mas_nota_neta_forma_suma(self) -> None:
        pool = [cfdi("U-1", total="150.00"), cfdi("U-2", total="50.00", tipo="E", dia=2)]
        r = uno(cruzar([cargo()], pool, CONFIG))
        assert (r.cfdis, r.evidencia) == (("U-1", "U-2"), "suma")
        assert r.deltas == (0, 2)

    def test_nota_sola_respalda_un_abono(self) -> None:
        r = uno(cruzar([cargo(monto="-50.00")], [cfdi("U-1", total="50.00", tipo="E")], CONFIG))
        assert (r.cfdis, r.evidencia) == (("U-1",), "monto_exacto")

    def test_reembolso_total_cada_fila_con_su_cfdi(self) -> None:
        cargos = [cargo("ALFA-0001", "80.00"), cargo("ALFA-0002", "-80.00", dia=2)]
        pool = [cfdi("U-1", "80.00"), cfdi("U-2", "80.00", tipo="E", dia=2)]
        res = cruzar(cargos, pool, CONFIG)
        assert uno(res, "ALFA-0001").cfdis == ("U-1",)
        assert uno(res, "ALFA-0002").cfdis == ("U-2",)

    def test_nota_no_respalda_un_cargo_positivo(self) -> None:
        r = uno(cruzar([cargo(monto="50.00")], [cfdi("U-1", total="50.00", tipo="E")], CONFIG))
        assert (r.cfdis, r.motivo) == ((), "sin_candidato")


class TestSumas:
    def test_suma_de_dos(self) -> None:
        r = uno(cruzar([cargo()], [cfdi("U-1", "60.00"), cfdi("U-2", "40.00", dia=1)], CONFIG))
        assert (r.cfdis, r.evidencia, r.diferencia) == (("U-1", "U-2"), "suma", Decimal("0.00"))

    def test_suma_de_tres(self) -> None:
        pool = [cfdi("U-1", "30.00"), cfdi("U-2", "30.00", dia=1), cfdi("U-3", "40.00", dia=2)]
        r = uno(cruzar([cargo()], pool, CONFIG))
        assert (r.cfdis, r.evidencia) == (("U-1", "U-2", "U-3"), "suma")

    def test_distractor_del_mismo_emisor_queda_libre(self) -> None:
        pool = [cfdi("U-1", "60.00"), cfdi("U-2", "40.00"), cfdi("U-3", "75.00", dia=1)]
        res = cruzar([cargo()], pool, CONFIG)
        assert uno(res).cfdis == ("U-1", "U-2")
        assert "U-3" not in res.cfdis_asignados()

    def test_emisores_distintos_no_se_suman(self) -> None:
        pool = [cfdi("U-1", "60.00"), cfdi("U-2", "40.00", rfc="RFC_COM_02")]
        assert uno(cruzar([cargo()], pool, CONFIG)).motivo == "sin_candidato"

    def test_suma_exige_afinidad_de_nombre(self) -> None:
        ajeno = "TALLER MECANICO EL PISTON SA DE CV"
        pool = [cfdi("U-1", "60.00", nombre=ajeno), cfdi("U-2", "40.00", nombre=ajeno)]
        assert uno(cruzar([cargo()], pool, CONFIG)).motivo == "sin_candidato"

    def test_prefiere_menos_cfdis(self) -> None:
        pool = [cfdi("U-1", "70.00"), cfdi("U-2", "30.00"), cfdi("U-3", "20.00"), cfdi("U-4", "10.00")]
        assert uno(cruzar([cargo()], pool, CONFIG)).cfdis == ("U-1", "U-2")

    def test_max_cfdis_es_configurable(self) -> None:
        pool = [cfdi("U-1", "30.00"), cfdi("U-2", "30.00"), cfdi("U-3", "40.00")]
        solo_pares = dataclasses.replace(CONFIG, suma_max_cfdis=2)
        assert uno(cruzar([cargo()], pool, solo_pares)).evidencia is None

    def test_tolerancia_de_suma_configurable(self) -> None:
        pool = [cfdi("U-1", "60.00"), cfdi("U-2", "40.50")]
        assert uno(cruzar([cargo()], pool, CONFIG)).evidencia == "suma"
        exacta = dataclasses.replace(CONFIG, tolerancia_suma=Decimal("0.00"))
        assert uno(cruzar([cargo()], pool, exacta)).evidencia is None

    def test_tope_por_emisor_trunca_y_advierte(self) -> None:
        pool = [cfdi("U-1", "11.00"), cfdi("U-2", "12.00", dia=1), cfdi("U-3", "13.00", dia=2),
                cfdi("U-4", "89.00", dia=9)]
        tope = dataclasses.replace(CONFIG, suma_max_candidatos=3)
        r = uno(cruzar([cargo()], pool, tope))
        assert r.evidencia is None
        assert r.advertencias == ("tope_suma_truncado: emisor RFC_COM_01, 4 candidatos, se usan 3",)
        assert uno(cruzar([cargo()], pool, CONFIG)).cfdis == ("U-1", "U-4")

    def test_sin_tope_excedido_no_hay_advertencia(self) -> None:
        r = uno(cruzar([cargo()], [cfdi("U-1", "60.00"), cfdi("U-2", "40.00")], CONFIG))
        assert r.advertencias == ()


class TestPrecedencia:
    def test_uno_a_uno_gana_sobre_suma_del_mismo_cargo(self) -> None:
        res = cruzar([cargo()], [cfdi("U-1", "60.00"), cfdi("U-2", "40.00"), cfdi("U-3")], CONFIG)
        assert (uno(res).cfdis, uno(res).evidencia) == (("U-3",), "monto_exacto")
        assert res.cfdis_asignados() == frozenset({"U-3"})

    @pytest.mark.parametrize("id_suma,id_uno", [("ALFA-0001", "ALFA-0002"), ("ALFA-0002", "ALFA-0001")])
    def test_cfdi_tomado_uno_a_uno_no_entra_en_suma(self, id_suma: str, id_uno: str) -> None:
        cargos = [cargo(id_suma, "100.00"), cargo(id_uno, "60.00")]
        res = cruzar(cargos, [cfdi("U-1", "60.00"), cfdi("U-2", "40.00")], CONFIG)
        assert uno(res, id_uno).cfdis == ("U-1",)
        assert (uno(res, id_suma).cfdis, uno(res, id_suma).motivo) == ((), "sin_candidato")


class TestEmpates:
    def test_identicos_se_reparten_por_orden_total(self) -> None:
        cargos = [cargo("ALFA-0002"), cargo("ALFA-0001")]
        res = cruzar(cargos, [cfdi("U-2"), cfdi("U-1")], CONFIG)
        assert uno(res, "ALFA-0001").cfdis == ("U-1",)
        assert uno(res, "ALFA-0002").cfdis == ("U-2",)

    def test_mismo_monto_fechas_distintas_gana_la_fecha_cercana(self) -> None:
        cargos = [cargo("ALFA-0001", dia=0), cargo("ALFA-0002", dia=4)]
        res = cruzar(cargos, [cfdi("U-1", dia=4), cfdi("U-2", dia=0)], CONFIG)
        assert uno(res, "ALFA-0001").cfdis == ("U-2",)
        assert uno(res, "ALFA-0002").cfdis == ("U-1",)

    def test_mismo_monto_y_fecha_comercios_distintos_decide_el_nombre(self) -> None:
        cargos = [cargo("ALFA-0001", desc="HOTEL MIRADOR DEL LAGO MICH"),
                  cargo("ALFA-0002", desc="FARMACIA SALUD CDMX")]
        pool = [cfdi("U-1", dia=1, rfc="RFC_COM_23", nombre="FARMACIA SALUD EJEMPLO SA DE CV"),
                cfdi("U-2", dia=1, rfc="RFC_COM_10", nombre="OPERADORA HOTEL MIRADOR DEL LAGO SA DE CV")]
        res = cruzar(cargos, pool, CONFIG)
        assert uno(res, "ALFA-0001").cfdis == ("U-2",)
        assert uno(res, "ALFA-0002").cfdis == ("U-1",)

    def test_a_igual_distancia_gana_el_cfdi_posterior(self) -> None:
        r = uno(cruzar([cargo()], [cfdi("U-1", dia=-2), cfdi("U-2", dia=2)], CONFIG))
        assert r.cfdis == ("U-2",)

    def test_resultado_no_depende_del_orden_de_los_insumos(self) -> None:
        cargos = [cargo("ALFA-0001"), cargo("ALFA-0002"), cargo("ALFA-0003", "100.00", dia=1)]
        pool = [cfdi("U-1"), cfdi("U-2", dia=1), cfdi("U-3", "60.00"), cfdi("U-4", "40.00")]
        directo = cruzar(cargos, pool, CONFIG)
        invertido = cruzar(list(reversed(cargos)), list(reversed(pool)), CONFIG)
        assert directo == invertido

    def test_un_cfdi_nunca_respalda_dos_cargos(self) -> None:
        cargos = [cargo("ALFA-0001"), cargo("ALFA-0002"), cargo("ALFA-0003")]
        res = cruzar(cargos, [cfdi("U-1"), cfdi("U-2")], CONFIG)
        asignados = [u for r in res.cargos for u in r.cfdis]
        assert sorted(asignados) == ["U-1", "U-2"]
        assert uno(res, "ALFA-0003").motivo == "sin_candidato"


class TestFilasEspeciales:
    def test_pago_no_aplica_aunque_haya_monto_igual(self) -> None:
        pago = cargo(monto="-100.00", tipo="pago", desc="PAGO RECIBIDO GRACIAS")
        r = uno(cruzar([pago], [cfdi("U-1", tipo="E")], CONFIG))
        assert (r.cfdis, r.motivo) == ((), "no_aplica")

    def test_fila_ininterpretable(self) -> None:
        r = uno(cruzar([cargo(estado="ininterpretable")], [cfdi("U-1")], CONFIG))
        assert (r.cfdis, r.motivo) == ((), "fila_ininterpretable")

    def test_universo_vacio(self) -> None:
        assert cruzar([], [cfdi("U-1")], CONFIG).cargos == ()

    def test_pool_vacio(self) -> None:
        res = cruzar([cargo("ALFA-0001"), cargo("ALFA-0002", "-5.00")], [], CONFIG)
        assert [r.motivo for r in res.cargos] == ["sin_candidato", "sin_candidato"]

    def test_salida_ordenada_por_cargo(self) -> None:
        res = cruzar([cargo("BETA-0001"), cargo("ALFA-0009")], [], CONFIG)
        assert [r.cargo_id for r in res.cargos] == ["ALFA-0009", "BETA-0001"]

    def test_descripcion_con_caracteres_especiales(self) -> None:
        raro = cargo(desc="CAFÉ 'LUNA' AZUL; DROP TABLE -- 🍞")
        assert uno(cruzar([raro], [cfdi("U-1", "60.00"), cfdi("U-2", "40.00")], CONFIG)).evidencia == "suma"


class TestEscala:
    def test_diez_mil_cargos_con_su_cfdi(self) -> None:
        n = 10_000
        cargos = [cargo(f"ALFA-{i:05d}", f"{100 + 3 * i}.00", dia=i % 300) for i in range(n)]
        pool = [cfdi(f"U-{i:05d}", f"{100 + 3 * i}.00", dia=i % 300 + 1) for i in range(n)]
        res = cruzar(cargos, pool, CONFIG)
        assert all(r.evidencia == "monto_exacto" for r in res.cargos)
        assert len(res.cfdis_asignados()) == n
