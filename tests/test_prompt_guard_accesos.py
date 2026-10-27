"""Controles de prompt_guard que no dependen del texto: allowlist de dominios y filtro de rutas sensibles."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "security-guardian"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from guardia import DOMINIOS_PERMITIDOS, Decision, dominio_permitido, ruta_permitida  # noqa: E402
from guardia.accesos import validar_allowlist  # noqa: E402

CUENTA = "1234567.suitetalk.api.netsuite.com"


# ------------------------------------------------------------------ dominios
class TestDominios:
    def test_la_allowlist_por_omision_es_el_subdominio_de_cuenta_de_netsuite(self) -> None:
        assert DOMINIOS_PERMITIDOS == ("*.suitetalk.api.netsuite.com",)

    @pytest.mark.parametrize("destino", [
        f"https://{CUENTA}/ruta/de/ejemplo",
        CUENTA,
        "1234567-sb1.suitetalk.api.netsuite.com",
        "TSTDRV99.SuiteTalk.Api.NetSuite.com",
        f"https://{CUENTA}:443/x",
        f"{CUENTA}.",
    ])
    def test_acepta_subdominios_de_cuenta(self, destino: str) -> None:
        assert dominio_permitido(destino) == Decision(True, "permitido")

    @pytest.mark.parametrize("destino,motivo", [
        ("suitetalk.api.netsuite.com", "no está en la allowlist"),
        ("a.b.suitetalk.api.netsuite.com", "no está en la allowlist"),
        ("suitetalk.api.netsuite.com.evil.com", "no está en la allowlist"),
        ("1234.suitetalk.api.netsuite.com.evil.com", "no está en la allowlist"),
        ("xsuitetalk.api.netsuite.com", "no está en la allowlist"),
        ("1234.xsuitetalk.api.netsuite.com", "no está en la allowlist"),
        ("1234.suitetalk-api.netsuite.com", "no está en la allowlist"),
        ("1234.suitetalk.api.netsuite.co", "no está en la allowlist"),
        ("evil.com/1234.suitetalk.api.netsuite.com", "no está en la allowlist"),
        (f"http://{CUENTA}", "esquema"),
        (f"ftp://{CUENTA}", "esquema"),
        (f"https://user:pw@{CUENTA}", "credenciales"),
        (f"https://{CUENTA}@evil.com", "credenciales"),
        (f"https://{CUENTA}:8443/", "puerto"),
        (f"https://{CUENTA}:abc/", "puerto"),
        (f"https://{CUENTA}\\@evil.com", "barra invertida"),
        (f"https://{CUENTA} .evil.com", "espacios"),
        ("https://1234.suitetalk.api.netsuit\u0435.com", "ASCII"),
        ("https://1234.suitetalk.api.netsuite.com。evil.com", "ASCII"),
        ("https://-bad-.suitetalk.api.netsuite.com", "etiqueta"),
        ("https://", "sin host"),
        ("", "vacío"),
        ("https://[::1", "URL inválida"),
    ])
    def test_rechaza_parecidos_y_trucos(self, destino: str, motivo: str) -> None:
        decision = dominio_permitido(destino)
        assert decision.permitido is False
        assert motivo in decision.motivo

    def test_allowlist_propia_con_host_exacto(self) -> None:
        assert dominio_permitido("api.example.com", ("api.example.com",)).permitido
        assert not dominio_permitido("x.api.example.com", ("api.example.com",)).permitido

    @pytest.mark.parametrize("entrada", ["*", "*.com", "", "*.-x.com", "ex ample.com", "com", "*.*.example.com"])
    def test_rechaza_entradas_de_allowlist_mal_formadas(self, entrada: str) -> None:
        with pytest.raises(ValueError, match="allowlist"):
            validar_allowlist((entrada,))

    def test_una_entrada_que_no_es_texto_es_invalida(self) -> None:
        with pytest.raises(ValueError, match="no es texto"):
            validar_allowlist((7,))  # type: ignore[arg-type]

    def test_normaliza_las_entradas(self) -> None:
        assert validar_allowlist(("API.Example.com.", "*.Cuenta.Example.com")) == (
            "api.example.com", "*.cuenta.example.com")

    def test_rechaza_destinos_que_no_son_texto(self) -> None:
        with pytest.raises(TypeError):
            dominio_permitido(42)  # type: ignore[arg-type]


# --------------------------------------------------------------------- rutas
class TestRutas:
    @pytest.mark.parametrize("relativa", [
        ".ssh/id_rsa", ".aws/credentials", ".gnupg/pubring.kbx", ".kube/config", "proyecto/.env",
        "proyecto/.env.production", "llaves/servidor.pem", "llaves/firma.KEY", "certs/cliente.p12",
        ".netrc", ".git-credentials", "Library/Keychains/login.keychain-db", "CARPETA/.SSH/config",
        "id_ed25519", ".zsh_history", "boveda.kdbx",
    ])
    def test_rechaza_credenciales_y_secretos(self, tmp_path: Path, relativa: str) -> None:
        decision = ruta_permitida(tmp_path / relativa)
        assert decision.permitido is False, relativa
        assert decision.motivo

    @pytest.mark.parametrize("ruta", ["/etc/passwd", "/private/etc/hosts", "/proc/self/environ", "/root/x",
                                      "/dev/null"])
    def test_rechaza_rutas_del_sistema(self, ruta: str) -> None:
        decision = ruta_permitida(ruta)
        assert (decision.permitido, "sistema" in decision.motivo) == (False, True)

    def test_expande_la_carpeta_del_usuario(self) -> None:
        assert not ruta_permitida("~/.ssh/id_rsa").permitido

    def test_acepta_un_archivo_de_datos(self, tmp_path: Path) -> None:
        assert ruta_permitida(tmp_path / "datos" / "cfdis.jsonl") == Decision(True, "permitida")

    def test_un_enlace_no_esconde_el_destino(self, tmp_path: Path) -> None:
        secreto = tmp_path / ".ssh" / "id_rsa"
        secreto.parent.mkdir()
        secreto.write_text("x", encoding="utf-8")
        enlace = tmp_path / "inocente.txt"
        os.symlink(secreto, enlace)
        assert not ruta_permitida(enlace).permitido

    def test_un_enlace_con_nombre_de_secreto_tambien_se_rechaza(self, tmp_path: Path) -> None:
        destino = tmp_path / "config.txt"
        destino.write_text("x", encoding="utf-8")
        os.symlink(destino, tmp_path / ".env")
        assert not ruta_permitida(tmp_path / ".env").permitido

    def test_con_raices_solo_acepta_lo_que_queda_dentro(self, tmp_path: Path) -> None:
        raiz = tmp_path / "trabajo"
        assert ruta_permitida(raiz / "a.csv", (raiz,)).permitido
        afuera = ruta_permitida(raiz / ".." / "otro" / "a.csv", (raiz,))
        assert (afuera.permitido, "fuera de las raíces" in afuera.motivo) == (False, True)

    @pytest.mark.parametrize("ruta,motivo", [("", "vacía"), ("a\x00b", "byte nulo")])
    def test_rechaza_rutas_vacias_o_con_nulos(self, ruta: str, motivo: str) -> None:
        decision = ruta_permitida(ruta)
        assert (decision.permitido, motivo in decision.motivo) == (False, True)

    def test_una_ruta_que_no_se_puede_resolver_se_rechaza(self, tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
        def falla(self: Path, strict: bool = False) -> Path:
            raise RuntimeError("bucle de enlaces")

        monkeypatch.setattr(Path, "resolve", falla)
        decision = ruta_permitida(tmp_path / "a.csv")
        assert (decision.permitido, "no se pudo resolver" in decision.motivo) == (False, True)

    def test_rechaza_lo_que_no_es_ruta(self) -> None:
        with pytest.raises(TypeError):
            ruta_permitida(3.5)  # type: ignore[arg-type]
