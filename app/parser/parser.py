"""
Main routing parser with layout auto-detection.

Detects the correct layout format of the test document and routes
the text to the appropriate specialized sub-parser.
"""

from __future__ import annotations

import re
from typing import List

from app.models.question import RawQuestion
from app.utils.logger import get_logger
from .image_tokens import extract_image_tokens
from .parser_types import FormatType
from .classic_parser import ClassicParser
from .abc_parser import ABCParser
from .blocks_parser import BlocksParser
from .gift_parser import GIFTParser

log = get_logger(__name__)


class QuestionParser:
    """
    Layout-routing parser. Supports Classic, ABC, and Blocks formats
    along with dynamic auto-detection.
    """

    # Spaced-separator format: lines consisting only of "+" or "=" chars with spaces
    # between them (e.g. "+ + + +" = question delimiter, "= = = =" = option delimiter).
    _SPACED_PLUS_LINE = re.compile(r'^\+(\s+\+){2,}\s*$')
    _SPACED_EQ_LINE   = re.compile(r'^=(\s+=){2,}\s*$')

    def __init__(self, format_type: FormatType = FormatType.AUTO) -> None:
        self.format_type = format_type
        self.detected_format: FormatType | None = None

    def _preprocess_spaced_sep(self, text: str) -> str | None:
        """
        Detect and convert spaced-separator format to Classic marker lines.

        Format: "+" chars separated by spaces (+ + + +) are question delimiters,
        "=" chars separated by spaces (= = = =) are option delimiters,
        lines starting with "#" are correct answers, all other lines are questions
        or wrong answers.

        Returns converted Classic text if detected (>= 5 question separators and
        no existing "?" markers), otherwise returns None.
        """
        lines = text.split('\n')
        plus_sep_count = sum(1 for ln in lines if self._SPACED_PLUS_LINE.match(ln.strip()))
        if plus_sep_count < 5:
            return None
        if any(ln.strip().startswith('?') for ln in lines):
            return None

        result: list[str] = []
        after_plus_sep = False
        started = False
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            if self._SPACED_PLUS_LINE.match(s):
                after_plus_sep = True
                started = True
            elif not started:
                continue  # skip header lines before first separator
            elif self._SPACED_EQ_LINE.match(s):
                pass  # option delimiter — skip
            elif after_plus_sep:
                result.append('? ' + s)
                after_plus_sep = False
            elif s.startswith('#') or s.startswith('*'):
                result.append('+ ' + s[1:].strip())
            else:
                result.append('= ' + s)

        q_count = sum(1 for ln in result if ln.startswith('? '))
        log.info(
            f"Ajratuvchi-separator formati aniqlandi (+ + + + / = = = =): "
            f"{q_count} ta savol klassik formatga o'girildi."
        )
        return '\n'.join(result)

    # Matches numbered questions with no space after separator: 30.Q, 57"Q, 58."Q
    # Uses chr() to avoid smart-quote substitution in the source file.
    _NO_OPT_Q_SEP = (
        '[.)'
        + chr(0x27) + chr(0x22)   # ASCII apostrophe and double quote
        + chr(0x201c) + chr(0x201d)  # curly double quotes
        + chr(0xab) + chr(0xbb)   # angle quotes
        + ']'
    )
    _NO_SPACE_NUM_Q = re.compile(r'^\d+' + _NO_OPT_Q_SEP + r'{1,2}[A-ZА-Яa-zа-я]', re.UNICODE)

    # Detects "B) #text" or "B)# text" — ABC option with # correct marker
    _abc_hash_re = re.compile(r'^([a-fA-F])[\.\)]\s*#\s*(.*)', re.UNICODE)

    OPTIONS_PER_QUESTION_NO_MARKERS = 4

    @classmethod
    def _is_no_marker_q_start(cls, stripped: str) -> bool:
        return (stripped.startswith("?") and len(stripped) > 1) or bool(
            cls._NO_SPACE_NUM_Q.match(stripped)
        )

    def _preprocess_no_option_markers(self, text: str) -> str | None:
        """
        Handle PDFs where ? marks questions but options have no = / + markers.

        Detects the format when ? questions exist but option markers are nearly
        absent (< 2 per question on average). Every question in this format has
        exactly OPTIONS_PER_QUESTION_NO_MARKERS options, so for each question
        block we look ahead to the next '?' line and count the non-empty lines
        in between: the LAST 4 of them are the real options (get an '=' marker),
        and any lines *before* those 4 are a wrapped continuation of the question
        text (left unmarked, so ClassicParser folds them back into the question —
        continuation can only precede the options, never follow them, since a
        question can't resume after its own answer choices).
        """
        lines = text.splitlines()

        q_count = sum(1 for ln in lines if ln.strip().startswith("?"))
        opt_count = sum(1 for ln in lines if ln.strip().startswith(("=", "+", "*")))

        if q_count < 3:
            return None
        # Already has at least 2 option markers per question → not this format
        if opt_count >= q_count * 2:
            return None

        q_idxs = [
            i for i, ln in enumerate(lines)
            if ln.strip() and self._is_no_marker_q_start(ln.strip())
        ]
        if not q_idxs:
            return None

        is_option_line = [False] * len(lines)
        for pos, qi in enumerate(q_idxs):
            block_end = q_idxs[pos + 1] if pos + 1 < len(q_idxs) else len(lines)
            content_idxs = [i for i in range(qi + 1, block_end) if lines[i].strip()]
            overflow = max(0, len(content_idxs) - self.OPTIONS_PER_QUESTION_NO_MARKERS)
            for i in content_idxs[overflow:]:
                is_option_line[i] = True

        result: list[str] = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or self._is_no_marker_q_start(stripped) or not is_option_line[i]:
                # Blank line, question start, or a wrapped question-continuation
                # line — left untouched so ClassicParser appends it to the
                # question text (it has no options yet at that point).
                result.append(line)
                continue

            abc_hash = self._abc_hash_re.match(stripped)
            if abc_hash:
                # "B) #Correct answer" → "+ Correct answer"
                result.append("+ " + abc_hash.group(2).strip())
            elif stripped.startswith('#'):
                # "#Correct answer" (standalone # prefix) → "+ Correct answer"
                result.append("+ " + stripped[1:].strip())
            else:
                result.append("= " + stripped)

        log.info(
            f"Belgisiz variant formati aniqlandi: {q_count} ta savol uchun = belgilari qo'shildi."
        )
        return "\n".join(result)

    # Matches an option-letter marker (A-F) + ) or . + space) embedded mid-line,
    # OR an embedded Classic marker ("+ text" / "= text") glued onto the same
    # PDF row as the previous question/option.
    #
    # "+ " splits on any preceding content (a correct answer swallowed mid-line
    # is the costlier failure — it silently drops the right answer — so this
    # side is deliberately the looser one), but never when followed by a digit,
    # so arithmetic like "5 + 3" inside an option's own text is left alone.
    #
    # "= " only splits after sentence-ending punctuation (". "/"! "/"? "), which
    # is what distinguishes a genuine second option ("...bajarmaydi. = Otning
    # ...") from "=" used as plain notation inside one option/question
    # ("asos = so'z yasovchi = lug'aviy shakl yasovchi ...", a morpheme-formula
    # description that must NOT be chopped into fragments).
    _EMBEDDED_OPT_RE = re.compile(
        r'(?<=\S)\s+(?=[A-Fa-f][\.\)]\s)'
        r'|(?<=\S)\s+(?=\+\s(?!\d))'
        r'|(?<=[.!?])\s+(?==\s(?!\d))',
        re.UNICODE,
    )
    # Recognises lines that already start with an option, a numbered question,
    # or a Classic-format marker (?/=/+). No required space after "="/"+"/"?" --
    # some PDFs extract them glued directly onto the text ("=Barcha ...").
    _OPT_OR_Q_START  = re.compile(r'^(?:[A-Fa-f][\.\)]|\d+[\.\)]|[=+?])', re.UNICODE)

    @classmethod
    def _split_merged_option_lines(cls, lines: List[str]) -> List[str]:
        """
        Split lines where the PDF extractor placed multiple items on one row.

        Handles:
          "A) text1 B) text2"        → ["A) text1",  "B) text2"]
          "1. Question A) option"    → ["1. Question", "A) option"]
          "= wrong. + correct"       → ["= wrong.",   "+ correct"]
          "?Question... + correct"   → ["?Question...", "+ correct"]

        Only processes lines that already start with an option letter (A-F),
        a numbered question, or a Classic marker (?/=/+), so prose text that
        happens to contain "B)" or "+"/"=" mid-sentence elsewhere is left
        untouched.
        """
        result: List[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                result.append(line)
                continue

            # Guard: only touch option/question lines
            if not cls._OPT_OR_Q_START.match(stripped):
                result.append(line)
                continue

            # If no embedded option marker, nothing to split
            if not cls._EMBEDDED_OPT_RE.search(stripped):
                result.append(line)
                continue

            parts = cls._EMBEDDED_OPT_RE.split(stripped)
            result.extend(p.strip() for p in parts if p.strip())

        return result

    def parse(self, text: str) -> List[RawQuestion]:
        """
        Detect format (if AUTO) and parse text into raw questions.
        """
        # Pre-process spaced-separator format (works for PDF, DOCX, TXT, XLSX)
        if self.format_type == FormatType.AUTO:
            converted = self._preprocess_spaced_sep(text)
            if converted is not None:
                text = converted

        # Pre-process no-option-markers format (? questions, options have no markers)
        if self.format_type == FormatType.AUTO:
            converted = self._preprocess_no_option_markers(text)
            if converted is not None:
                text = converted

        # Split lines where PDF merged multiple options / question+option onto one row
        text = "\n".join(self._split_merged_option_lines(text.split("\n")))

        lines = text.split("\n")
        
        # ── Auto detection ──────────────────────────────────────────────
        if self.format_type == FormatType.AUTO:
            self.detected_format = self._detect_format(text)
            log.info(f"Auto-detected test format: [bold cyan]{self.detected_format.value}[/]")
            active_format = self.detected_format
        else:
            self.detected_format = None
            active_format = self.format_type
            log.info(f"Using manually selected format: [bold cyan]{active_format.value}[/]")

        # ── Routing to sub-parser ────────────────────────────────────────
        if active_format == FormatType.GIFT:
            parser = GIFTParser()
        elif active_format == FormatType.BLOCKS:
            parser = BlocksParser()
        elif active_format == FormatType.ABC:
            parser = ABCParser()
        else:
            parser = ClassicParser()

        raw_questions = parser.parse(lines)
        self._extract_images(raw_questions)
        return raw_questions

    @staticmethod
    def _extract_images(raw_questions: List[RawQuestion]) -> None:
        """
        Strip ``[[img:path]]`` tokens from question/option text in-place,
        moving the referenced paths onto ``RawQuestion.images`` /
        ``RawOption.images``.

        An option whose text was *only* an image token becomes ``"[rasm]"``
        so it still counts as a non-empty option.
        """
        for rq in raw_questions:
            clean_q, q_images = extract_image_tokens(rq.question_text)
            rq.question_text = clean_q
            rq.images.extend(q_images)

            for opt in rq.options:
                clean_opt, opt_images = extract_image_tokens(opt.text)
                if opt_images:
                    # Images in option text were placed there by the parser's
                    # _append_continuation when the image token appeared at a
                    # y-position between options. Promote them to question level
                    # because they semantically belong to the question, not the
                    # option.
                    rq.images.extend(opt_images)
                    if not clean_opt:
                        clean_opt = "[rasm]"
                opt.text = clean_opt

    def _detect_format(self, text: str) -> FormatType:
        """
        Analyze text features to auto-detect layout style.
        """
        # 0. GIFT format: { } blocks with = correct, ~ wrong options
        gift_braces = len(re.findall(r"^\{", text, re.MULTILINE))
        gift_wrong  = len(re.findall(r"^~\s*\S", text, re.MULTILINE))
        if gift_braces >= 3 and gift_wrong >= gift_braces * 2:
            return FormatType.GIFT

        # 1. Blocks format detection: count occurrences of separating lines
        plus_seps = len(re.findall(r"^\+{3,}\s*$", text, re.MULTILINE))
        equal_seps = len(re.findall(r"^={3,}\s*$", text, re.MULTILINE))
        if plus_seps >= 2 or equal_seps >= 2:
            return FormatType.BLOCKS

        # 2. Classic format detection: count questions (?...) and options (+... / =...)
        classic_questions = len(re.findall(r"^\?\s*\S", text, re.MULTILINE))
        classic_options = len(re.findall(r"^[+=]\s*\S", text, re.MULTILINE))
        
        # 3. ABC format detection: count numbered questions (1. 2)) and letters (A) B. #C) *D))
        abc_questions = len(re.findall(r"^\d+[\.\)]\s*\S", text, re.MULTILINE))
        abc_options = len(re.findall(r"^[#*+=]?\s*[a-fA-F][\.\)]\s*\S", text, re.MULTILINE))

        log.debug(
            f"Layout Analysis: Classic Q={classic_questions}, Opts={classic_options} | "
            f"ABC Q={abc_questions}, Opts={abc_options} | Blocks Plus={plus_seps}, Equals={equal_seps}"
        )

        if abc_questions > classic_questions and abc_options > classic_options:
            return FormatType.ABC
        
        if classic_questions > 0 or classic_options > 0:
            return FormatType.CLASSIC

        # Fallback default
        return FormatType.CLASSIC
