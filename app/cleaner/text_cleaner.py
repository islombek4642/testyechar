"""
Text cleaning and normalisation pipeline.

Transforms raw extracted text into a consistent format that the
parser can process reliably.  Each cleaning step is a small pure
function — easy to test, reorder, or extend.
"""

from __future__ import annotations

import re
import unicodedata

from app.utils.logger import get_logger

log = get_logger(__name__)

# ── Unicode normalisation maps ──────────────────────────────────────────
_QUOTE_MAP: dict[str, str] = {
    "\u2018": "'",  # LEFT SINGLE QUOTATION MARK
    "\u2019": "'",  # RIGHT SINGLE QUOTATION MARK
    "\u201a": "'",  # SINGLE LOW-9 QUOTATION MARK
    # U+201C/201D (curly double quotes) intentionally NOT normalised:
    # converting them to ASCII " causes \"...\" escaping in JSON preview,
    # making the output look garbled.  Kept as Unicode -- JSON handles them fine.
    "\u201e": '"',  # LOW-9 DOUBLE QUOTATION MARK (encoding artefact)
    "\u2039": "'",  # SINGLE LEFT-POINTING ANGLE QUOTATION MARK
    "\u203a": "'",  # SINGLE RIGHT-POINTING ANGLE QUOTATION MARK
    "\u00ab": '"',  # LEFT-POINTING DOUBLE ANGLE QUOTATION MARK
    "\u00bb": '"',  # RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK
}

_DASH_MAP: dict[str, str] = {
    "–": "-",  # en-dash
    "—": "-",  # em-dash
    "―": "-",  # horizontal bar
    "−": "-",  # minus sign
}

_SUPERSCRIPT_MAP: dict[str, str] = {}

_SUBSCRIPT_MAP: dict[str, str] = {}

# ── Regex helpers used by fix_broken_line_joins ─────────────────────────
_MATH_SYMBOLS: frozenset[str] = frozenset(
    # Mathematical Italic Greek small (α-ω variants)
    "\U0001D70B\U0001D719\U0001D6FC\U0001D6FD\U0001D6FE\U0001D6FF"
    "\U0001D700\U0001D702\U0001D703\U0001D706\U0001D707\U0001D708"
    "\U0001D709\U0001D70C\U0001D70E\U0001D70F\U0001D710\U0001D711"
    "\U0001D712\U0001D713\U0001D718"
    # Math operators and basic Greek
    "√∞∑∏∫∆∇"
    "πφαβγδεηθ"
    "λμνξρστχψω"
    # Mathematical Italic Small Latin a-z (𝑎-𝑧, U+1D44E-1D467, gap at 1D455)
    "\U0001D44E\U0001D44F\U0001D450\U0001D451\U0001D452\U0001D453\U0001D454"
    "\U0001D456\U0001D457\U0001D458\U0001D459\U0001D45A\U0001D45B\U0001D45C"
    "\U0001D45D\U0001D45E\U0001D45F\U0001D460\U0001D461\U0001D462\U0001D463"
    "\U0001D464\U0001D465\U0001D466\U0001D467"
)
_ARABIC_DIAC_CLASS = (
    '[' + chr(0x0610) + '-' + chr(0x061A)
    + chr(0x064B) + '-' + chr(0x065F)
    + chr(0x0670) + ']'
)
_ARABIC_DIAC_BEFORE_MARKER = re.compile(
    r'^' + _ARABIC_DIAC_CLASS + r'+\s*(?=[=+?#])',
    re.MULTILINE,
)
_TRAILING_OP = re.compile(r"[+\-\xD7\xF7*/=≤≥\xB1]\s*$")
_TEST_MARKER = re.compile(r"^[?+=#]")
# ABC option start: optional marker prefix then letter + ) or .
_ABC_OPT_START = re.compile(r"^[#*+=]?\s*[a-fA-F][\.\)]")
# Numbered question start: "257. Text…" / "257) Text…" — always begins a new
# question, never a wrapped continuation of a math expression.
_NUMBERED_ITEM_START = re.compile(r"^\d{1,4}[.\)]\s*\S")
# Blocks-format separators: 3+ identical = or + chars (e.g. ====, +++++).
# Must never be joined to the following line.
_BLOCKS_SEP = re.compile(r"^[=+]{3,}$")
_DIGIT_ONLY = re.compile(r"^\d{1,3}$")
_HAS_MATH_OP = re.compile(
    r"[+\-\xD7\xF7*/=√∞∑∏∫^"
    r"πφαβγδεηθ"
    r"λμνξρστχψω]"
)
# Inline fraction: "π 6" or "𝜋 6" → "π/6"
# Covers regular Greek (U+03B1-03C9), Mathematical Italic (U+1D6FC-1D714),
# and √.  PDF extractors sometimes output math-italic variants (𝜋, 𝛼…)
# instead of plain Greek.
_GREEK_MATH_CHAR = (
    r"[α-ωϕπφ√"                    # basic Greek + √
    r"\U0001D6FC-\U0001D714"        # 𝛼-𝜔 Math Italic small
    r"\U0001D736-\U0001D74E"        # 𝜶-𝝎 Math Bold Italic small
    r"\U0001D770-\U0001D788"        # 𝝰-𝞈 Math SansSerif Italic small
    r"]"
)
# Inline fraction: "π 6" or "𝜋 6" → "π/6".
# Group 1 = Greek/math char, Group 2 = denominator digits.
_INLINE_FRACTION = re.compile(
    r"(" + _GREEK_MATH_CHAR + r")\s{1,3}(\d{1,3})(?=[\s,;.!?)«»\"']|$)"
)


