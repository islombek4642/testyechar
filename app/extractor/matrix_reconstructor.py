"""
PDF sahifalaridagi matritsalarni qator/ustun tartibida tiklovchi modul.

Muammo: PyMuPDF matnni qator-qator (vizual asosda) o'qiydi. Lekin
matritsalar PDF'da 2 o'lchovli "to'r" ko'rinishida joylashadi —
masalan

    A = (1  1)
        (1  1)

Bunday joy oddiy matn sifatida olinganda qator/ustun tartibi yo'qolib,
elementlar tartibsiz ketma-ketlikka aylanib qoladi:

    𝐴= (1
    1
    1
    1)

Bu modul har bir raqamning sahifadagi (x, y) koordinatasidan foydalanib
(``page.get_text("rawdict")`` orqali belgi darajasida), asl qator/ustun
joylashuvini geometrik tarzda qayta tiklaydi va uni bitta aniq, izchil
yozuvga keltiradi:

    (1 1; 1 1)        — 2x2:  [[1, 1], [1, 1]]
    (1 0 0; 0 1 0; 0 0 1)   — 3x3 birlik matritsa

Qatorlar ";" bilan, ustunlar bo'sh joy bilan ajratiladi — bu yagona,
chalkashmaydigan yozuv (matematikada keng qo'llanadigan
MATLAB/Octave uslubi bilan bir xil).

Eslatma: faqat KAMIDA 2 QATORLI to'rlar "matritsa" deb hisoblanadi.
Bitta qatorli qator-vektorlar (masalan "(2 1)") oddiy matn sifatida
ham to'g'ri chiqadi — ularga maxsus tiklash shart emas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import fitz  # PyMuPDF

from app.utils.logger import get_logger

log = get_logger(__name__)

# ── Geometrik chegaralar ────────────────────────────────────────────────
# Quyidagi qiymatlar PDF'dagi haqiqiy matritsalarning belgi-koordinatalarini
# o'lchab kalibrlangan (12pt shrift asosida):
#   - bir xil qatordagi belgilarning y0-farqi  ≈ 0.0   (qatorlar orasi ≈ 10-16)
#   - bitta son ichidagi belgilar orasi (gap)  ≈ 0.0   (ustunlar orasi ≈ 16)
_ROW_TOLERANCE = 3.0     # shundan kichik y0-farq -> bir xil qator
_TOKEN_GAP = 3.0         # shundan katta x-bo'shliq -> yangi son (ustun)
_OPEN_BRACKETS = "(["
_CLOSE_FOR = {"(": ")", "[": "]"}
_BRACKET_CHARS = "()[]"
_MAX_LOOKAHEAD = 400     # bitta qavs ichida qaralishi mumkin bo'lgan belgilar soni


_SIZE_TOLERANCE = 0.5    # bundan katta shrift-o'lcham farqi -> indeks/daraja (subscript), matritsa EMAS
_MAX_TOKEN_LEN = 6       # matritsa elementi uzunligi chegarasi (masalan "-1234")
_MAX_LETTERS = 2         # elementda ruxsat etilgan harflar soni (qisqa o'zgaruvchi: 𝑥, 𝛼, 𝑎𝑏)


@dataclass
class _Glyph:
    char: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float


@dataclass
class MatrixGrid:
    """Sahifadan aniqlangan bitta matritsa: tor (qator-ustun) va render natijasi."""

    bbox: tuple[float, float, float, float]
    rows: list[list[str]]        # [[qator1ustun1, qator1ustun2, ...], [qator2...], ...]
    flat_values: list[str]       # ekstraksiyada paydo bo'lish tartibida (qator-ustun)
    rendered: str                # masalan "(-1 1; 4 -2)"

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.rows), len(self.rows[0]) if self.rows else 0)


# ── Sahifani belgi darajasida o'qish ────────────────────────────────────

def _page_glyphs(page: fitz.Page) -> list[_Glyph]:
    """Sahifadagi belgilarni (bo'sh joylardan tashqari) o'qish tartibida qaytaradi."""
    glyphs: list[_Glyph] = []
    raw = page.get_text("rawdict")
    for block in raw.get("blocks", []):
        if block.get("type") != 0:  # rasm bloklarini o'tkazib yuboramiz
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                size = span.get("size", 0.0)
                for ch in span.get("chars", []):
                    if ch["c"].strip():
                        x0, y0, x1, y1 = ch["bbox"]
                        glyphs.append(_Glyph(ch["c"], x0, y0, x1, y1, size))
    return glyphs


# ── Qator/ustunlarni geometrik tiklash ──────────────────────────────────

def _cluster_rows(glyphs: list[_Glyph]) -> list[list[_Glyph]]:
    """Belgilarni y0 koordinatasi bo'yicha vizual qatorlarga guruhlaydi."""
    rows: list[list[_Glyph]] = []
    for g in sorted(glyphs, key=lambda g: g.y0):
        if rows and abs(rows[-1][0].y0 - g.y0) <= _ROW_TOLERANCE:
            rows[-1].append(g)
        else:
            rows.append([g])
    return rows


def _row_to_tokens(row: list[_Glyph]) -> list[str]:
    """Bitta qatordagi belgilarni x0 bo'yicha tartiblab, sonlarga (tokenlarga) yig'adi."""
    tokens: list[str] = []
    cur = ""
    prev_x1: float | None = None
    for g in sorted(row, key=lambda g: g.x0):
        if prev_x1 is not None and (g.x0 - prev_x1) > _TOKEN_GAP:
            tokens.append(cur)
            cur = ""
        cur += g.char
        prev_x1 = g.x1
    if cur:
        tokens.append(cur)
    return tokens


def _looks_like_matrix_element(token: str) -> bool:
    """
    Bitta katakcha (element) matritsaga xos ko'rinishdami — son, ishora yoki
    qisqa o'zgaruvchi (𝑥, 𝛼, 𝑎𝑏)? Yoki bu oddiy SO'Z (qavs ichiga olingan,
    ko'p qatorga o'ralib ketgan matn bo'lagi)?

    Bu tekshiruv juda muhim: aks holda "(кайси гап булаклари; бош...)" kabi
    qavs ichida o'ralib qolgan oddiy gaplarni ham "matritsa" deb
    aniqlab, ularni bemalol buzib qo'yish xavfi bor edi.
    """
    if not token or len(token) > _MAX_TOKEN_LEN:
        return False
    letters = sum(1 for c in token if c.isalpha())
    digits = sum(1 for c in token if c.isdigit())
    if letters == 0 and digits == 0:
        return False
    return letters <= _MAX_LETTERS


def _looks_like_matrix(token_rows: list[list[str]]) -> bool:
    """Butun to'rning HAR BIR katakchasi matritsa elementiga o'xshashmi?"""
    return all(
        _looks_like_matrix_element(tok) for row in token_rows for tok in row
    )


def find_matrices(page: fitz.Page) -> list[MatrixGrid]:
    """
    Sahifadagi qavs ichiga olingan, kamida 2 qatorli sonlar to'rlarini (matritsalarni)
    aniqlaydi va ularning asl qator/ustun joylashuvini geometrik tarzda tiklaydi.

    Faqat barcha qatorlarida USTUNLAR SONI BIR XIL bo'lgan to'g'ri to'rtburchak
    to'rlar "matritsa" deb qabul qilinadi — aks holda (masalan tasodifiy qavs
    ichidagi ko'p qatorli matn) e'tiborga olinmaydi, asl matn o'zgarishsiz qoladi.
    """
    glyphs = _page_glyphs(page)
    matrices: list[MatrixGrid] = []
    i, n = 0, len(glyphs)

    while i < n:
        g = glyphs[i]
        if g.char in _OPEN_BRACKETS:
            close_char = _CLOSE_FOR[g.char]
            j = i + 1
            limit = min(n, i + 1 + _MAX_LOOKAHEAD)
            while j < limit and glyphs[j].char != close_char:
                j += 1

            if j < limit:
                inner = glyphs[i + 1:j]
                content = [c for c in inner if c.char not in _BRACKET_CHARS]

                # Indeks/daraja (subscript/superscript) bo'lgan ifodalar — masalan
                # "(𝐴𝑖)" yoki "(𝑥0)" — kichikroq shriftli belgidan iborat bo'ladi.
                # Bunday holatlar 2 "qator"ga o'xshab ko'rinishi mumkin, lekin
                # ular matritsa EMAS — shrift o'lchami bir xil bo'lmagani uchun
                # rad etamiz.
                uniform_size = (
                    bool(content)
                    and (max(c.size for c in content) - min(c.size for c in content))
                    <= _SIZE_TOLERANCE
                )
                rows = _cluster_rows(content) if (content and uniform_size) else []

                if len(rows) >= 2:
                    token_rows = [_row_to_tokens(r) for r in rows]
                    col_counts = {len(t) for t in token_rows}
                    if (
                        len(col_counts) == 1
                        and 0 not in col_counts
                        and _looks_like_matrix(token_rows)
                    ):
                        whole = [g, *inner, glyphs[j]]
                        bbox = (
                            min(c.x0 for c in whole),
                            min(c.y0 for c in whole),
                            max(c.x1 for c in whole),
                            max(c.y1 for c in whole),
                        )
                        rendered = (
                            g.char
                            + "; ".join(" ".join(row) for row in token_rows)
                            + close_char
                        )
                        matrices.append(
                            MatrixGrid(
                                bbox=bbox,
                                rows=token_rows,
                                flat_values=[v for row in token_rows for v in row],
                                rendered=rendered,
                            )
                        )
                        log.debug(
                            f"Matritsa topildi: {len(token_rows)}x{len(token_rows[0])} "
                            f"-> {rendered}"
                        )
                        i = j  # shu qavs blokidan o'tib ketamiz (ichma-ich qidirmaymiz)
        i += 1

    return matrices


# ── Matnga splайс qilish (almashtirish) ─────────────────────────────────

def _value_pattern(value: str) -> str:
    return re.escape(value)


def fix_matrices_in_text(page: fitz.Page, text: str) -> tuple[str, list[str]]:
    """
    `text` (shu sahifadan olingan tekis matn) ichidagi tartibsiz matritsa
    fragmentlarini sahifa geometriyasidan tiklangan aniq ko'rinish bilan
    almashtiradi.

    Qiymatlar orasidagi naqsh "\\D*?" (lazy, faqat raqam BO'LMAGAN belgilar)
    bo'lgani uchun, qatorlar orasidagi probel/yangi-qator/qavslar e'tiborga
    olinmaydi-yu, lekin boshqa raqamlar bilan adashtirib yubormaydi.

    Qaytaradi: (tuzatilgan matn, har bir almashtirish haqida hisobot qatorlari).
    """
    matrices = find_matrices(page)
    if not matrices:
        return text, []

    report: list[str] = []
    cursor = 0
    out: list[str] = []

    for m in matrices:
        open_char = m.rendered[0]
        close_char = m.rendered[-1]
        pattern = re.compile(
            re.escape(open_char)
            + r"\s*"
            + r"\D*?".join(_value_pattern(v) for v in m.flat_values)
            + r"\s*"
            + re.escape(close_char)
        )
        match = pattern.search(text, cursor)
        if not match:
            report.append(
                f"OGOHLANTIRISH: {m.shape[0]}x{m.shape[1]} matritsa {m.flat_values} "
                f"matnda topilmadi — o'tkazib yuborildi"
            )
            continue

        out.append(text[cursor:match.start()])
        out.append(m.rendered)
        report.append(
            f"TIKLANDI ({m.shape[0]}x{m.shape[1]}): "
            f"{match.group(0)!r} -> {m.rendered!r}"
        )
        cursor = match.end()

    out.append(text[cursor:])
    return "".join(out), report


# ── To'g'ridan-to'g'ri ishga tushirish: tekshirish va hisobot ───────────

def main() -> None:
    """PDF ustida ishlab, har bir sahifadagi matritsalarni topadi, tiklaydi
    va natijani tekshirib, hisobot chiqaradi."""
    from pathlib import Path

    pdf_path = Path(r"D:\TESTLAR\yangi format\Numerical methods II_UZ_2025-2026_talabalarga.pdf")
    out_path = Path(r"D:\PDF test\nm_matrices_fixed_sample.txt")

    doc = fitz.open(str(pdf_path))
    print(f"=== {pdf_path.name} ({doc.page_count} bet) ===\n")

    total_found = total_fixed = total_warned = 0
    sample_chunks: list[str] = []

    for pno in range(doc.page_count):
        page = doc[pno]
        original = page.get_text("text")
        matrices = find_matrices(page)
        if not matrices:
            continue

        fixed, report = fix_matrices_in_text(page, original)
        n_fixed = sum(1 for r in report if r.startswith("TIKLANDI"))
        n_warn = sum(1 for r in report if r.startswith("OGOHLANTIRISH"))
        total_found += len(matrices)
        total_fixed += n_fixed
        total_warned += n_warn

        print(f"--- {pno + 1}-bet: {len(matrices)} ta matritsa topildi ---")
        for r in report:
            print(f"   {r}")

        sample_chunks.append(f"\n========== PAGE {pno + 1} ==========\n{fixed}")

    out_path.write_text("".join(sample_chunks), encoding="utf-8")

    print()
    print("=== YAKUNIY HISOBOT ===")
    print(f"Jami topilgan matritsalar: {total_found}")
    print(f"  -> tiklanib, matnga joylashtirildi: {total_fixed}")
    print(f"  -> matnda mos joyi topilmay o'tkazib yuborildi: {total_warned}")
    print(f"\nMatritsalar tiklangan namunaviy fayl yozildi: {out_path}")

    doc.close()


if __name__ == "__main__":
    main()
