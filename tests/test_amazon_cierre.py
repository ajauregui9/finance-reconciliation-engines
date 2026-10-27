"""Pruebas del núcleo del cierre con liquidaciones pequeñas armadas a mano."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Dict, List, Mapping, Optional, Tuple

import pytest

import test_amazon_soporte as soporte
from cierre_amazon.cierre import CierreMes, ResultadoCorrida, cerrar
from cierre_amazon.config import Config, config_desde_dict
from cierre_amazon.errores import ErrorInsumo
from cierre_amazon.lector_fuentes import facturas_desde_dict, leer_consola_texto, venta_erp_desde_dict
from cierre_amazon.lector_liquidacion import leer_liquidacion_texto
from cierre_amazon.modelo import Insumos
from cierre_amazon.ubicacion import FilaUbicada, ubicar
from cierre_amazon.validacion import evaluar_candados

D = Decimal
HUSO = "UTC-07:00"


def _config(fuente: str = "liquidacion", tolerancia: str = "1.00", **cambios: object) -> Config:
    datos = soporte.config_dict(**cambios)
    datos["publicidad"] = {"fuente_autoritativa": fuente, "tolerancia": tolerancia}
    return config_desde_dict(datos)


def _insumos(liquidaciones: Mapping[str, str], consola: Optional[str] = None,
             facturas: Optional[List[Dict[str, str]]] = None,
             venta_erp: Optional[Dict[str, str]] = None) -> Insumos:
    archivos = tuple(leer_liquidacion_texto(texto, f"liquidacion_{periodo}.csv", "MXN")
                     for periodo, texto in sorted(liquidaciones.items()))
    return Insumos(
        archivos=archivos,
        consola=None if consola is None else leer_consola_texto(consola, "publicidad_consola.csv"),
        facturas=None if facturas is None else facturas_desde_dict(
            {"esquema": "facturas_publicidad/v1", "facturas": facturas}, "facturas_publicidad.json"),
        venta_erp=None if venta_erp is None else venta_erp_desde_dict(
            {"esquema": "venta_erp/v1", "venta_neta_por_mes_de_pedido": venta_erp}, "venta_erp.json"),
    )


def _cerrar(liquidaciones: Mapping[str, str], config: Optional[Config] = None, **fuentes: object) -> ResultadoCorrida:
    return cerrar(_insumos(liquidaciones, **fuentes), config or _config())  # type: ignore[arg-type]


def _mes(resultado: ResultadoCorrida, mes: str) -> CierreMes:
    return next(c for c in resultado.meses if c.mes == mes)


def _codigos(cierre: CierreMes) -> List[str]:
    return [a.codigo for a in cierre.alertas]


def _candados(cierre: CierreMes) -> Dict[str, bool]:
    return {c.nombre: c.ok for c in cierre.candados}


# --- escenario de dos meses: abril con provisión, mayo con cola y reverso ---------------

ABRIL = soporte.csv_liquidacion("2026-04", HUSO, [
    soporte.venta("2026-04-10 10:00:00", "P-1", "1000.00", fecha_pedido="2026-04-09 10:00:00",
                  comision="-150.00", logistica="-100.00", retencion="-80.00"),
])
MAYO = soporte.csv_liquidacion("2026-05", HUSO, [
    soporte.venta("2026-05-03 10:00:00", "P-2", "500.00", fecha_pedido="2026-04-29 10:00:00",
                  comision="-80.00", logistica="-45.00", retencion="-40.00"),
    soporte.venta("2026-05-12 10:00:00", "P-3", "2000.00", fecha_pedido="2026-05-11 10:00:00",
                  comision="-300.00", logistica="-160.00", retencion="-160.00"),
])
ERP = {"2026-04": "1500.00", "2026-05": "2000.00"}


class TestCohortesYCorte:
    def test_separa_cohorte_del_mes_y_cola(self) -> None:
        mayo = _mes(_cerrar({"2026-04": ABRIL, "2026-05": MAYO}, venta_erp=ERP), "2026-05")
        assert mayo.grupos.cohorte_mes.venta_neta == D("2000.00")
        assert list(mayo.grupos.colas) == ["2026-04"]
        assert mayo.grupos.colas["2026-04"].venta_neta == D("500.00")
        assert mayo.grupos.colas["2026-04"].pedidos == 1

    def test_fila_que_el_corte_saca_de_los_meses_declarados(self) -> None:
        texto = soporte.csv_liquidacion("2026-05", HUSO, [
            soporte.venta("2026-05-12 10:00:00", "P-3", "100.00"),
            soporte.venta("2026-05-31 23:30:00", "P-9", "40.00"),
        ])
        resultado = _cerrar({"2026-05": texto})
        assert list(resultado.fuera_de_meses) == ["2026-06"]
        assert resultado.fuera_de_meses["2026-06"].filas == 1
        assert resultado.fuera_de_meses["2026-06"].total == D("40.00")
        assert [a.codigo for a in resultado.alertas] == ["filas_fuera_de_meses"]
        assert _mes(resultado, "2026-05").grupos.todas.total == D("100.00")

    def test_el_huso_de_cada_archivo_decide_el_mes(self) -> None:
        filas = [soporte.venta("2026-06-30 22:30:00", "P-1", "100.00", fecha_pedido="2026-06-30 08:00:00")]
        menos7 = _cerrar({"2026-06": soporte.csv_liquidacion("2026-06", "UTC-07:00", filas)})
        menos8 = _cerrar({"2026-06": soporte.csv_liquidacion("2026-06", "UTC-08:00", filas)})
        assert _mes(menos7, "2026-06").grupos.cohorte_mes.filas == 1
        assert dict(menos7.fuera_de_meses) == {}
        assert _mes(menos8, "2026-06").grupos.todas.filas == 0
        assert menos8.fuera_de_meses["2026-07"].filas == 1

    def test_cohorte_por_fecha_del_pedido_en_huso_de_cierre(self) -> None:
        # En UTC+00:00 el pedido del 1 de julio a las 05:30 es 30 de junio en el huso de cierre.
        texto = soporte.csv_liquidacion("2026-07", "UTC+00:00", [
            soporte.venta("2026-07-01 07:00:00", "P-1", "100.00", fecha_pedido="2026-07-01 05:30:00"),
        ])
        julio = _mes(_cerrar({"2026-07": texto}), "2026-07")
        assert list(julio.grupos.colas) == ["2026-06"]
        assert julio.grupos.cohorte_mes.filas == 0

    def test_cola_de_reembolsos_conserva_el_signo(self) -> None:
        texto = soporte.csv_liquidacion("2026-06", HUSO, [
            soporte.venta("2026-06-04 10:00:00", "P-7", "-900.00", fecha_pedido="2026-05-20 10:00:00",
                          comision="108.00", retencion="72.00", tipo="Reembolso"),
            soporte.venta("2026-06-05 10:00:00", "P-8", "200.00", fecha_pedido="2026-05-31 10:00:00",
                          comision="-30.00", retencion="-16.00"),
        ])
        junio = _mes(_cerrar({"2026-06": texto}), "2026-06")
        cola = junio.grupos.colas["2026-05"]
        assert cola.venta_neta == D("-700.00")
        assert junio.gasto.tarifas["comision"].cola_real == D("-78.00")
        assert cola.pedidos == 1

    def test_fila_de_pedido_sin_fecha_del_pedido(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", HUSO, [
            soporte.venta("2026-04-10 10:00:00", "P-1", "1.00", fecha_pedido=""),
        ])
        with pytest.raises(ErrorInsumo, match="Fecha del pedido"):
            _cerrar({"2026-04": texto})

    def test_fila_de_pedido_sin_pedido(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", HUSO, [
            soporte.venta("2026-04-10 10:00:00", "", "1.00"),
        ])
        with pytest.raises(ErrorInsumo, match="Pedido"):
            _cerrar({"2026-04": texto})


class TestProvisionYReverso:
    def test_tasas_efectivas_solo_con_la_cohorte_del_mes(self) -> None:
        mayo = _mes(_cerrar({"2026-04": ABRIL, "2026-05": MAYO}, venta_erp=ERP), "2026-05")
        assert mayo.tasas is not None
        assert mayo.tasas["comision"] == D("0.15")
        assert mayo.tasas["logistica"] == D("0.08")
        assert mayo.tasas["otras_tarifas"] == D("0")

    def test_provision_sobre_la_venta_pendiente(self) -> None:
        abril = _mes(_cerrar({"2026-04": ABRIL}, venta_erp=ERP), "2026-04")
        assert abril.venta_pendiente == D("500.00")
        assert abril.provision is not None
        assert abril.provision.comision == D("75.00")
        assert abril.provision.logistica == D("50.00")
        assert abril.gasto.tarifas["comision"].total == D("225.00")

    def test_provision_redondea_al_final(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", HUSO, [
            soporte.venta("2026-04-10 10:00:00", "P-1", "1000.00", comision="-150.00"),
        ])
        abril = _mes(_cerrar({"2026-04": texto}, venta_erp={"2026-04": "1333.33"}), "2026-04")
        assert abril.provision is not None
        assert abril.provision.comision == D("50.00")  # 333.33 * 0.15 = 49.9995

    def test_reverso_de_la_provision_anterior_contra_la_cola_real(self) -> None:
        mayo = _mes(_cerrar({"2026-04": ABRIL, "2026-05": MAYO}, venta_erp=ERP), "2026-05")
        comision = mayo.gasto.tarifas["comision"]
        assert (comision.cohorte_mes, comision.provision, comision.cola_real, comision.reverso) == (
            D("300.00"), D("0.00"), D("80.00"), D("75.00"))
        assert comision.total == D("305.00")
        assert mayo.gasto.tarifas["logistica"].total == D("155.00")
        assert "cola_sin_provision_previa" not in _codigos(mayo)

    def test_suma_de_meses_es_gasto_real_mas_ultima_provision(self) -> None:
        resultado = _cerrar({"2026-04": ABRIL, "2026-05": MAYO}, venta_erp={"2026-04": "1500.00",
                                                                            "2026-05": "2400.00"})
        devengado = sum((c.gasto.tarifas["comision"].total for c in resultado.meses), D("0"))
        real = D("150.00") + D("80.00") + D("300.00")
        ultima = _mes(resultado, "2026-05").provision
        assert ultima is not None
        assert devengado == real + ultima.comision

    def test_cola_sin_provision_previa(self) -> None:
        mayo = _mes(_cerrar({"2026-05": MAYO}, venta_erp=ERP), "2026-05")
        assert "cola_sin_provision_previa" in _codigos(mayo)
        assert mayo.gasto.tarifas["comision"].reverso == D("0.00")
        assert mayo.gasto.tarifas["comision"].total == D("380.00")

    def test_sin_venta_erp_no_hay_provision(self) -> None:
        abril = _mes(_cerrar({"2026-04": ABRIL}), "2026-04")
        assert abril.provision is None and abril.venta_pendiente is None
        assert "sin_venta_erp" in _codigos(abril)
        assert abril.gasto.tarifas["comision"].total == D("150.00")

    def test_sin_venta_en_la_cohorte_no_hay_tasa(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", HUSO, [soporte.cargo("2026-04-05 10:00:00", "Almacenaje", "-10.00")])
        abril = _mes(_cerrar({"2026-04": texto}, venta_erp={"2026-04": "100.00"}), "2026-04")
        assert abril.tasas is None and abril.provision is None
        assert "sin_tasa_efectiva" in _codigos(abril)

    def test_tasa_fuera_de_referencia(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", HUSO, [
            soporte.venta("2026-04-10 10:00:00", "P-1", "1000.00", comision="-250.00", logistica="-100.00",
                          retencion="-80.00"),
        ])
        abril = _mes(_cerrar({"2026-04": texto}, venta_erp={"2026-04": "1000.00"}), "2026-04")
        fuera = [a for a in abril.alertas if a.codigo == "tasa_fuera_de_referencia"]
        assert len(fuera) == 1
        assert dict(fuera[0].datos)["concepto"] == "comision"


# --- publicidad ------------------------------------------------------------------------

ABRIL_PUBLICIDAD = soporte.csv_liquidacion("2026-04", HUSO, [
    soporte.venta("2026-04-10 10:00:00", "P-1", "1000.00", comision="-150.00", logistica="-100.00",
                  retencion="-80.00"),
    soporte.cargo("2026-04-09 11:00:00", "Publicidad", "-386.67"),
    soporte.cargo("2026-04-17 11:00:00", "Publicidad", "-386.67"),
    soporte.cargo("2026-04-25 11:00:00", "Publicidad", "-386.67"),
    soporte.cargo("2026-04-05 10:00:00", "Almacenaje", "-300.00"),
    soporte.cargo("2026-04-14 12:00:00", "Transferencia", "-500.00"),
])
CONSOLA = "Fecha,Campaña,Gasto\n2026-04-01,NOR | Busqueda,400.00\n2026-04-15,BRI | Marca,600.00\n" \
          "2026-05-01,NOR | Busqueda,999.00\n"
FACTURA = {"mes": "2026-04", "folio": "PUB-1", "subtotal": "1000.00", "iva": "160.00", "total": "1160.00"}


class TestPublicidad:
    def _abril(self, fuente: str = "consola", factura: Optional[Dict[str, str]] = None,
               tolerancia: str = "1.00") -> CierreMes:
        resultado = _cerrar({"2026-04": ABRIL_PUBLICIDAD}, _config(fuente, tolerancia), consola=CONSOLA,
                            facturas=[factura or FACTURA])
        return _mes(resultado, "2026-04")

    def test_la_publicidad_entra_una_sola_vez(self) -> None:
        abril = self._abril()
        assert abril.gasto.publicidad == D("1000.00")
        assert dict(abril.gasto.cargos_periodo) == {"Almacenaje": D("300.00")}
        assert abril.gasto.total == D("150.00") + D("100.00") + D("300.00") + D("1000.00")
        assert all(_candados(abril).values())

    def test_monto_de_liquidacion_se_calcula_sobre_la_suma(self) -> None:
        abril = self._abril()
        assert abril.publicidad.liquidacion_con_iva == D("1160.01")
        assert abril.publicidad.liquidacion_sin_iva == D("1000.01")
        assert abril.publicidad.filas_liquidacion == 3
        assert dict(abril.publicidad.diferencias) == {"factura": D("0.00"), "liquidacion": D("0.01")}

    @pytest.mark.parametrize("fuente,monto", [("liquidacion", "1000.01"), ("consola", "1000.00"),
                                              ("factura", "1000.00")])
    def test_la_fuente_autoritativa_decide_la_linea(self, fuente: str, monto: str) -> None:
        abril = self._abril(fuente)
        assert abril.publicidad.fuente_autoritativa == fuente
        assert abril.gasto.publicidad == D(monto)
        assert fuente not in abril.publicidad.diferencias

    def test_fuentes_que_difieren_alertan(self) -> None:
        factura = {"mes": "2026-04", "folio": "PUB-1", "subtotal": "1100.00", "iva": "176.00", "total": "1276.00"}
        abril = self._abril(factura=factura)
        difieren = [a for a in abril.alertas if a.codigo == "publicidad_fuentes_difieren"]
        assert [dict(a.datos)["fuente"] for a in difieren] == ["factura"]
        assert dict(difieren[0].datos)["diferencia"] == "100.00"

    def test_diferencia_dentro_de_tolerancia_no_alerta(self) -> None:
        assert "publicidad_fuentes_difieren" not in _codigos(self._abril(tolerancia="0.01"))
        assert "publicidad_fuentes_difieren" in _codigos(self._abril(tolerancia="0.00"))

    def test_factura_con_iva_inconsistente(self) -> None:
        factura = {"mes": "2026-04", "folio": "PUB-1", "subtotal": "1000.00", "iva": "150.00", "total": "1150.00"}
        assert "factura_iva_inconsistente" in _codigos(self._abril(factura=factura))

    def test_fuente_autoritativa_ausente_detiene_el_cierre(self) -> None:
        with pytest.raises(ErrorInsumo, match="consola"):
            _cerrar({"2026-04": ABRIL_PUBLICIDAD}, _config("consola"))
        with pytest.raises(ErrorInsumo, match="factura"):
            _cerrar({"2026-04": ABRIL_PUBLICIDAD}, _config("factura"),
                    facturas=[dict(FACTURA, mes="2026-05")])

    def test_fuentes_opcionales_ausentes_no_se_comparan(self) -> None:
        abril = _mes(_cerrar({"2026-04": ABRIL_PUBLICIDAD}), "2026-04")
        assert abril.publicidad.consola is None and abril.publicidad.factura is None
        assert dict(abril.publicidad.diferencias) == {}

    def test_las_transferencias_no_son_gasto_pero_cuadran(self) -> None:
        abril = self._abril()
        assert abril.grupos.transferencias.total == D("-500.00")
        assert abril.grupos.todas.total == D("670.00") - D("1160.01") - D("300.00") - D("500.00")
        assert _candados(abril)["puente_liquidacion"]


# --- retención -------------------------------------------------------------------------


def _retencion_abril(*filas: Dict[str, str]) -> CierreMes:
    texto = soporte.csv_liquidacion("2026-04", HUSO, list(filas))
    return _mes(_cerrar({"2026-04": texto}), "2026-04")


class TestRetencion:
    def test_dentro_de_banda(self) -> None:
        abril = _retencion_abril(soporte.venta("2026-04-10 10:00:00", "P-1", "1000.00", retencion="-80.00"))
        assert abril.retencion.dentro_de_banda is True
        assert abril.retencion.tasa_observada == D("0.08")
        assert "retencion_fuera_de_banda" not in _codigos(abril)

    def test_fuera_de_banda_alerta_con_datos(self) -> None:
        abril = _retencion_abril(soporte.venta("2026-04-10 10:00:00", "P-1", "1000.00", retencion="-120.00"))
        assert abril.retencion.dentro_de_banda is False
        alerta = next(a for a in abril.alertas if a.codigo == "retencion_fuera_de_banda")
        datos = dict(alerta.datos)
        assert datos["tasa_observada"] == "0.120000"
        assert datos["esperada"] == "80.00"
        assert datos["diferencia"] == "40.00"

    @pytest.mark.parametrize("retenida,dentro", [("-90.00", True), ("-70.00", True), ("-90.01", False),
                                                 ("-69.99", False)])
    def test_la_banda_es_inclusiva(self, retenida: str, dentro: bool) -> None:
        abril = _retencion_abril(soporte.venta("2026-04-10 10:00:00", "P-1", "1000.00", retencion=retenida))
        assert abril.retencion.dentro_de_banda is dentro

    def test_filas_sin_retencion_quedan_en_la_base(self) -> None:
        abril = _retencion_abril(
            soporte.venta("2026-04-10 10:00:00", "P-1", "1000.00", retencion="-80.00"),
            soporte.venta("2026-04-11 10:00:00", "P-2", "1000.00"),
        )
        assert abril.retencion.base == D("2000.00")
        assert abril.retencion.tasa_observada == D("0.04")
        assert "retencion_fuera_de_banda" in _codigos(abril)

    def test_la_base_es_venta_mas_descuento_sin_envio(self) -> None:
        fila = soporte.fila("2026-04-10 10:00:00", venta_productos="1000.00", descuento_promocional="-100.00",
                            envio_cobrado="100.00", retencion="-72.00")
        abril = _retencion_abril(fila)
        assert abril.retencion.base == D("900.00")
        assert abril.retencion.esperada == D("72.00")
        assert abril.retencion.dentro_de_banda is True

    def test_la_cola_cuenta_en_el_mes_de_liquidacion(self) -> None:
        mayo = _mes(_cerrar({"2026-04": ABRIL, "2026-05": MAYO}), "2026-05")
        assert mayo.retencion.base == D("2500.00")
        assert mayo.retencion.retenida == D("200.00")

    def test_retencion_sin_base(self) -> None:
        abril = _retencion_abril(
            soporte.venta("2026-04-10 10:00:00", "P-1", "100.00", retencion="-8.00"),
            soporte.venta("2026-04-11 10:00:00", "P-1", "-100.00", tipo="Reembolso"),
        )
        assert abril.retencion.base == D("0.00")
        assert abril.retencion.tasa_observada is None and abril.retencion.dentro_de_banda is None
        assert "retencion_sin_base" in _codigos(abril)

    def test_sin_base_ni_retencion_no_alerta(self) -> None:
        abril = _retencion_abril(soporte.cargo("2026-04-05 10:00:00", "Almacenaje", "-10.00"))
        assert abril.retencion.dentro_de_banda is None
        assert not [c for c in _codigos(abril) if c.startswith("retencion")]


# --- candados --------------------------------------------------------------------------


class TestCandados:
    def test_todo_cuadra_en_un_cierre_normal(self) -> None:
        resultado = _cerrar({"2026-04": ABRIL, "2026-05": MAYO}, venta_erp=ERP)
        assert resultado.ok
        for cierre in resultado.meses:
            assert set(_candados(cierre)) == {"puente_liquidacion", "puente_cohortes", "publicidad_una_vez",
                                              "gasto_suma_lineas", "tipos_clasificados"}
            assert all(_candados(cierre).values())

    def test_tipo_sin_clasificar_falla_pero_no_se_pierde(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", HUSO, [
            soporte.venta("2026-04-10 10:00:00", "P-1", "1000.00", retencion="-80.00"),
            soporte.cargo("2026-04-12 10:00:00", "Cargo nuevo", "-10.00"),
        ])
        resultado = _cerrar({"2026-04": texto})
        abril = _mes(resultado, "2026-04")
        assert abril.grupos.sin_clasificar["Cargo nuevo"].total == D("-10.00")
        assert _candados(abril)["tipos_clasificados"] is False
        assert _candados(abril)["puente_liquidacion"] is True
        assert not resultado.ok

    def _piezas(self) -> Tuple[CierreMes, List[FilaUbicada]]:
        config = _config("consola")
        insumos = _insumos({"2026-04": ABRIL_PUBLICIDAD}, consola=CONSOLA, facturas=[FACTURA])
        abril = _mes(cerrar(insumos, config), "2026-04")
        filas = [f for f in ubicar(insumos.archivos, config) if f.mes == "2026-04"]
        return abril, filas

    def test_los_candados_detectan_publicidad_duplicada(self) -> None:
        abril, filas = self._piezas()
        cargos = dict(abril.gasto.cargos_periodo, Publicidad=D("1160.01"))
        gasto = replace(abril.gasto, cargos_periodo=cargos, total=abril.gasto.total + D("1160.01"))
        candados = {c.nombre: c.ok for c in evaluar_candados(filas, abril.grupos, gasto, abril.publicidad)}
        assert candados["publicidad_una_vez"] is False
        assert candados["gasto_suma_lineas"] is True

    def test_los_candados_detectan_un_total_que_no_suma(self) -> None:
        abril, filas = self._piezas()
        gasto = replace(abril.gasto, total=abril.gasto.total + D("0.01"))
        candados = {c.nombre: c.ok for c in evaluar_candados(filas, abril.grupos, gasto, abril.publicidad)}
        assert candados["gasto_suma_lineas"] is False

    def test_los_candados_detectan_una_fila_perdida(self) -> None:
        abril, filas = self._piezas()
        candados = {c.nombre: c.ok for c in evaluar_candados(filas[1:], abril.grupos, abril.gasto, abril.publicidad)}
        assert candados["puente_liquidacion"] is False
