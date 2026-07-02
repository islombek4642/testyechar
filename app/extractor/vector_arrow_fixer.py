"""
PDF sahifalaridagi vektor-strelka belgilarini (combining arrow, U+20D7)
to'g'ri harfiga ulovchi modul.

Muammo: ba'zi PDF'larda (CambriaMath shrifti bilan yaratilgan formulalar,
masalan $\\vec{a}$, $\\vec{i}$ kabi vektor yozuvlari) strelka aksenti
harfning o'zidan ALOHIDA glif(lar) sifatida joylashtirilgan — ba'zan
bitta vizual strelka bir nechta ustma-ust strelka-glif bilan chizilgan.
PyMuPDF buni qator-qator matnga aylantirganda ikki xil nuqson paydo bo'ladi:

  1. TAKRORLANGAN strelka — bitta harfdan keyin bir nechta strelka belgisi
     ketma-ket kelib qoladi (vizual jihatdan bittagina aksent edi):

         𝑏⃗⃗(1; −1; 4)        ->   𝑏⃗(1; −1; 4)
         …4𝑘⃗⃗                ->   …4𝑘⃗

  2. "YETIM" strelka — strelka glifi o'z harfidan butunlay ajralib,
     hatto KEYINGI QATORGA o'tib qoladi. Sababi: aksent boshqa
     baseline'da chizilgani uchun PyMuPDF uni alohida "qator" deb
     hisoblaydi va asl (bitta) qatorni ikkiga bo'lib yuboradi:

         =  5𝑖
         ⃗⃗⃗⃗+ 3𝑗⃗−4𝑘⃗⃗

     bo'lishi kerak edi:

         =  5𝑖⃗+ 3𝑗⃗−4𝑘⃗

Bu modul avval sahifa belgi-geometriyasidan ("rawdict") foydalanib,
sahifada chinakam shunday "yetim strelka" muammosi bor-yo'qligini
tekshiradi (strelkasiz va muammosiz sahifalarga umuman tegmaydi),
so'ngra matnni ikki bosqichda tuzatadi: avval ortiqcha takrorlarni
bittaga qisqartiradi, keyin qatorlarga bo'linib qolgan strelkalarni
asl harfiga ulab, ikki qatorni qaytadan bitta qatorga birlashtiradi.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import fitz  # PyMuPDF

from app.utils.logger import get_logger

log = get_logger(__name__)

_ARROW = "⃗"  # COMBINING RIGHT ARROW ABOVE — vektor belgisi aksenti

# Strelka bo'la olmaydigan, raqam ham bo'lmagan harf — vektor NOMI
# (𝑎, 𝑏, 𝑖, 𝑗, 𝑘 …); koeffitsient sifatidagi raqamlar (masalan "5"da "5")
# strelka "egasi" bo'la olmaydi — vektor nomi har doim HARF bo'ladi.
_LETTER = r"[^\W\d_" + _ARROW + r"]"

# Vektor "nomi" — harf bilan boshlanib, unga yopishgan pastki indeks
# raqamlari bilan davom etishi mumkin (masalan nuqta nomlari 𝐴1, 𝐴2 dagi
# kabi "𝐴1𝐴2" — vektor 𝐴₁𝐴₂ uchun strelka oxirgi belgi "2" ustiga
# tushadi). Diqqat: bu "raqam HARFdan KEYIN" qoidasi — shu bois "5𝑖" dagi
# "5" kabi OLDIN turuvchi koeffitsientlar bunga kirmaydi (ular HARF bilan
# boshlanmagani uchun mosligi yo'q) — strelka faqat "𝑖"ga ulanadi.
#
# MUHIM: bu yerga keladigan `text` — xom sahifa matni emas, balki
# PDFExtractor._spans_to_text allaqachon ishlov bergan natija. U pastki
# indeks holatidagi kichik shriftli raqamlarni (masalan "𝐴1" dagi
# kichkina "1"ni) "𝐴_{1}" kabi LaTeX yozuviga aylantirib ulguradi —
# demak nuqta nomlari bu yerga "𝐴1𝐴2" emas, balki "𝐴_{1}𝐴_{2}"
# ko'rinishida keladi. Host naqshi buni ham tan olishi kerak, aks holda
# bunday kompozit nomlarning oxiriga ulangan strelkalar aniqlanmay qoladi.
_SUBSCRIPT = r"(?:_\{[^{}\n]*\})"
_HOST = r"(?:" + _LETTER + r"(?:\d|" + _SUBSCRIPT + r")*)"

# Bitta vektor-nomidan keyin 2 yoki undan ko'p strelka -> bitta strelkaga
# qisqartiramiz (vizual jihatdan bittagina aksent, glif darajasida takrorlangan)
_DUPLICATE_RE = re.compile(r"(" + _HOST + r")" + _ARROW + r"{2,}")

# Qator oxiridagi vektor-nomi + qator ko'chirish + qator boshidagi "yetim"
# strelka(lar) -> ikki qatorni birlashtirib, strelkani nomga ulaymiz
_SPLIT_LINE_RE = re.compile(r"(" + _HOST + r")\n" + _ARROW + r"+")

_HOST_RE = re.compile(r"[^\W\d_]")  # harf (raqam/strelka/pastki chiziq emas)


@dataclass
class _Glyph:
    char: str
    x0: float
    y0: float
    x1: float
    y1: float


def _page_glyphs(page: fitz.Page) -> list[_Glyph]:
    """Sahifadagi belgilarni (bo'sh joylardan tashqari) o'qish tartibida qaytaradi."""
    glyphs: list[_Glyph] = []
    raw = page.get_text("rawdict")
    for block in raw.get("blocks", []):
        if block.get("type") != 0:  # rasm bloklarini o'tkazib yuboramiz
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    if ch["c"].strip():
                        x0, y0, x1, y1 = ch["bbox"]
                        glyphs.append(_Glyph(ch["c"], x0, y0, x1, y1))
    return glyphs


def _has_orphan_arrows(glyphs: list[_Glyph]) -> bool:
    """
    Sahifada o'qish tartibida o'zidan oldin harf kelmagan strelka glyifi
    bormi? Aynan shu holatda (qator boshida yoki takrorlangan holda)
    matn buzilishi yuz beradi — faqat shunday sahifalardagina ishlaymiz.
    """
    for i, g in enumerate(glyphs):
        if g.char != _ARROW:
            continue
        prev = glyphs[i - 1] if i > 0 else None
        if prev is None or prev.char == _ARROW or not _HOST_RE.match(prev.char):
            return True
    return False


def fix_vector_arrows(page: fitz.Page, text: str) -> tuple[str, list[str]]:
    """
    Sahifa matnidagi vektor-strelka (U+20D7) nuqsonlarini tuzatadi:

      1. bitta harfdan keyin takrorlangan strelkalarni bittaga qisqartiradi;
      2. qatorga bo'linib ketgan "yetim" strelkalarni asl harfiga ulab,
         ikki qatorni qaytadan bitta (asl) qatorga birlashtiradi.

    Faqat sahifada geometrik tarzda "yetim strelka" aniqlangandagina
    ishlaydi — strelkasiz yoki muammosiz sahifalar matni o'zgarishsiz
    qaytadi.

    Qaytaradi: (tuzatilgan matn, har bir o'zgarish haqidagi hisobot qatorlari).
    """
    if _ARROW not in text:
        return text, []

    glyphs = _page_glyphs(page)
    if not _has_orphan_arrows(glyphs):
        return text, []

    report: list[str] = []

    def _collapse(m: re.Match) -> str:
        fixed_piece = m.group(1) + _ARROW
        report.append(f"TAKRORLANGAN STRELKA qisqartirildi: {m.group(0)!r} -> {fixed_piece!r}")
        return fixed_piece

    def _merge(m: re.Match) -> str:
        fixed_piece = m.group(1) + _ARROW
        report.append(f"QATOR BIRLASHTIRILDI (yetim strelka ulandi): {m.group(0)!r} -> {fixed_piece!r}")
        return fixed_piece

    # Avval takrorlarni qisqartiramiz — shunda qator-birlashtirish bosqichi
    # to'g'ri (allaqachon yagona) strelka bilan ishlaydi.
    fixed = _DUPLICATE_RE.sub(_collapse, text)
    fixed = _SPLIT_LINE_RE.sub(_merge, fixed)

    return fixed, report


# ── To'g'ridan-to'g'ri ishga tushirish: tekshirish va hisobot ───────────

def main() -> None:
    """PDF ustida ishlab, har bir sahifadagi vektor-strelka nuqsonlarini
    topadi, tuzatadi va natijani tekshirib, hisobot chiqaradi."""
    from pathlib import Path

    pdf_path = Path(r"D:\TESTLAR\yangi format\Numerical methods II_UZ_2025-2026_talabalarga.pdf")
    out_path = Path(r"D:\PDF test\nm_vectors_fixed_sample.txt")

    doc = fitz.open(str(pdf_path))
    print(f"=== {pdf_path.name} ({doc.page_count} bet) ===\n")

    total_changes = 0
    sample_chunks: list[str] = []

    for pno in range(doc.page_count):
        page = doc[pno]
        original = page.get_text("text")
        if _ARROW not in original:
            continue

        fixed, report = fix_vector_arrows(page, original)
        if report:
            total_changes += len(report)
            print(f"--- {pno + 1}-bet: {len(report)} ta tuzatish ---")
            for r in report:
                print(f"   {r}")
            sample_chunks.append(f"\n========== PAGE {pno + 1} ==========\n{fixed}")

    out_path.write_text("".join(sample_chunks), encoding="utf-8")

    print()
    print("=== YAKUNIY HISOBOT ===")
    print(f"Jami tuzatishlar: {total_changes}")
    print(f"\nNamunaviy fayl yozildi: {out_path}")

    doc.close()


if __name__ == "__main__":
    main()
