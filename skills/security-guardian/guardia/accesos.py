"""Controles que no dependen del texto: filtro de rutas sensibles y allowlist de dominios.

Ambos fallan cerrado: ante la duda, la decisión es "no permitido" con su motivo. La
allowlist compara etiquetas completas del host, nunca sufijos de texto. Reglas en
`specs/prompt_guard.md`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import FrozenSet, Iterable, Optional, Sequence, Tuple, Union
from urllib.parse import SplitResult, urlsplit

Ruta = Union[str, "os.PathLike[str]"]

DOMINIOS_PERMITIDOS: Tuple[str, ...] = ("*.suitetalk.api.netsuite.com",)
ESQUEMA_SEGURO = "https"
PUERTO_SEGURO = 443
COMODIN = "*."
MIN_ETIQUETAS = 2
_ETIQUETA = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

RAICES_DEL_SISTEMA: Tuple[PurePath, ...] = tuple(PurePath(r) for r in (
    "/etc", "/private/etc", "/var/root", "/private/var/root", "/root", "/proc", "/sys", "/dev"))
CARPETAS_SENSIBLES: FrozenSet[str] = frozenset({
    ".ssh", ".aws", ".gnupg", ".kube", ".docker", ".azure", "gcloud", "keychains", ".password-store"})
ARCHIVOS_SENSIBLES: FrozenSet[str] = frozenset({
    ".env", ".netrc", ".npmrc", ".pypirc", ".pgpass", ".git-credentials", "credentials", "id_rsa", "id_dsa",
    "id_ecdsa", "id_ed25519", "authorized_keys", ".bash_history", ".zsh_history"})
PREFIJOS_SENSIBLES: Tuple[str, ...] = (".env.",)
EXTENSIONES_SENSIBLES: FrozenSet[str] = frozenset({
    ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".kdbx", ".ppk"})


@dataclass(frozen=True)
class Decision:
    permitido: bool
    motivo: str


def _no(motivo: str) -> Decision:
    return Decision(False, motivo)


# --- rutas ----------------------------------------------------------------------


def _motivo_sensible(ruta: PurePath) -> Optional[str]:
    for raiz in RAICES_DEL_SISTEMA:
        if ruta == raiz or raiz in ruta.parents:
            return f"ruta del sistema bajo {raiz}"
    carpetas = [p.lower() for p in ruta.parts[:-1]]
    sensibles = sorted(set(carpetas) & CARPETAS_SENSIBLES)
    if sensibles:
        return f"carpeta de credenciales {sensibles[0]}"
    nombre = ruta.name.lower()
    if nombre in ARCHIVOS_SENSIBLES or nombre.startswith(PREFIJOS_SENSIBLES) or nombre in CARPETAS_SENSIBLES:
        return f"archivo de secretos {ruta.name}"
    if ruta.suffix.lower() in EXTENSIONES_SENSIBLES:
        return f"extensión de llave o certificado {ruta.suffix}"
    return None


def _dentro(ruta: Path, raices: Sequence[Path]) -> bool:
    return any(ruta == raiz or raiz in ruta.parents for raiz in raices)


def ruta_permitida(ruta: Ruta, raices: Sequence[Ruta] = ()) -> Decision:
    """Rechaza rutas del sistema, de credenciales o de secretos, y lo que quede fuera de `raices`."""
    if not isinstance(ruta, (str, os.PathLike)):
        raise TypeError(f"se esperaba una ruta; llegó {type(ruta).__name__}")
    texto = os.fspath(ruta)
    if not texto.strip():
        return _no("ruta vacía")
    if "\x00" in texto:
        return _no("ruta con byte nulo")
    pedida = Path(os.path.expanduser(texto)).absolute()
    try:
        resuelta = pedida.resolve()
        resueltas = [Path(os.path.expanduser(os.fspath(r))).resolve() for r in raices]
    except (OSError, RuntimeError) as error:
        return _no(f"bloqueada: no se pudo resolver la ruta ({error})")
    for candidata in (pedida, resuelta):
        motivo = _motivo_sensible(candidata)
        if motivo is not None:
            return _no(f"bloqueada: {motivo}")
    if resueltas and not _dentro(resuelta, resueltas):
        return _no("bloqueada: fuera de las raíces permitidas")
    return Decision(True, "permitida")


# --- dominios -------------------------------------------------------------------


def _host_valido(host: str) -> bool:
    etiquetas = host.split(".")
    return len(etiquetas) >= MIN_ETIQUETAS and all(_ETIQUETA.match(e) for e in etiquetas)


def validar_allowlist(entradas: Iterable[str]) -> Tuple[str, ...]:
    """Entradas normalizadas (minúsculas, sin punto final); `ValueError` si alguna está mal formada."""
    normalizadas = []
    for entrada in entradas:
        if not isinstance(entrada, str):
            raise ValueError(f"entrada de allowlist inválida: {entrada!r} no es texto")
        limpia = entrada.strip().lower().rstrip(".")
        base = limpia[len(COMODIN):] if limpia.startswith(COMODIN) else limpia
        if not _host_valido(base):
            raise ValueError(f"entrada de allowlist inválida: {entrada!r} (host exacto o '*.' más un host de "
                             f"al menos {MIN_ETIQUETAS} etiquetas)")
        normalizadas.append(limpia)
    return tuple(normalizadas)


def _coincide(host: str, entrada: str) -> bool:
    if not entrada.startswith(COMODIN):
        return host == entrada
    base = entrada[len(COMODIN):]
    sobrante = host[:-len(base) - 1] if host.endswith("." + base) else ""
    return bool(sobrante) and "." not in sobrante


def _partes(destino: str) -> Union[SplitResult, Decision]:
    if not destino.strip():
        return _no("destino vacío")
    if "\\" in destino:
        return _no("destino con barra invertida")
    if any(c.isspace() for c in destino):
        return _no("destino con espacios")
    try:
        return urlsplit(destino if "://" in destino else f"{ESQUEMA_SEGURO}://{destino}")
    except ValueError as error:
        return _no(f"URL inválida: {error}")


def _host(partes: SplitResult) -> Union[str, Decision]:
    if partes.scheme.lower() != ESQUEMA_SEGURO:
        return _no(f"esquema {partes.scheme or '(vacío)'} no permitido; solo {ESQUEMA_SEGURO}")
    if partes.username is not None or partes.password is not None:
        return _no("credenciales en la URL")
    try:
        puerto = partes.port
    except ValueError:
        return _no("puerto inválido")
    if puerto not in (None, PUERTO_SEGURO):
        return _no(f"puerto {puerto} no permitido")
    host = (partes.hostname or "").rstrip(".")
    if not host:
        return _no("URL sin host")
    if not host.isascii():
        return _no("host no ASCII (posible homógrafo)")
    if not _host_valido(host):
        return _no(f"host con una etiqueta inválida: {host}")
    return host


def dominio_permitido(destino: str, permitidos: Iterable[str] = DOMINIOS_PERMITIDOS) -> Decision:
    """Solo `https` hacia un host de la allowlist; el comodín cubre exactamente una etiqueta."""
    if not isinstance(destino, str):
        raise TypeError(f"se esperaba str; llegó {type(destino).__name__}")
    allowlist = validar_allowlist(permitidos)
    partes = _partes(destino)
    if isinstance(partes, Decision):
        return partes
    host = _host(partes)
    if isinstance(host, Decision):
        return host
    if any(_coincide(host, entrada) for entrada in allowlist):
        return Decision(True, "permitido")
    return _no(f"el host {host} no está en la allowlist")
