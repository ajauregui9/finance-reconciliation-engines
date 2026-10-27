"""Catálogo de familias de prompt_guard y sus patrones.

Los patrones se escriben para la vista plana (minúsculas, sin acentos, un espacio entre
palabras) o para la compacta (solo letras y dígitos). Entre dos palabras se acepta
cualquier separador (`SEP`), así que `ignora-las_instrucciones` cuenta igual que con
espacios. Las listas de palabras van separadas por comas (`_lista`). Cada familia y su
intención están en `specs/prompt_guard.md`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern, Tuple

ANULACION = "anulacion_instrucciones"
CAMBIO_DE_ROL = "cambio_de_rol"
MARCADOR_DE_ROL = "marcador_de_rol"
MARCADO_HTML = "marcado_html"
EXFILTRACION = "exfiltracion"
CAMBIO_CUENTA = "cambio_cuenta_bancaria"
AL_MODELO = "instruccion_al_modelo"
MANIPULACION = "manipulacion_conciliacion"
TEXTO_INVISIBLE = "texto_invisible"
NO_INSPECCIONABLE = "no_inspeccionable"

FAMILIAS: Tuple[str, ...] = (ANULACION, CAMBIO_DE_ROL, MARCADOR_DE_ROL, MARCADO_HTML, EXFILTRACION, CAMBIO_CUENTA,
                             AL_MODELO, MANIPULACION, TEXTO_INVISIBLE, NO_INSPECCIONABLE)

VISTA_PLANA = "plana"
VISTA_COMPACTA = "compacta"

SEP = r"[\W_]+"


def _hasta(palabras: int) -> str:
    """Hasta `palabras` palabras de relleno (perezoso), cada una seguida de un separador."""
    return rf"(?:\w+{SEP}){{0,{palabras}}}?"


def _lista(opciones: str) -> str:
    """Alternativa de las opciones separadas por comas; un espacio dentro de una opción es `SEP`."""
    return "(?:" + "|".join(o.strip().replace(" ", SEP) for o in opciones.split(",")) + ")"


def _articulos(palabras: str, veces: int = 1) -> str:
    """Hasta `veces` palabras cortas opcionales de la lista (artículos, posesivos)."""
    return rf"(?:{_lista(palabras)}{SEP}){{0,{veces}}}"


@dataclass(frozen=True)
class Patron:
    familia: str
    regex: Pattern[str]
    vista: str = VISTA_PLANA
    al_inicio: bool = False


def _p(familia: str, patron: str, vista: str = VISTA_PLANA, al_inicio: bool = False) -> Patron:
    return Patron(familia, re.compile(patron), vista, al_inicio)


# --- anulación de instrucciones -------------------------------------------------
_VERBO_EN = _lista(r"ignore, disregard, forget, override, overrule, bypass, discard, neglect, pay no attention to, "
                   r"do not follow, don[\W_]?t follow, dont follow, do not obey, stop following, never mind")
_OBJETO_EN = _lista("instructions?, prompts?, directives, guidelines, programming, system prompt")
_CALIFICA_EN = _lista("previous, prior, preceding, earlier, above, former, original, initial, existing")
_OBJETO_DEBIL_EN = _lista("rules, directions, commands, context, messages?, constraints, polic(?:y|ies), text, input, "
                          "guidance")
_PASADO_EN = _lista("above, before, previous(?:ly)?, prior, said, written, you (?:were|have been) told")
_VERBO_ES = _lista("ignora, ignore, ignoren, ignorar, olvida, olvide, olviden, olvidar, olvidate, omite, omita, "
                   "omitan, omitir, descarta, descarte, descartar, desatiende, desobedece, anula, anular, sobrescribe, "
                   "sobreescribe, haz caso omiso (?:a|de), hagan caso omiso (?:a|de), "
                   "no (?:sigas|siga|sigan|obedezcas|obedezca|consideres|apliques), no hagas caso (?:a|de), "
                   "no tomes en cuenta, deja de (?:seguir|obedecer), deja de lado, pasa por alto")
_OBJETO_ES = _lista("instrucciones, instruccion, indicaciones, indicacion, directrices, directivas, prompt, consignas, "
                    "programacion")
_OBJETO_DEBIL_ES = _lista("reglas, ordenes, mensajes, restricciones, politicas, texto, contexto")
_CALIFICA_ES = _lista("anteriores, anterior, previas, previa, precedentes, de arriba, originales, iniciales, "
                      "del sistema")
_LO_ANTERIOR = _lista("anterior, previo, de arriba, "
                      "que (?:te |se te )?(?:dijeron|dije|indicaron|pidieron|ordenaron|escribieron)")

_ANULACION: Tuple[Patron, ...] = (
    _p(ANULACION, rf"\b{_VERBO_EN}{SEP}{_hasta(3)}{_OBJETO_EN}\b"),
    _p(ANULACION, rf"\b{_VERBO_EN}{SEP}{_hasta(3)}{_CALIFICA_EN}{SEP}{_hasta(2)}{_OBJETO_DEBIL_EN}\b"),
    _p(ANULACION, rf"\b(?:ignore|disregard|forget){SEP}{_hasta(2)}(?:everything|anything|all){SEP}{_hasta(2)}"
                  rf"{_PASADO_EN}\b"),
    _p(ANULACION, rf"\b(?:ignore|disregard|forget){SEP}{_articulos('the, all, everything, of, that', 2)}above\b"),
    _p(ANULACION, rf"\b{_lista('new, updated, revised, real, actual')}{SEP}"
                  rf"{_lista('instructions?, system prompt, rules')}\s*:"),
    _p(ANULACION, rf"\b{_VERBO_ES}{SEP}{_hasta(3)}{_OBJETO_ES}\b"),
    _p(ANULACION, rf"\b{_VERBO_ES}{SEP}{_hasta(3)}{_OBJETO_DEBIL_ES}{SEP}{_hasta(2)}{_CALIFICA_ES}\b"),
    _p(ANULACION, rf"\b{_VERBO_ES}{SEP}(?:todo{SEP})?lo{SEP}{_LO_ANTERIOR}\b"),
    _p(ANULACION, rf"\b{_lista('nuevas, nueva, verdaderas, reales, actualizadas')}{SEP}"
                  rf"{_lista('instrucciones, indicaciones, reglas, ordenes')}\s*:"),
    _p(ANULACION, r"ignore(?:all|any|the|your|of)*(?:previous|prior|above|earlier|preceding)?"
                  r"(?:instructions?|prompts?|directives)", VISTA_COMPACTA),
    _p(ANULACION, r"disregard(?:all|the|any|your)*(?:previous|prior|above|earlier)", VISTA_COMPACTA),
    _p(ANULACION, r"(?:ignora|olvida)(?:todas|todos|las|los|tus|sus)*"
                  r"(?:instrucciones|indicaciones|directrices)", VISTA_COMPACTA),
    _p(ANULACION, r"olvida(?:todo)?loanterior", VISTA_COMPACTA),
)

# --- cambio de rol --------------------------------------------------------------
_ROLES_EN = _lista("unrestricted, unfiltered, different, new, evil, admin, administrator, root, developer, system, "
                   "superuser, dan, jailbroken, ai, assistant, chatbot, model")
_ROLES_ES = _lista("asistente, administrador, admin, sistema, desarrollador, superusuario, root, ia, modelo, bot, dan")
_DESDE_AHORA_ES = _lista("eres, seras, actua, actuaras, responde, responderas, ignora, obedece, solo, siempre, "
                         "te comportaras, vas a")
_MODOS_ES = _lista("desarrollador, dios, administrador, admin, sin restricciones, sin filtros, depuracion, jailbreak, "
                   "dan")

_CAMBIO_DE_ROL: Tuple[Patron, ...] = (
    _p(CAMBIO_DE_ROL, rf"\byou are now\b(?!{SEP}(?:enrolled|subscribed|registered|a member|eligible|signed))"),
    _p(CAMBIO_DE_ROL, rf"\bfrom now on\b{SEP}{_hasta(2)}"
                      rf"{_lista('you, act, respond, answer, behave, ignore, only, always, reply')}\b"),
    _p(CAMBIO_DE_ROL, rf"\bpretend{SEP}{_lista('to be, you are, that you')}\b"),
    _p(CAMBIO_DE_ROL, rf"\b{_lista('act, behave, respond, roleplay, role play')}{SEP}as{SEP}"
                      rf"(?:an?{SEP}|the{SEP})?{_ROLES_EN}\b"),
    _p(CAMBIO_DE_ROL, rf"\b{_lista('developer, god, admin, debug, jailbreak, unrestricted, dan, sudo')}{SEP}mode\b"),
    _p(CAMBIO_DE_ROL, r"\b(?:jailbreak(?:ed|ing)?|do anything now)\b"),
    _p(CAMBIO_DE_ROL, rf"\bahora{SEP}eres\b"),
    _p(CAMBIO_DE_ROL, rf"\b{_lista('a partir de ahora, de ahora en adelante, desde ahora')}{SEP}{_hasta(2)}"
                      rf"{_DESDE_AHORA_ES}\b"),
    _p(CAMBIO_DE_ROL, rf"\b{_lista('finge, fingir, simula, simular')}{SEP}{_lista('ser, que eres')}\b"),
    _p(CAMBIO_DE_ROL, rf"\bhaz{SEP}como{SEP}si{SEP}fueras\b"),
    _p(CAMBIO_DE_ROL, rf"\b{_lista('actua, actue, actuar, comportate, comportese')}{SEP}como{SEP}"
                      rf"(?:si{SEP}fueras{SEP})?{_articulos('un, una, el, la')}{_ROLES_ES}\b"),
    _p(CAMBIO_DE_ROL, rf"\bmodo{SEP}{_MODOS_ES}\b"),
)

# --- marcadores de rol ----------------------------------------------------------
_MARCADOR_DE_ROL: Tuple[Patron, ...] = (
    _p(MARCADOR_DE_ROL, r"\b(?:system|assistant|developer|sistema|asistente|desarrollador)\s*:", al_inicio=True),
    _p(MARCADOR_DE_ROL, rf"\b(?:system|developer){SEP}"
                        r"(?:override|prompt|message|instruction|note|notice|command|directive)s?\s*:"),
    _p(MARCADOR_DE_ROL, rf"\b{_lista('mensaje, instruccion, instrucciones, indicacion, nota, orden')}{SEP}"
                        rf"del{SEP}{_lista('sistema, administrador, desarrollador')}\s*:"),
    _p(MARCADOR_DE_ROL, r"[\[<]\s*/?\s*(?:system|sistema|assistant|asistente|developer|inst|sys|instructions?|"
                        r"instrucciones)\s*[\]>]"),
    _p(MARCADOR_DE_ROL, r"<\|\s*[a-z_]{2,20}\s*\|>"),
    _p(MARCADOR_DE_ROL, r"<<\s*/?\s*sys\s*>>"),
    _p(MARCADOR_DE_ROL, r"#{2,}\s*(?:system|instruction|instructions|instrucciones|assistant|response|sistema)\b"),
    _p(MARCADOR_DE_ROL, rf"\b(?:begin|start|end){SEP}(?:of{SEP})?(?:system|hidden|secret){SEP}"
                        r"(?:prompt|instructions?|message)\b"),
)

# --- marcado HTML ---------------------------------------------------------------
_MARCADO_HTML: Tuple[Patron, ...] = (
    _p(MARCADO_HTML, r"(?:<|&lt;)!--(?:(?!-->|--&gt;).){0,200}(?:-->|--&gt;)?"),
    _p(MARCADO_HTML, r"(?:<|&lt;)\s*/?\s*(?:script|iframe|object|embed|style|svg|meta|link|form|img|"
                     r"instructions?|instrucciones|prompt|hidden|oculto|secret)\b"),
    _p(MARCADO_HTML, r"\bon(?:error|load|click|mouseover|focus)\s*="),
    _p(MARCADO_HTML, r"\bjavascript\s*:"),
)

# --- exfiltración ---------------------------------------------------------------
_ENVIAR_EN = _lista("send, forward, email, e-mail, mail, upload, transmit, leak, share, exfiltrate, export, dump, "
                    "paste, submit")
_SECRETOS_EN = _lista(r"credentials, passwords?, api[\W_]?keys?, access[\W_]?tokens?, tokens, secrets?, private keys?, "
                      r"card numbers, conversation, chat history, system prompt, "
                      r"(?:all|the|full|entire|complete) (?:data|database|records|ledger|files|context|history)")
_REVELAR_EN = _lista("reveal, print, show, display, output, repeat, dump, leak, tell me, give me, write out, disclose")
_PROMPT_EN = _lista("system prompt, hidden (?:prompt|instructions), initial prompt, prompt")
_REVELADO_EN = _lista(r"your (?:instructions|rules), "
                      r"(?:the|all|any|your) (?:api[\W_]?keys?|passwords?|credentials|secrets?)")
_ENVIAR_ES = _lista("envia, envie, envien, enviar, enviame, manda, mande, manden, mandar, mandame, reenvia, reenvie, "
                    "reenviar, comparte, comparta, compartir, sube, suba, subir, filtra, filtrar, transmite, exporta, "
                    "publica")
_SECRETOS_ES = _lista("credenciales, contrasenas?, claves? (?:de )?(?:api|acceso), llaves? (?:privadas?|de api), "
                      "tokens?, secretos, numeros de tarjeta, conversacion, "
                      "historial de (?:la )?(?:conversacion|chat), prompt, instrucciones del sistema, "
                      "(?:todos los|toda la|todas las) (?:datos|registros|informacion|archivos|correos)")
_REVELAR_ES = _lista("revela, revele, revelar, muestra, muestrame, muestre, mostrar, imprime, imprimir, repite, "
                     "repetir, dime, escribe, transcribe")
_REVELADO_ES = _lista("(?:tu|tus|su|sus) (?:instrucciones|indicaciones|reglas|prompt), (?:el|tu|su) prompt, "
                      "(?:las|tus|sus) (?:contrasenas|credenciales), (?:la|tu|su) (?:contrasena|clave api)")
_DESTINO_EXTERNO = r"(?:https?[\W_]|webhook|endpoint|ngrok|pastebin|requestbin)"

_EXFILTRACION: Tuple[Patron, ...] = (
    _p(EXFILTRACION, rf"\b{_ENVIAR_EN}{SEP}{_hasta(3)}{_SECRETOS_EN}\b"),
    _p(EXFILTRACION, rf"\b{_REVELAR_EN}{SEP}(?:me{SEP}|us{SEP})?(?:your|the){SEP}{_hasta(1)}{_PROMPT_EN}\b"),
    _p(EXFILTRACION, rf"\b{_REVELAR_EN}{SEP}(?:me{SEP}|us{SEP})?{_REVELADO_EN}\b"),
    _p(EXFILTRACION, rf"\b{_ENVIAR_ES}{SEP}{_hasta(3)}{_SECRETOS_ES}\b"),
    _p(EXFILTRACION, rf"\b{_REVELAR_ES}{SEP}{_hasta(2)}{_REVELADO_ES}\b"),
    _p(EXFILTRACION, r"!\[[^\]]{0,100}\]\(\s*(?:https?:)?//"),
    _p(EXFILTRACION, rf"\b(?:curl|wget|invoke-webrequest|iwr){SEP}(?:-\w+{SEP}){{0,4}}https?:"),
    _p(EXFILTRACION, rf"\b{_lista('send, post, upload, forward, envia, manda, sube, reenvia')}{SEP}{_hasta(5)}"
                     rf"{_DESTINO_EXTERNO}"),
)

# --- cambio de cuenta bancaria --------------------------------------------------
_CAMBIAR_ES = _lista("cambio, cambiamos, cambiar, cambie, cambia, actualiza, actualice, actualizar, actualizamos, "
                     "actualizacion, modifica, modifique, modificar, modificacion, nueva, nuevo, nuevos, nuestra nueva")
_CUENTA_ES = _lista("cuenta (?:bancaria|de deposito|receptora|para (?:pagos|depositos|transferencias)), clabe, "
                    "datos bancarios, beneficiario, banco receptor")
_DEPOSITAR_ES = _lista("deposita, deposite, depositen, depositar, transfiere, transfiera, transfieran, transferir, "
                       "paga, pague, paguen, abona, abone, envia, envie")
_OTRA_CUENTA_ES = (rf"(?:(?:nueva|siguiente|otra){SEP}(?:cuenta|clabe)|"
                   rf"(?:cuenta|clabe){SEP}(?:nueva|siguiente|indicada|adjunta|anexa))")
_ORDENAR_ES = _lista("programa, programe, ejecuta, ejecute, realiza, realice, haz, haga, autoriza, autorice, procesa, "
                     "procese, libera, libere")
_CAMBIAR_EN = _lista("new, updated, changed, change (?:of|to|in), update, updating")
_CUENTA_EN = _lista("bank(?:ing)? (?:account|details|information|info|instructions), beneficiary, routing number, "
                    "iban, remittance details")
_OTRA_EN = _lista("new, following, below, updated, different, alternate, another")
_ORDENAR_EN = _lista("initiate, make, process, execute, schedule, release, authorize")

_CAMBIO_CUENTA: Tuple[Patron, ...] = (
    _p(CAMBIO_CUENTA, rf"\b{_CAMBIAR_ES}{SEP}"
                      rf"{_articulos('de, la, el, los, las, nuestra, nuestro, nuestros, su, sus, tu, tus', 2)}"
                      rf"{_CUENTA_ES}\b"),
    _p(CAMBIO_CUENTA, rf"\b{_DEPOSITAR_ES}{SEP}{_hasta(5)}{_OTRA_CUENTA_ES}\b"),
    _p(CAMBIO_CUENTA, rf"\b{_ORDENAR_ES}{SEP}{_articulos('una, la, el, un, esta, las')}"
                      r"(?:transferencias?|spei|deposito|wire)\b"),
    _p(CAMBIO_CUENTA, rf"\b{_CAMBIAR_EN}{SEP}{_articulos('our, the, your, my, of, to', 2)}{_CUENTA_EN}\b"),
    _p(CAMBIO_CUENTA, rf"\b{_lista('wire, transfer, send, remit, pay, deposit')}{SEP}{_hasta(5)}"
                      rf"(?:to|into){SEP}{_articulos('the, this, our, a, my')}{_OTRA_EN}{SEP}"
                      rf"{_lista('account, iban, bank, beneficiary')}"),
    _p(CAMBIO_CUENTA, rf"\b{_ORDENAR_EN}{SEP}{_articulos('a, the, an, this')}(?:urgent{SEP})?"
                      rf"{_lista('wire, bank transfer, transfer, payment')}{SEP}(?:of|to|for)\b"),
)

# --- instrucciones dirigidas al modelo -----------------------------------------
_IA_EN = _lista(r"ai, a[\W_]?i, artificial intelligence, assistant, ai assistant, ai agent, llm, language model, "
                r"ai model, chatbot, bot, gpt, chatgpt, claude, copilot, gemini, automated (?:system|agent|reviewer)")
_IA_ES = _lista(r"ia, i[\W_]?a, inteligencia artificial, asistente, asistente virtual, asistente de ia, "
                r"modelo de lenguaje, modelo de ia, modelo ia, llm, chatbot, bot, agente de ia, agente ia, "
                r"agente automatico, claude, chatgpt, gpt, copilot, gemini, revisor automatico, sistema automatico")
_AVISO_EN = _lista("note, message, instructions?, memo, attention, reminder, directive, request")
_AVISO_ES = _lista("nota, mensaje, instruccion, instrucciones, aviso, atencion, recordatorio, indicacion, indicaciones")
_LEER_EN = _lista("reading, processing, parsing, reviewing, summarizing")

_AL_MODELO: Tuple[Patron, ...] = (
    _p(AL_MODELO, rf"\b{_AVISO_EN}{SEP}(?:to|for){SEP}{_articulos('the, any, all')}{_IA_EN}\b"),
    _p(AL_MODELO, rf"\b{_lista('dear, hey, hello, hi')}{SEP}{_IA_EN}\b"),
    _p(AL_MODELO, rf"\bif{SEP}you{SEP}are{SEP}(?:an?{SEP})?{_IA_EN}\b"),
    _p(AL_MODELO, rf"\b(?:to|for){SEP}(?:any|the){SEP}{_lista('ai, llm, language model, automated system')}s?"
                  rf"{SEP}{_LEER_EN}\b"),
    _p(AL_MODELO, rf"\b{_AVISO_ES}{SEP}(?:para|al|a){SEP}{_articulos('el, la, cualquier, todo')}{_IA_ES}\b"),
    _p(AL_MODELO, rf"\b{_lista('estimado, estimada, querido, querida, hola, oye')}{SEP}{_IA_ES}\b"),
    _p(AL_MODELO, rf"\bsi{SEP}eres{SEP}{_articulos('un, una, el, la')}{_IA_ES}\b"),
    _p(AL_MODELO, rf"\b(?:la|cualquier){SEP}(?:ia|inteligencia{SEP}artificial){SEP}que{SEP}"
                  rf"{_lista('lea, procese, revise, analice')}\b"),
)

# --- manipulación de la conciliación -------------------------------------------
_DICTAR_ES = _lista("marca, marcalo, marcala, marque, marquelo, marcar, marquen, clasifica, clasificalo, clasifique, "
                    "clasificar, registra, registralo, registre, registrar, considera, consideralo, considere, dejalo, "
                    "reportalo, ponlo")
_RESULTADO_ES = _lista("conciliados?, conciliada, aprobados?, aprobada, autorizado, autorizada, valido, valida, "
                       "deducibles?, pagado, pagada, verificado, verificada, revisado, revisada, correcto, correcta, "
                       "legitimo, legitima, sin observaciones")
_REGISTRO_ES = _lista("cargos?, pagos?, gastos?, facturas?, movimientos?, registros?, cfdis?, asientos?, cruces?")
_EL_REGISTRO_ES = rf"{_articulos('este, esta, el, la, los, las, estos, todo, todos')}(?:{_REGISTRO_ES}{SEP})?"
_NO_REVISAR_ES = _lista("revises, revise, revisen, audites, audite, auditen, reportes, reporten, marques, escales, "
                        "escale, cuestiones, verifiques, senales, bloquees, rechaces, rechace")
_APROBAR_ES = _lista("aprueba, apruebe, aprueben, apruebalo, autoriza, autorizalo, acepta, aceptalo, validalo, "
                     "concilia, concilie, concilialo")
_SIN_REVISAR_ES = _lista("automaticamente, sin (?:revision|revisar|validar|verificar|preguntar|cuestionar), "
                         "de inmediato, directamente")
_CONTROL_ES = _lista("revision, validacion, verificacion, aprobacion, cola de revision")
_NO_EN = _lista(r"do not, don[\W_]?t, dont, never")
_REGISTRO_EN = _lista("charges?, payments?, invoices?, transactions?, expenses?, entry, item")
_RESULTADO_EN = _lista("reconciled, approved, verified, valid, deductible, paid, reviewed, legitimate, matched, "
                       "cleared")
_NO_REVISAR_EN = _lista("flag, review, audit, report, escalate, question, verify, reject, block")
_YA_EN = _lista("automatically, immediately, without (?:review|checking|verification)")
_CONTROL_EN = _lista("review, approval, verification, reconciliation, checks?")

_MANIPULACION: Tuple[Patron, ...] = (
    _p(MANIPULACION, rf"\b{_DICTAR_ES}{SEP}{_EL_REGISTRO_ES}como{SEP}{_RESULTADO_ES}\b"),
    _p(MANIPULACION, rf"\b(?:no|nunca){SEP}{_articulos('lo, la, los, las, me')}{_NO_REVISAR_ES}\b"),
    _p(MANIPULACION, rf"\b{_APROBAR_ES}{SEP}{_EL_REGISTRO_ES}{_SIN_REVISAR_ES}\b"),
    _p(MANIPULACION, rf"\b{_lista('omite, omitir, saltate, evita, evitar, brinca')}{SEP}"
                     rf"{_articulos('la, el, las, los')}{_CONTROL_ES}\b"),
    _p(MANIPULACION, rf"\bmark{SEP}{_articulos('this, it, the, these, all, them')}(?:{_REGISTRO_EN}{SEP})?"
                     rf"as{SEP}{_RESULTADO_EN}\b"),
    _p(MANIPULACION, rf"\b{_NO_EN}{SEP}{_NO_REVISAR_EN}\b"),
    _p(MANIPULACION, rf"\b(?:auto[\W_]?approve|approve{SEP}automatically|"
                     rf"approve{SEP}(?:this|it|the|all){SEP}{_hasta(2)}{_YA_EN})\b"),
    _p(MANIPULACION, rf"\b{_lista('skip, bypass, avoid, circumvent')}{SEP}"
                     rf"{_articulos('the, any, all, human, manual', 2)}{_CONTROL_EN}\b"),
)

PATRONES: Tuple[Patron, ...] = (_ANULACION + _CAMBIO_DE_ROL + _MARCADOR_DE_ROL + _MARCADO_HTML + _EXFILTRACION
                                + _CAMBIO_CUENTA + _AL_MODELO + _MANIPULACION)
