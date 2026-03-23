#!/usr/bin/env python3
"""
generate_ass.py — Pipeline de Subtítulos con Estilos de Marca

Genera un archivo ASS con 3 estilos visuales y detección de keywords.

Input (variables de entorno):
  WHISPER_RESULT   — JSON string completo de Whisper verbose_json (contiene .words[])
  KEYWORDS_RESULT  — JSON array de strings de keywords (de GPT-4o-mini)
  STYLE_ID         — "A", "B" o "C" (seleccionado aleatoriamente por n8n)
  VIDEO_WIDTH      — ancho en píxeles (default: 1080)
  VIDEO_HEIGHT     — alto en píxeles (default: 1920)

Output:
  Escribe /tmp/subtitles.ass en disco
"""

import os
import sys
import json
import unicodedata
import string
from difflib import SequenceMatcher

# ---------------------------------------------------------------------------
# BRAND COLOR TOKENS — Formato ASS: &HAABBGGRR (alpha, blue, green, red)
# ---------------------------------------------------------------------------
# --bone:         #E8E0D4  → R=E8, G=E0, B=D4 → &H00D4E0E8
# --deep:         #0D0B09  → R=0D, G=0B, B=09 → &H00090B0D
# --obsidian:     #1A1714  → R=1A, G=17, B=14 → &H0014171A
# --bio-green:    #8B9A3B  → R=8B, G=9A, B=3B → &H003B9A8B
# --bio-dark:     #5C6828  → R=5C, G=68, B=28 → &H0028685C
# --neural-light: #D4AA82  → R=D4, G=AA, B=82 → &H0082AAD4
# --bark:         #6B5B4B  → R=6B, G=5B, B=4B → &H004B5B6B

# ---------------------------------------------------------------------------
# ESTILOS DE MARCA
# ---------------------------------------------------------------------------
STYLES = {
    "A": {
        # "Bold Impact" — Bebas Neue, uppercase, shadow, keywords en bio-green estático
        "font":             "Bebas Neue",
        "font_fallback":    "Arial",
        "font_size":        120,            # base para 1080px — escala automática por resolución
        "kw_font_size":     120,
        "max_words":        3,
        "case":             "upper",
        # Colors
        "primary_color":    "&H00D4E0E8",   # bone (normal)
        "kw_color":         "&H003B9A8B",   # bio-green (keyword)
        "secondary_color":  "&H00D4E0E8",
        "outline_color":    "&H00090B0D",   # deep
        "back_color":       "&H00090B0D",   # deep
        # Style
        "bold":             0,
        "kw_bold":          1,
        "italic":           0,
        "underline":        0,
        "border_style":     1,              # outline + shadow
        "outline":          3,
        "shadow":           2,
        "alignment":        2,              # bottom-center
        "margin_l":         80,
        "margin_r":         80,
        "margin_v":         180,
    },
    "B": {
        # "Boxed Highlight" — Bebas Neue, caja semitransparente, keywords en caja verde
        "font":             "Bebas Neue",
        "font_fallback":    "Arial",
        "font_size":        110,            # base para 1080px — escala automática por resolución
        "kw_font_size":     110,
        "max_words":        3,
        "case":             "upper",
        # Colors
        "primary_color":    "&H00D4E0E8",   # bone (normal text)
        "kw_color":         "&H00090B0D",   # deep (texto oscuro sobre caja verde)
        "secondary_color":  "&H00D4E0E8",
        "outline_color":    "&H00090B0D",
        "back_color":       "&H26090B0D",   # deep con 85% opacidad
        "kw_back_color":    "&H003B9A8B",   # bio-green box para keywords
        # Style
        "bold":             0,
        "kw_bold":          1,
        "italic":           0,
        "underline":        0,
        "border_style":     4,              # caja/fondo opaco
        "outline":          0,
        "shadow":           0,
        "alignment":        2,
        "margin_l":         80,
        "margin_r":         80,
        "margin_v":         180,
    },
    "C": {
        # "Minimal Accent" — Liberation Sans, sentence case, warm accent
        "font":             "Liberation Sans",
        "font_fallback":    "Arial",
        "font_size":        56,
        "kw_font_size":     62,
        "max_words":        4,
        "case":             "sentence",
        # Colors
        "primary_color":    "&H00D4E0E8",   # bone (normal)
        "kw_color":         "&H0082AAD4",   # neural-light warm amber (keyword)
        "secondary_color":  "&H00D4E0E8",
        "outline_color":    "&H00090B0D",
        "back_color":       "&H00090B0D",
        # Style
        "bold":             0,
        "kw_bold":          1,
        "italic":           0,
        "underline":        0,
        "border_style":     1,
        "outline":          2,
        "shadow":           3,
        "kw_outline":       0,
        "kw_shadow":        4,
        "alignment":        2,
        "margin_l":         60,
        "margin_r":         60,
        "margin_v":         120,
    },
}