class TextCleaner:
    """
    Stateless text normalisation pipeline.

    Call :meth:`clean` with raw text and receive normalised text ready
    for the parser.  Individual steps are also available as static
    methods for unit testing.
    """

    # ── Pipeline entry point ────────────────────────────────────────────

    @classmethod
    def clean(cls, text: str) -> str:
        """
        Apply the full cleaning pipeline to *text*.

        Pipeline order matters — early steps simplify input for later ones.
        """
        if not text:
            return ""

        text = cls.normalize_unicode(text)
        text = cls.normalize_quotes(text)
        text = cls.normalize_dashes(text)
        text = cls.normalize_whitespace(text)
        text = cls.strip_arabic_diacritics_before_markers(text)
        text = cls.normalize_superscripts_subscripts(text)
        text = cls.fix_orphan_numerators(text)
        text = cls.fix_broken_line_joins(text)
        text = cls.fix_inline_fractions(text)
        text = cls.remove_bom(text)
        text = cls.strip_page_headers_footers(text)

        log.debug(f"Cleaned text: {len(text)} characters")
        return text

    # ── Individual cleaning steps ───────────────────────────────────────

    @staticmethod
    def normalize_unicode(text: str) -> str:
        """
        Apply NFC normalisation.

        NFC is the safest default — it composes combining characters so
        that Uzbek letters like «oʻ», «gʻ» and Cyrillic are preserved
        in their canonical composed form.
        """
        return unicodedata.normalize("NFC", text)

    @staticmethod
    def normalize_quotes(text: str) -> str:
        """Replace fancy/typographic quotes with ASCII equivalents."""
        for fancy, plain in _QUOTE_MAP.items():
            text = text.replace(fancy, plain)
        return text

    @staticmethod
    def normalize_dashes(text: str) -> str:
        """Replace unicode dashes with simple hyphens."""
        for fancy, plain in _DASH_MAP.items():
            text = text.replace(fancy, plain)
        return text

    @staticmethod
    def normalize_whitespace(text: str) -> str:
        """
        Collapse runs of spaces/tabs into a single space per line.

        Preserves newlines so the parser can iterate line-by-line.
        """
        lines = text.splitlines()
        cleaned: list[str] = []
        for line in lines:
            # collapse horizontal whitespace only
            line = re.sub(r"[ \t]+", " ", line)
            cleaned.append(line.strip())
        return "\n".join(cleaned)

    @staticmethod
    def strip_arabic_diacritics_before_markers(text: str) -> str:
        """
        Strip Arabic combining diacritical marks (kasra U+0650, fatha, etc.)
        from the start of lines when they precede a test marker (= + ? #).

        Arabic-content PDFs often place orphaned diacritics before the
        marker character, e.g. ``ِ=text`` instead of ``=text``, preventing
        the parser from recognizing option lines.
        """
        return _ARABIC_DIAC_BEFORE_MARKER.sub('', text)

    @staticmethod
    def normalize_superscripts_subscripts(text: str) -> str:
        """
        Pass Unicode superscript/subscript characters through unchanged.

        ² ³ ⁿ ₂ ₃ etc. are preserved as-is so the output matches
        the original mathematical notation from the source document.
        """
        for char, repl in _SUPERSCRIPT_MAP.items():
            text = text.replace(char, repl)
        for char, repl in _SUBSCRIPT_MAP.items():
            text = text.replace(char, repl)
        return text

    @staticmethod
    def fix_broken_line_joins(text: str) -> str:
        """
        Rejoin lines that were broken by PDF text extraction.

        Handles five cases in priority order:

        1. Math-symbol-only line + digit   ->  sym/digit        (existing)
        2. Digit-only + digit-only         ->  d1/d2  (fraction)  (new)
        3. Short math expression + digit   ->  expr/digit         (new)
        4. Line ending with math operator  ->  join with next     (new)
        5. Standard broken-word joining (lowercase -> lowercase)  (existing)

        Test markers (?, +, =) are never joined to prevent corrupting
        the parser's input format.
        """
        lines = text.split("\n")
        result: list[str] = []
        i = 0

        def _next_nonempty(idx: int) -> tuple[int, str]:
            j = idx + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            return (j, lines[j].strip()) if j < len(lines) else (-1, "")

        def _is_marker(s: str) -> bool:
            return bool(_TEST_MARKER.match(s))

        while i < len(lines):
            current = lines[i]
            cs = current.strip()

            if not cs:
                result.append(current)
                i += 1
                continue

            j, ns = _next_nonempty(i)

            # ── Case 0: Lone trailing "?" — sentence-ending question mark ──
            # PDF sometimes places the closing "?" of a question on its own
            # line. A bare "?" that is NOT preceded by a test-marker line is
            # the punctuation that ends the sentence — append it to cs.
            if (
                ns == "?"
                and not _is_marker(cs)
                and cs[-1:].isalpha()
            ):
                result.append(cs + " ?")
                i = j + 1
                continue

            # ── Case 1: Math-symbol-only line + digit denominator ──────────
            if (
                j >= 0
                and all(c in _MATH_SYMBOLS or c.isspace() for c in cs)
                and _DIGIT_ONLY.match(ns)
            ):
                result.append(cs + "/" + ns)
                i = j + 1
                continue

            # ── Case 1b: Marker-prefixed math symbol + denominator ───────────
            # Handles "= √2\n2" → "= √2/2" and "= 𝑏\n𝑐" → "= 𝑏/𝑐".
            # Denominator can be a digit OR a pure math-symbol expression
            # (e.g. another italic variable like 𝑐, or √3).
            _marker_m = re.match(r"^([+=]) +(.{1,25})$", cs)
            if _marker_m and j >= 0 and not _is_marker(ns):
                _content = _marker_m.group(2).strip()
                _has_math = (
                    any(c in _MATH_SYMBOLS for c in _content)
                    or bool(re.match(r"^-\d+$", _content))  # negative integer: -1, -2 …
                )
                _ns_is_digit = _DIGIT_ONLY.match(ns)
                _ns_is_math = (
                    all(c in _MATH_SYMBOLS or c.isspace() or c.isdigit() for c in ns)
                    and any(c in _MATH_SYMBOLS for c in ns)
                    and len(ns) <= 12
                )
                if _has_math and not _content.endswith("=") and (_ns_is_digit or _ns_is_math):
                    result.append(f"{_marker_m.group(1)} {_content}/{ns}")
                    i = j + 1
                    continue

            # ── Case 1c: Math-symbol numerator + "digit + rest-of-text" ──────
            # PDF stacked fractions in question text: "𝜋" + "4 necha gradusga"
            # → "𝜋/4 necha gradusga".  Triggered when cs consists only of
            # math/digit chars AND ns begins with a digit followed by text
            # (i.e., the denominator is embedded in the continuing sentence).
            _frac_text_m = re.match(r"^(\d{1,3})\s+(.+)$", ns)
            if (
                j >= 0
                and not _is_marker(cs)
                and all(c in _MATH_SYMBOLS or c.isspace() or c.isdigit() for c in cs)
                and any(c in _MATH_SYMBOLS for c in cs)
                and _frac_text_m
                and not _is_marker(ns)
                and len(ns) <= 120
            ):
                result.append(cs + "/" + _frac_text_m.group(1) + " " + _frac_text_m.group(2))
                i = j + 1
                continue

            # ── Case 1d: Lone question marker + stacked fraction question ──────
            # "?" alone + "𝜋" + "4 necha gradusga" → "? 𝜋/4 necha gradusga".
            # Look two lines ahead to handle question marker separated from its
            # fraction numerator.
            _lone_q_m = re.match(r"^(\?+)$", cs)
            if _lone_q_m and j >= 0:
                k, nns = _next_nonempty(j)
                if (
                    k >= 0
                    and all(c in _MATH_SYMBOLS or c.isspace() or c.isdigit() for c in ns)
                    and any(c in _MATH_SYMBOLS for c in ns)
                    and not _is_marker(ns)
                ):
                    _nns_frac = (
                        re.match(r"^(\d{1,3})\s+(.+)$", nns)
                        or re.match(r"^_\{(\d{1,3})\}\s+(.+)$", nns)
                    )
                    if _nns_frac and not _is_marker(nns):
                        result.append(
                            _lone_q_m.group(1) + " " + ns + "/"
                            + _nns_frac.group(1) + " " + _nns_frac.group(2)
                        )
                        i = k + 1
                        continue

            # ── Case 1e: Lone answer marker + numerator + math denominator ─────
            # "=" + "1" + "√3" → "= 1/√3"   (e.g. tg30° = 1/√3)
            # "=" + "𝑏" + "𝑐" → "= 𝑏/𝑐"   (trig ratio b/c)
            _lone_ans = re.match(r"^([+=])$", cs)
            if _lone_ans and j >= 0 and not _is_marker(ns):
                _ns_is_num = (
                    _DIGIT_ONLY.match(ns)
                    or (
                        all(c in _MATH_SYMBOLS or c.isspace() for c in ns)
                        and any(c in _MATH_SYMBOLS for c in ns)
                        and len(ns.strip()) <= 6
                    )
                )
                if _ns_is_num:
                    k, nns = _next_nonempty(j)
                    if (
                        k >= 0
                        and all(c in _MATH_SYMBOLS or c.isspace() or c.isdigit() for c in nns)
                        and any(c in _MATH_SYMBOLS for c in nns)
                        and not _is_marker(nns)
                    ):
                        result.append(_lone_ans.group(1) + " " + ns.strip() + "/" + nns.strip())
                        i = k + 1
                        continue

            # ── Case 1f: Answer marker with trailing sign + fraction ────────
            # "= -" + "1" + "2"  → "= -1/2"   (negative integer fraction)
            # "= -" + "1" + "√3" → "= -1/√3"  (negative radical fraction)
            _trailing_sign = re.match(r"^([+=]\s*[-+])$", cs)
            if (
                _trailing_sign and j >= 0
                and not _is_marker(ns)
                and re.match(r"^\d", ns)
            ):
                k, nns = _next_nonempty(j)
                _nns_is_denom = k >= 0 and not _is_marker(nns) and (
                    bool(_DIGIT_ONLY.match(nns))
                    or (
                        all(c in _MATH_SYMBOLS or c.isspace() or c.isdigit() for c in nns)
                        and any(c in _MATH_SYMBOLS for c in nns)
                        and len(nns) <= 12
                    )
                )
                # Three-line case: sign + digit + denominator → sign+digit/denom
                if _DIGIT_ONLY.match(ns) and _nns_is_denom:
                    result.append(_trailing_sign.group(0).rstrip() + ns + "/" + nns)
                    i = k + 1
                else:
                    # Two-line case: "= -" + "1/2" → "= -1/2"
                    result.append(_trailing_sign.group(0).rstrip() + ns)
                    i = j + 1
                continue

            # ── Case 2: Digit/digit fraction ────────────────────────────────
            # Two consecutive standalone numbers -> fraction (3\n4 -> 3/4).
            # Capped at 3 digits each to avoid merging large unrelated numbers.
            if (
                j >= 0
                and _DIGIT_ONLY.match(cs)
                and _DIGIT_ONLY.match(ns)
                and not _is_marker(ns)
            ):
                result.append(cs + "/" + ns)
                i = j + 1
                continue

            # ── Case 3: Short math expression + digit denominator ──────────
            # Handles cases like "a + b\n c" -> "a + b/c" where a fraction
            # numerator contains operators or Greek/math symbols.
            # Guard: skip lone "=" or "+" (handled by Case 1e above) and
            # expressions ending with "=" (right-side fraction, needs look-ahead).
            if (
                j >= 0
                and not _is_marker(cs)
                and not re.match(r"^[+=]$", cs)
                and len(cs) <= 25
                and _HAS_MATH_OP.search(cs)
                and _DIGIT_ONLY.match(ns)
                and cs[-1:] not in ".!?:;="
            ):
                result.append(cs + "/" + ns)
                i = j + 1
                continue

            # ── Case 3h: Line ending with "math+digit" + "digit + text" ─────────
            # PDF stacked fractions inside question text where the numerator is
            # the last token of a longer line:
            #   "? Agar sinα= √3" + "2 va ..." → "? Agar sinα= √3/2 va ..."
            #   "? Agar sinα= -√3" + "2 va ..." → "? Agar sinα= -√3/2 va ..."
            # Guard: last char is a digit AND the last few chars contain a math
            # symbol (distinguishes "√3" from bare numbers like "12").
            _frac_cont_m = re.match(r"^(\d{1,3})\s+(.+)$", ns)
            if (
                j >= 0
                and cs[-1:].isdigit()
                and any(c in _MATH_SYMBOLS for c in cs[-6:])
                and _frac_cont_m
                and not _is_marker(ns)
                and len(ns) <= 120
            ):
                result.append(
                    cs + "/" + _frac_cont_m.group(1) + " " + _frac_cont_m.group(2)
                )
                i = j + 1
                continue

            # ── Case 3g: Line ending with "=" + digit numerator + denominator ──
            # Handles stacked fractions where the LHS ends with "=":
            #   "? Agar sinα=" + "1" + "2 va ..." → "? Agar sinα= 1/2 va ..."
            #   "= 1 + tg²α=" + "1" + "cos²α"    → "= 1 + tg²α= 1/cos²α"
            # Guard: skip Blocks separators (==== is NOT a fraction context).
            if (
                j >= 0
                and cs.endswith("=")
                and not _BLOCKS_SEP.match(cs)
                and _DIGIT_ONLY.match(ns)
                and not _is_marker(ns)
            ):
                k, nns = _next_nonempty(j)
                if k >= 0 and not _is_marker(nns):
                    _num_rest = re.match(r"^(\d{1,3})\s+(.+)$", nns)
                    if _num_rest:
                        result.append(
                            cs + " " + ns + "/" + _num_rest.group(1)
                            + " " + _num_rest.group(2)
                        )
                    else:
                        result.append(cs + " " + ns + "/" + nns)
                    i = k + 1
                    continue

            # ── Case 4: Line ending with math operator ───────────────────────
            # Handles "2x +\n3y" -> "2x + 3y" and "sin(x) =\n0" -> "sin(x) = 0".
            # Never joins Blocks separators (====, +++++) or test marker lines.
            # Also never joins when the next line is an ABC option (a), *b), #c))
            # to prevent merging question-ending "-" with option lines, nor when
            # it's a numbered question ("257. Text…") — a genuine wrapped math
            # continuation never starts a fresh numbered item; joining onto one
            # glues a whole question (and its options) onto the previous option
            # (e.g. ABC option "d) -" + "257. Never turn…" -> "d) - 257. Never turn…").
            if (
                j >= 0
                and _TRAILING_OP.search(cs)
                and not _is_marker(cs)
                and not _is_marker(ns)
                and not _BLOCKS_SEP.match(cs)
                and not _BLOCKS_SEP.match(ns)
                and not _ABC_OPT_START.match(ns)
                and not _NUMBERED_ITEM_START.match(ns)
            ):
                result.append(cs + " " + ns)
                i = j + 1
                continue

            # ── Case 4b: Trig double-angle formula fraction ──────────────────
            # PDF stacks "2𝑡𝑔15°" on one line and "1-𝑡𝑔²15°" on the next.
            # Both end with ° and denominator starts with "1-".
            # "2𝑡𝑔15°" + "1-𝑡𝑔215°" → "2𝑡𝑔15°/1-𝑡𝑔215°"
            if (
                j >= 0
                and cs.endswith("°")
                and not _is_marker(cs)
                and not _is_marker(ns)
                and re.match(r"^1[-−]", ns)
                and ns.endswith("°")
            ):
                result.append(cs + "/" + ns)
                i = j + 1
                continue

            # ── Case 5: Standard broken-word joining ─────────────────────────
            # Guard: never join when either line is an ABC option (a), *b) …)
            # to prevent merging separate options or question text with options.
            if (
                j >= 0
                and cs
                and cs[-1:].islower()
                and ns
                and ns[0:1].islower()
                and not _is_marker(ns)
                and not _BLOCKS_SEP.match(cs)
                and not _BLOCKS_SEP.match(ns)
                and not _ABC_OPT_START.match(cs)
                and not _ABC_OPT_START.match(ns)
            ):
                result.append(cs + " " + ns)
                i = j + 1
            else:
                result.append(current)
                i += 1

        return "\n".join(result)

    @staticmethod
    def fix_orphan_numerators(text: str) -> str:
        """
        Merge lone-digit numerator lines that are sandwiched between a
        preceding context line (ending with letter or '=') and a denominator
        line (starting with digit + text):

            "??...sinusi"           "? ...sinα="
            "2"              →      "1"
            "5 ga teng..."          "3 ga teng..."

        Becomes: "??...sinusi 2/5 ga teng..." / "? ...sinα= 1/3 ga teng..."
        """
        _LONE_DIGIT = re.compile(r"^\d{1,3}$")
        _DENOM = re.compile(r"^(\d{1,3})\s*(.*)", re.DOTALL)

        lines = text.split("\n")
        out: list[str] = []
        i = 0

        def _next_nonempty_idx(start: int) -> int:
            j = start + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            return j if j < len(lines) else -1

        while i < len(lines):
            cs = lines[i].strip()

            if not cs:
                out.append(lines[i])
                i += 1
                continue

            # Detect: current line = lone digit numerator
            if _LONE_DIGIT.match(cs):
                # Check the PREVIOUS non-empty output line
                prev_idx = len(out) - 1
                while prev_idx >= 0 and not out[prev_idx].strip():
                    prev_idx -= 1
                prev = out[prev_idx].strip() if prev_idx >= 0 else ""

                # Previous must end with letter or '=' (fraction context)
                if prev and (prev[-1:].islower() or prev[-1:] == "="):
                    # Next non-empty line should start with digit (denominator)
                    j = _next_nonempty_idx(i)
                    if j >= 0:
                        nns = lines[j].strip()
                        dm = _DENOM.match(nns)
                        if dm and (dm.group(2) or True):  # denominator line
                            denom = dm.group(1)
                            rest = dm.group(2).strip()
                            # Re-write the previous output line with fraction merged
                            base = out[prev_idx]
                            merged = base.rstrip() + " " + cs + "/" + denom
                            if rest:
                                merged += " " + rest
                            out[prev_idx] = merged
                            # Skip: current (numerator) + any blanks + denominator line
                            i = j + 1
                            continue

            out.append(lines[i])
            i += 1

        return "\n".join(out)

    @staticmethod
    def fix_inline_fractions(text: str) -> str:
        """
        Restore missing slash in same-line fractions extracted without it.

        PDF/DOCX extractors sometimes give "π 6" instead of "π/6" when the
        fraction bar is a visual element rather than a text character.
        Pattern: Greek/math char + spaces + short number → insert slash.

        Examples:
            "= π 6"  -> "= π/6"
            "2π 3"   -> "2π/3"
            "√ 2"    -> "√/2"  (rare, but consistent)
        """
        return _INLINE_FRACTION.sub(r"\1/\2", text)

    @staticmethod
    def remove_bom(text: str) -> str:
        """Strip UTF-8 BOM if present."""
        return text.lstrip("﻿")

    @staticmethod
    def strip_page_headers_footers(text: str) -> str:
        """
        Remove common page-number patterns and repeated headers.

        This is a best-effort heuristic — PDF generators often inject
        page numbers like «12» or «- 12 -» on standalone lines.
        """
        lines = text.split("\n")
        cleaned: list[str] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            # Skip lines that are just a page number
            if re.fullmatch(r"-?\s*\d{1,4}\s*-?", stripped):
                # Safe check: if this numeric line is preceded or followed by:
                #   • Blocks separators (=== or +++) — at least 3 chars
                #   • Classic format markers (=, +, ?) — single char
                # then it is a valid numeric test answer, not a page number!
                is_test_structure = False

                _CLASSIC_MARKERS = {"=", "+", "?"}

                def _is_test_line(ln: str) -> bool:
                    s = ln.strip()
                    if not s:
                        return False
                    # Blocks separators (===, +++)
                    if len(s) >= 3 and (all(c == "=" for c in s) or all(c == "+" for c in s)):
                        return True
                    # Classic single-char markers (=answer, +answer, ?question)
                    if s[0] in _CLASSIC_MARKERS:
                        return True
                    return False

                # Check line before
                if idx > 0 and _is_test_line(lines[idx - 1]):
                    is_test_structure = True

                # Check line after
                if idx < len(lines) - 1 and _is_test_line(lines[idx + 1]):
                    is_test_structure = True

                if is_test_structure:
                    cleaned.append(line)
                    continue

                continue
            cleaned.append(line)
        return "\n".join(cleaned)