# ---------------------------------------------------------------------------
# UTILIDADES DE TIEMPO ASS
# ---------------------------------------------------------------------------

def ass_time(seconds: float) -> str:
    """
    Convierte segundos float a formato ASS: H:MM:SS.cs (centiseconds 00-99).

    IMPORTANTE: El separador decimal usa centiseconds (00-99), NO milliseconds.
    Ej: 3.47s → 0:00:03.47
    """
    if seconds < 0:
        seconds = 0.0
    total_cs = round(seconds * 100)
    h  = total_cs // 360000
    m  = (total_cs % 360000) // 6000
    s  = (total_cs % 6000) // 100
    cs = total_cs % 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ---------------------------------------------------------------------------
# NORMALIZACIÓN Y MATCHING DE KEYWORDS
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """
    Normaliza texto para comparación:
    - NFKD decomposition (maneja tildes españolas: á→a, é→e, etc.)
    - casefold (lowercase Unicode-aware)
    - elimina puntuación y acentos residuales
    """
    nfkd = unicodedata.normalize("NFKD", text)
    # Mantener solo caracteres ASCII después de descomponer (elimina diacríticos)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    casefolded = ascii_only.casefold()
    # Eliminar puntuación
    no_punct = casefolded.translate(str.maketrans("", "", string.punctuation))
    return no_punct.strip()


def load_keywords(raw_json: str) -> frozenset:
    """
    Parsea el JSON array de keywords de GPT-4o-mini.
    Devuelve frozenset de strings normalizados.
    """
    try:
        keywords = json.loads(raw_json)
        if not isinstance(keywords, list):
            return frozenset()
        return frozenset(normalize(kw) for kw in keywords if isinstance(kw, str) and kw.strip())
    except (json.JSONDecodeError, TypeError):
        return frozenset()


def is_keyword(word: str, kw_set: frozenset) -> bool:
    """
    Determina si una palabra es keyword usando:
    1. Coincidencia exacta (normalizada)
    2. Substring match (maneja conjugaciones: "muscular" ↔ "músculo")
    3. Fuzzy match con SequenceMatcher ratio > 0.75
    """
    if not kw_set:
        return False

    word_norm = normalize(word)
    if not word_norm:
        return False

    for kw in kw_set:
        # 1. Coincidencia exacta
        if word_norm == kw:
            return True
        # 2. Substring match bidireccional
        if len(word_norm) >= 4 and len(kw) >= 4:
            if kw in word_norm or word_norm in kw:
                return True
        # 3. Fuzzy match
        ratio = SequenceMatcher(None, word_norm, kw).ratio()
        if ratio > 0.75:
            return True

    return False


# ---------------------------------------------------------------------------
# CONSTRUCCIÓN DE LÍNEAS ASS
# ---------------------------------------------------------------------------

def build_ass_header(style_id: str, video_w: int, video_h: int) -> str:
    """
    Genera el header ASS completo con [Script Info] y [V4+ Styles].
    """
    s = STYLES[style_id]
    font_name = f"{s['font']},{s['font_fallback']}"

    # Para Style B necesitamos 2 styles; para A y C también definimos el keyword style
    normal_style_line = (
        f"Style: StyleNormal,"
        f"{s['font']},"
        f"{s['font_size']},"
        f"{s['primary_color']},"
        f"{s['secondary_color']},"
        f"{s['outline_color']},"
        f"{s['back_color']},"
        f"{s['bold']},0,0,0,"
        f"100,100,0,0,"
        f"{s['border_style']},"
        f"{s['outline']},"
        f"{s.get('shadow', 0)},"
        f"{s['alignment']},"
        f"{s['margin_l']},{s['margin_r']},{s['margin_v']},1"
    )

    return (
        f"[Script Info]\n"
        f"ScriptType: v4.00+\n"
        f"PlayResX: {video_w}\n"
        f"PlayResY: {video_h}\n"
        f"WrapStyle: 0\n"
        f"ScaledBorderAndShadow: yes\n"
        f"\n"
        f"[V4+ Styles]\n"
        f"Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        f"Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        f"Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{normal_style_line}\n"
        f"\n"
        f"[Events]\n"
        f"Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def apply_case(text: str, case_mode: str, is_first_word: bool = False) -> str:
    """Aplica transformación de case según el estilo."""
    if case_mode == "upper":
        return text.upper()
    elif case_mode == "sentence":
        # Solo la primera palabra del bloque va capitalizada
        if is_first_word:
            return text.capitalize()
        return text.lower()
    return text


def build_word_tag(word_text: str, style_id: str, is_kw: bool) -> str:
    """
    Construye el texto con tags ASS inline para una palabra.
    Los tags ASS son acumulativos dentro de una línea Dialogue,
    por eso hay que resetear explícitamente al volver al estilo normal.
    """
    s = STYLES[style_id]

    if style_id == "A":
        if is_kw:
            # Keyword: bio-green, bold, fontsize 80
            tag = f"{{\\fn{s['font']}\\fs{s['kw_font_size']}\\c{s['kw_color']}\\b1}}"
        else:
            # Normal: bone, no bold, fontsize 72
            tag = f"{{\\fn{s['font']}\\fs{s['font_size']}\\c{s['primary_color']}\\b0}}"
        return f"{tag}{word_text}"

    elif style_id == "B":
        if is_kw:
            # Keyword: obsidian text + bio-green box
            # \3c es el color de outline/box en ASS BorderStyle 4
            tag = f"{{\\fn{s['font']}\\fs{s['kw_font_size']}\\c{s['kw_color']}\\3c{s['kw_back_color']}\\b1}}"
        else:
            # Normal: bone text + deep semitransparente box
            tag = f"{{\\fn{s['font']}\\fs{s['font_size']}\\c{s['primary_color']}\\3c{s['back_color']}\\b0}}"
        return f"{tag}{word_text}"

    elif style_id == "C":
        if is_kw:
            # Keyword: neural-light, bold, slight size bump, sin outline fuerte
            tag = (
                f"{{\\fn{s['font']}\\fs{s['kw_font_size']}"
                f"\\c{s['kw_color']}\\b1"
                f"\\bord{s.get('kw_outline', 0)}\\shad{s.get('kw_shadow', 4)}}}"
            )
        else:
            # Normal: bone, no bold, outline+shadow
            tag = (
                f"{{\\fn{s['font']}\\fs{s['font_size']}"
                f"\\c{s['primary_color']}\\b0"
                f"\\bord{s['outline']}\\shad{s.get('shadow', 3)}}}"
            )
        return f"{tag}{word_text}"

    return word_text


# ---------------------------------------------------------------------------
# CHUNKING Y RENDERIZADO
# ---------------------------------------------------------------------------

def chunk_words(words: list, max_words: int):
    """
    Genera grupos de hasta max_words palabras.
    Filtra palabras vacías.
    """
    buf = []
    for w in words:
        word_text = w.get("word", "").strip()
        if not word_text:
            continue
        buf.append(w)
        if len(buf) >= max_words:
            yield list(buf)
            buf.clear()
    if buf:
        yield list(buf)


def render_block(chunk: list, style_id: str, kw_set: frozenset) -> str:
    """
    Convierte un bloque de palabras en una línea Dialogue ASS.

    chunk: lista de word objects {word, start, end}
    Devuelve string "Dialogue: ..." o "" si chunk vacío.
    """
    if not chunk:
        return ""

    s = STYLES[style_id]

    # Timestamps
    start_sec = chunk[0].get("start", 0.0)
    last = chunk[-1]
    end_sec = last.get("end") or (last.get("start", start_sec) + 0.3)
    # Añadir 50ms de padding al final
    end_sec += 0.05

    start_str = ass_time(start_sec)
    end_str   = ass_time(end_sec)

    # Construir texto con tags inline
    parts = []
    for i, w in enumerate(chunk):
        raw_text = w.get("word", "").strip()
        if not raw_text:
            continue
        display_text = apply_case(raw_text, s["case"], is_first_word=(i == 0))
        kw = is_keyword(raw_text, kw_set)
        parts.append(build_word_tag(display_text, style_id, kw))

    if not parts:
        return ""

    # Unir palabras con espacio, el primer tag ya resetea el estilo para cada palabra
    text = " ".join(parts)

    return f"Dialogue: 0,{start_str},{end_str},StyleNormal,,0,0,0,,{text}"


# ---------------------------------------------------------------------------
# GENERACIÓN PRINCIPAL DEL ARCHIVO ASS
# ---------------------------------------------------------------------------

def write_empty_ass(output_path: str, style_id: str, video_w: int, video_h: int):
    """Escribe un archivo ASS válido pero sin diálogos (para video sin palabras)."""
    header = build_ass_header(style_id, video_w, video_h)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
    print(f"[generate_ass] Archivo vacío escrito: {output_path}", file=sys.stderr)


def main():
    # --- Leer variables de entorno ---
    whisper_raw   = os.environ.get("WHISPER_RESULT", "")
    keywords_raw  = os.environ.get("KEYWORDS_RESULT", "[]")
    style_id      = os.environ.get("STYLE_ID", "A").upper().strip()
    video_w       = int(os.environ.get("VIDEO_WIDTH", "1080"))
    video_h       = int(os.environ.get("VIDEO_HEIGHT", "1920"))
    output_path   = os.environ.get("OUTPUT_PATH", "/tmp/subtitles.ass")

    # Validar style_id
    if style_id not in STYLES:
        print(f"[generate_ass] STYLE_ID '{style_id}' inválido, usando 'A'", file=sys.stderr)
        style_id = "A"

    # Escalar font sizes y márgenes según resolución real (referencia: 1080px ancho)
    import copy
    scale = video_w / 1080.0
    if abs(scale - 1.0) > 0.01:
        STYLES[style_id] = copy.deepcopy(STYLES[style_id])
        STYLES[style_id]["font_size"]     = round(STYLES[style_id]["font_size"]     * scale)
        STYLES[style_id]["kw_font_size"]  = round(STYLES[style_id]["kw_font_size"]  * scale)
        STYLES[style_id]["margin_l"]      = round(STYLES[style_id]["margin_l"]      * scale)
        STYLES[style_id]["margin_r"]      = round(STYLES[style_id]["margin_r"]      * scale)
        STYLES[style_id]["margin_v"]      = round(STYLES[style_id]["margin_v"]      * scale)
        print(f"[generate_ass] Resolución {video_w}x{video_h} → escala {scale:.2f}x → font {STYLES[style_id]['font_size']}px", file=sys.stderr)

    # --- Parsear Whisper result ---
    # Soporte para leer desde archivo si el JSON es muy grande para env var
    whisper_file = os.environ.get("WHISPER_FILE", "/tmp/whisper.json")
    if not whisper_raw and os.path.exists(whisper_file):
        with open(whisper_file, "r", encoding="utf-8") as f:
            whisper_raw = f.read()
        print(f"[generate_ass] Leyendo Whisper desde archivo: {whisper_file}", file=sys.stderr)

    if not whisper_raw:
        print("[generate_ass] WHISPER_RESULT vacío, generando ASS vacío", file=sys.stderr)
        write_empty_ass(output_path, style_id, video_w, video_h)
        return

    try:
        whisper_data = json.loads(whisper_raw)
    except json.JSONDecodeError as e:
        print(f"[generate_ass] Error parseando WHISPER_RESULT: {e}", file=sys.stderr)
        write_empty_ass(output_path, style_id, video_w, video_h)
        return

    words = whisper_data.get("words", [])
    if not words:
        # Puede ser que el formato sea diferente (segments en vez de words top-level)
        segments = whisper_data.get("segments", [])
        for seg in segments:
            words.extend(seg.get("words", []))

    if not words:
        print("[generate_ass] No se encontraron palabras en WHISPER_RESULT", file=sys.stderr)
        write_empty_ass(output_path, style_id, video_w, video_h)
        return

    # --- Parsear keywords ---
    keywords_file = os.environ.get("KEYWORDS_FILE", "/tmp/keywords.json")
    if keywords_raw in ("[]", "", "null") and os.path.exists(keywords_file):
        with open(keywords_file, "r", encoding="utf-8") as f:
            keywords_raw = f.read()

    kw_set = load_keywords(keywords_raw)
    print(f"[generate_ass] Estilo: {style_id} | Palabras: {len(words)} | Keywords: {len(kw_set)}", file=sys.stderr)

    # --- Generar ASS ---
    s = STYLES[style_id]
    max_words = s["max_words"]

    header = build_ass_header(style_id, video_w, video_h)
    dialogue_lines = []

    for chunk in chunk_words(words, max_words):
        line = render_block(chunk, style_id, kw_set)
        if line:
            dialogue_lines.append(line)

    # --- Escribir archivo ---
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(dialogue_lines))
        if dialogue_lines:
            f.write("\n")

    print(f"[generate_ass] ✓ Escrito: {output_path} ({len(dialogue_lines)} líneas de diálogo)", file=sys.stderr)


if __name__ == "__main__":
    main()
