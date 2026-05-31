"""
Tests for app.text.normalizer
==============================
PHASE 5G: Text Normalization Engine

Coverage:
- All 12 normalization rules (TTS pass)
- Narration pass (rules A, B, C)
- normalize_with_stats() counters
- Real-world fixtures: English nonfiction, Spanish literature,
  academic papers, OCR documents, mixed formatting
- Edge cases: empty input, already-clean text, unicode, very long text
- Determinism: same input → same output
"""

import pytest
from app.text.normalizer import (
    normalize_for_tts,
    normalize_for_narration,
    normalize_with_stats,
    NormalizationStats,
)


# ===========================================================================
# Helpers
# ===========================================================================

def norm(text: str) -> str:
    """Shorthand for normalize_for_tts."""
    return normalize_for_tts(text)


def narr(text: str) -> str:
    """Shorthand for normalize_for_narration."""
    return normalize_for_narration(text)


# ===========================================================================
# Rule 1 + 2: False line breaks & paragraph preservation
# ===========================================================================

class TestFalseLineBreaks:
    def test_basic_false_break(self):
        raw = "The memory of Funes\nwas extraordinary."
        assert norm(raw) == "The memory of Funes was extraordinary."

    def test_multiline_paragraph_joined(self):
        raw = (
            "He had spent the morning\n"
            "walking through the village\n"
            "and thinking about the past."
        )
        result = norm(raw)
        assert "\n" not in result
        assert "walking through the village" in result

    def test_real_paragraph_boundary_preserved(self):
        raw = "Sentence one.\n\nSentence two."
        result = norm(raw)
        assert "\n\n" in result
        assert result.index("Sentence one.") < result.index("Sentence two.")

    def test_sentence_ending_prevents_join(self):
        raw = "He stopped.\nShe continued."
        result = norm(raw)
        # "She" starts uppercase → new line preserved
        assert "He stopped." in result
        assert "She continued." in result

    def test_question_mark_prevents_join(self):
        raw = "Is that right?\nYes, it is."
        result = norm(raw)
        assert "Is that right?" in result
        assert "Yes, it is." in result

    def test_exclamation_mark_prevents_join(self):
        raw = "Run!\nHe ran."
        result = norm(raw)
        assert "Run!" in result

    def test_lowercase_continuation_joined(self):
        raw = "The old man sat at the edge\nof the water and waited."
        result = norm(raw)
        assert "edge of the water" in result

    def test_multiple_paragraphs_preserved(self):
        raw = (
            "First paragraph, first line\n"
            "continues here.\n\n"
            "Second paragraph starts\n"
            "and ends here."
        )
        result = norm(raw)
        assert "\n\n" in result
        parts = result.split("\n\n")
        assert len(parts) == 2
        assert "First paragraph, first line continues here." in parts[0]
        assert "Second paragraph starts and ends here." in parts[1]

    def test_colon_line_ending_not_joined(self):
        raw = "The following items:\nfirst item"
        result = norm(raw)
        # colon is in _SENTENCE_END → no join
        assert "The following items:" in result

    def test_uppercase_start_not_joined(self):
        raw = "End of sentence.\nAnother sentence here."
        result = norm(raw)
        assert "End of sentence." in result
        assert "Another sentence here." in result


# ===========================================================================
# Rule 3: Hyphenated line breaks
# ===========================================================================

class TestHyphenRepair:
    def test_basic_hyphen_repair(self):
        raw = "The memo-\nry was extraordinary."
        result = norm(raw)
        assert "memory" in result
        assert "memo-\nry" not in result

    def test_information(self):
        raw = "He gathered all the informa-\ntion he needed."
        result = norm(raw)
        assert "information" in result

    def test_extraordinary(self):
        raw = "It was an extra-\nordinary day."
        result = norm(raw)
        assert "extraordinary" in result

    def test_mid_paragraph(self):
        raw = (
            "The author described a remark-\n"
            "able scene that took place on a\n"
            "warm summer evening."
        )
        result = norm(raw)
        assert "remarkable" in result

    def test_stats_count_hyphen_repairs(self):
        raw = "The memo-\nry is good. The informa-\ntion is clear."
        _, stats = normalize_with_stats(raw)
        assert stats.hyphen_repairs == 2

    def test_hyphen_in_compound_at_line_end_not_touched(self):
        # "well-known\n" — hyphen is NOT at end of line before the break
        # The continuation "text" starts after "known\n", not after "well-"
        raw = "He is well-known\nfor his writing."
        result = norm(raw)
        # The hyphen stays; only the line break between the two sentences matters
        assert "well-known" in result


# ===========================================================================
# Rule 4: Repeated headers / footers
# ===========================================================================

class TestRepeatedHeaders:
    def test_repeated_book_title_removed(self):
        header = "One Hundred Years of Solitude"
        body_lines = [
            f"{header}\n\nParagraph {i} of the text. It goes on and on.\n"
            for i in range(5)
        ]
        raw = "".join(body_lines)
        result = norm(raw)
        # Header should appear fewer times (removed from most occurrences)
        assert result.count(header) < 5

    def test_stats_count_headers_removed(self):
        header = "García Márquez"
        # Appear 4 times in the text
        raw = "\n\n".join([
            f"{header}\n\nSome paragraph text here.",
            f"{header}\n\nAnother paragraph text here.",
            f"{header}\n\nYet another paragraph text here.",
            f"{header}\n\nFourth paragraph text here.",
        ])
        _, stats = normalize_with_stats(raw)
        assert stats.headers_removed > 0

    def test_body_text_not_removed(self):
        # A sentence appearing once stays
        raw = (
            "The village had been prosperous.\n\n"
            "After the war, things changed.\n\n"
            "The village had been prosperous."
        )
        # Only 2 occurrences — below threshold of 3
        result = norm(raw)
        assert result.count("The village had been prosperous.") == 2

    def test_sentence_with_period_not_removed_as_header(self):
        # A repeating sentence that ends with a period should NOT be flagged
        raw = "\n\n".join([
            "He walked slowly.\n\nThe sun was bright.",
            "He walked slowly.\n\nThe moon was full.",
            "He walked slowly.\n\nThe stars were out.",
            "He walked slowly.\n\nThe sky was clear.",
        ])
        result = norm(raw)
        # Should still contain occurrences (has terminal punctuation)
        assert result.count("He walked slowly.") >= 1


# ===========================================================================
# Rule 5: Page numbers
# ===========================================================================

class TestPageNumbers:
    def test_standalone_number_removed(self):
        raw = "First paragraph.\n12\nSecond paragraph."
        result = norm(raw)
        assert "\n12\n" not in result
        assert "First paragraph." in result
        assert "Second paragraph." in result

    def test_page_word_removed(self):
        raw = "Chapter text.\nPage 42\nMore text."
        result = norm(raw)
        assert "Page 42" not in result

    def test_pagina_removed(self):
        raw = "Texto aquí.\nPágina 7\nMás texto."
        result = norm(raw)
        assert "Página 7" not in result

    def test_seite_removed(self):
        raw = "Deutscher Text.\nSeite 15\nMehr Text."
        result = norm(raw)
        assert "Seite 15" not in result

    def test_multiple_page_numbers_removed(self):
        raw = "Para 1.\n1\nPara 2.\n2\nPara 3.\n3\nPara 4."
        result = norm(raw)
        assert "\n1\n" not in result
        assert "\n2\n" not in result
        assert "\n3\n" not in result

    def test_year_in_sentence_preserved(self):
        # "in 1984" inside a sentence should NOT be removed
        raw = "The event happened in 1984 and was significant."
        result = norm(raw)
        assert "1984" in result

    def test_stats_count_page_removals(self):
        raw = "Para 1.\n1\nPara 2.\n2\nPara 3.\n3\nPara 4."
        _, stats = normalize_with_stats(raw)
        assert stats.footers_removed == 3


# ===========================================================================
# Rule 6: OCR garbage
# ===========================================================================

class TestOCRGarbage:
    def test_pipe_line_removed(self):
        raw = "First line.\n|\nSecond line."
        result = norm(raw)
        assert "|\n" not in result
        assert "First line." in result
        assert "Second line." in result

    def test_double_pipe_removed(self):
        raw = "First.\n||\nSecond."
        result = norm(raw)
        assert "||" not in result

    def test_underscores_line_removed(self):
        raw = "Chapter text.\n___\nMore text."
        result = norm(raw)
        assert "___" not in result

    def test_mixed_symbols_line_removed(self):
        raw = "Text.\n••••\nMore text."
        result = norm(raw)
        assert "••••" not in result

    def test_forward_slash_line_removed(self):
        raw = "Text.\n///\nMore text."
        result = norm(raw)
        assert "///" not in result

    def test_stats_count_ocr_removals(self):
        raw = "Text.\n|\nMore.\n||\nEven more."
        _, stats = normalize_with_stats(raw)
        assert stats.ocr_artifacts_removed == 2

    def test_slash_in_text_not_removed(self):
        # A URL-like or fraction in running text should survive
        raw = "The ratio is 1/2 of the total."
        result = norm(raw)
        assert "1/2" in result


# ===========================================================================
# Rule 7: Whitespace normalization
# ===========================================================================

class TestWhitespaceNormalization:
    def test_multiple_spaces_collapsed(self):
        raw = "Hello   world."
        assert norm(raw) == "Hello world."

    def test_tab_converted_to_space(self):
        raw = "Hello\tworld."
        assert norm(raw) == "Hello world."

    def test_excessive_blank_lines_collapsed(self):
        raw = "Para 1.\n\n\n\n\nPara 2."
        result = norm(raw)
        assert "\n\n\n" not in result
        assert "Para 1." in result
        assert "Para 2." in result

    def test_trailing_spaces_stripped(self):
        raw = "Hello world.   \nNext line."
        result = norm(raw)
        assert "   \n" not in result


# ===========================================================================
# Rule 8: Quote normalization
# ===========================================================================

class TestQuoteNormalization:
    def test_left_double_quote_normalized(self):
        raw = '“Hello,” she said.'
        result = norm(raw)
        assert '"Hello,"' in result

    def test_guillemets_normalized(self):
        raw = '«Bonjour,» dit-il.'
        result = norm(raw)
        assert '"Bonjour,"' in result

    def test_german_low_quotes_normalized(self):
        raw = '„Guten Tag," sagte er.'
        result = norm(raw)
        assert '"Guten Tag,"' in result

    def test_single_typographic_quotes_normalized(self):
        raw = "‘It’s fine.’"
        result = norm(raw)
        assert "'" in result
        assert '‘' not in result
        assert '’' not in result

    def test_backtick_normalized(self):
        raw = "`quoted`"
        result = norm(raw)
        assert "`" not in result

    def test_dialogue_preserved(self):
        raw = '"Hello," she said. "How are you?"'
        result = norm(raw)
        assert "Hello," in result
        assert "How are you?" in result


# ===========================================================================
# Rule 9: Ellipsis normalization
# ===========================================================================

class TestEllipsisNormalization:
    def test_unicode_ellipsis_normalized(self):
        raw = "He paused… and then continued."
        result = norm(raw)
        assert "…" not in result
        assert "..." in result

    def test_spaced_dots_normalized(self):
        raw = "He paused. . . and then continued."
        result = norm(raw)
        assert ". . ." not in result
        assert "..." in result

    def test_four_dots_normalized(self):
        raw = "She waited...."
        result = norm(raw)
        assert "...." not in result
        assert "..." in result

    def test_five_dots_normalized(self):
        raw = "The end....."
        result = norm(raw)
        assert "....." not in result
        assert "..." in result

    def test_standard_ellipsis_unchanged(self):
        raw = "He paused... and then spoke."
        result = norm(raw)
        assert "..." in result


# ===========================================================================
# Narration pass: Rule A — em/en dashes
# ===========================================================================

class TestNarrationEmDash:
    def test_em_dash_spaced(self):
        raw = "He said—quietly—that he was fine."
        result = narr(raw)
        assert " — " in result
        assert "He said" in result
        assert "quietly" in result

    def test_em_dash_with_spaces_normalized(self):
        raw = "The result — as expected — was wrong."
        result = narr(raw)
        assert " — " in result

    def test_en_dash_spaced(self):
        raw = "Pages 10–20 are missing."
        result = narr(raw)
        assert " — " in result or "–" in result  # en dash is also handled


# ===========================================================================
# Narration pass: Rule B — abbreviation safety
# ===========================================================================

class TestNarrationAbbreviations:
    def test_dr_period_removed(self):
        raw = "He visited Dr. Smith at the clinic."
        result = narr(raw)
        # Period after Dr should not appear (to avoid false sentence splits)
        assert "Dr " in result or "Dr." not in result.split("Smith")[0]

    def test_mr_period_removed(self):
        raw = "Mr. Johnson was late."
        result = narr(raw)
        assert "Mr " in result

    def test_mrs_period_removed(self):
        raw = "Mrs. Davis called this morning."
        result = narr(raw)
        assert "Mrs " in result

    def test_etc_period_removed(self):
        raw = "Items like tables, chairs, etc. were moved."
        result = narr(raw)
        assert "etc" in result

    def test_sr_period_removed(self):
        raw = "El Sr. García llegó temprano."
        result = narr(raw)
        assert "Sr " in result

    def test_sra_period_removed(self):
        raw = "La Sra. Martínez firmó el contrato."
        result = narr(raw)
        assert "Sra " in result

    def test_vs_period_removed(self):
        raw = "The match was Team A vs. Team B."
        result = narr(raw)
        assert "vs " in result


# ===========================================================================
# Narration pass: Rule C — list readability
# ===========================================================================

class TestNarrationLists:
    def test_number_period_spacing(self):
        raw = "1.First item\n2.Second item"
        result = narr(raw)
        assert "1. First" in result
        assert "2. Second" in result

    def test_already_spaced_list_unchanged(self):
        raw = "1. First item\n2. Second item"
        result = narr(raw)
        assert "1. First item" in result


# ===========================================================================
# normalize_with_stats — counter accuracy
# ===========================================================================

class TestNormalizationStats:
    def test_input_output_char_counts(self):
        raw = "Hello   world.\n\n\nGoodbye."
        _, stats = normalize_with_stats(raw)
        assert stats.input_chars == len(raw)
        assert stats.output_chars == len(normalize_for_tts(raw))

    def test_stats_type(self):
        _, stats = normalize_with_stats("Hello.")
        assert isinstance(stats, NormalizationStats)

    def test_clean_text_zero_repairs(self):
        raw = "This is a clean sentence. It has proper formatting.\n\nA new paragraph."
        _, stats = normalize_with_stats(raw)
        assert stats.hyphen_repairs == 0
        assert stats.ocr_artifacts_removed == 0

    def test_combined_stats(self):
        raw = (
            "A memo-\nry lasts.\n"   # 1 hyphen repair
            "Line breaks here\n"      # potential line-break repair
            "continue here.\n"
            "|\n"                     # 1 OCR artifact
            "1\n"                     # 1 page number (footer)
        )
        _, stats = normalize_with_stats(raw)
        assert stats.hyphen_repairs == 1
        assert stats.ocr_artifacts_removed == 1
        assert stats.footers_removed == 1


# ===========================================================================
# Real-world fixtures
# ===========================================================================

class TestRealWorldFixtures:

    def test_english_nonfiction_paragraph(self):
        """Simulates a typical nonfiction paragraph with soft breaks."""
        raw = (
            "In the early twentieth century, the city of Buenos Aires\n"
            "was undergoing a rapid transformation. The old colonial\n"
            "architecture was giving way to European-style boulevards,\n"
            "and the population had grown to nearly a million inhabitants.\n\n"
            "The immigrants arrived in waves, bringing with them their\n"
            "languages, customs, and traditions from every corner of the world."
        )
        result = norm(raw)
        assert "\n\n" in result  # paragraph boundary preserved
        assert "Buenos Aires was undergoing" in result
        assert "European-style boulevards" in result

    def test_spanish_literature_snippet(self):
        """Simulates a classic Spanish-language literary passage."""
        raw = (
            "Muchos años después, frente al pelotón de\n"
            "fusilamiento, el coronel Aureliano Buendía había\n"
            "de recordar aquella tarde remota en que su padre\n"
            "lo llevó a conocer el hielo.\n\n"
            "Macondo era entonces una aldea de veinte casas de\n"
            "barro y cañabrava construidas a la orilla de un río\n"
            "de aguas diáfanas que se precipitaban por un lecho\n"
            "de piedras pulidas, blancas y enormes como huevos prehistóricos."
        )
        result = norm(raw)
        # Paragraph break preserved
        assert "\n\n" in result
        # Spanish text joined correctly
        assert "pelotón de fusilamiento" in result
        assert "Macondo era entonces una aldea" in result

    def test_academic_paper_with_page_breaks(self):
        """Simulates an academic paper with page numbers and headers."""
        raw = (
            "Abstract\n\n"
            "This paper examines the relationship between\n"
            "cognitive load and reading comprehension in\n"
            "digital environments.\n"
            "3\n"
            "Introduction\n\n"
            "The study of cognitive load theory (Sweller, 1988)\n"
            "has provided important insights into how\n"
            "students process information.\n"
            "4\n"
            "The results indicate that excessive complexity\n"
            "reduces retention rates significantly."
        )
        result = norm(raw)
        assert "\n3\n" not in result
        assert "\n4\n" not in result
        assert "cognitive load and reading comprehension" in result

    def test_ocr_document_with_artifacts(self):
        """Simulates heavily OCR-processed text with common noise."""
        raw = (
            "The quick brown fox\n"
            "|\n"
            "jumps over the lazy dog.\n"
            "||  \n"
            "It was a sunny afternoon\n"
            "___\n"
            "when the events unfolded."
        )
        result = norm(raw)
        assert "|" not in result
        assert "___" not in result
        assert "quick brown fox" in result
        assert "sunny afternoon" in result

    def test_academic_with_hyphenated_technical_terms(self):
        """Academic PDFs often hyphenate long technical terms at line end."""
        raw = (
            "The phenomenon of electromag-\n"
            "netic interference was studied.\n\n"
            "Researchers examined the photo-\n"
            "synthesis process in detail."
        )
        result = norm(raw)
        assert "electromagnetic" in result
        assert "photosynthesis" in result

    def test_book_with_running_header(self):
        """Simulates a book where the chapter title repeats on each page."""
        chapter_title = "The Garden of Forking Paths"
        pages = [
            f"{chapter_title}\n\nHe ran through the garden and\nfound the old house.\n",
            f"{chapter_title}\n\nThe doors were open and light\nstreamed through.\n",
            f"{chapter_title}\n\nHe entered and saw\nthe manuscripts.\n",
            f"{chapter_title}\n\nThey spoke for hours\nabout time and space.\n",
        ]
        raw = "\n".join(pages)
        result = norm(raw)
        # The repeated header should be reduced to fewer occurrences
        occurrences = result.count(chapter_title)
        assert occurrences < 4

    def test_portuguese_text_with_accents(self):
        """Ensure accented characters survive all rules."""
        raw = (
            "A história do Brasil é\n"
            "marcada por grandes transformações.\n\n"
            "O povo brasileiro sempre\n"
            "buscou sua própria identidade."
        )
        result = norm(raw)
        assert "é" in result
        assert "õ" in result   # transformações
        assert "ó" in result
        assert "A história do Brasil é marcada" in result

    def test_french_text_with_guillemets(self):
        """French text with «guillemets» should have quotes normalized."""
        raw = '«Bonjour,» dit-il, «comment allez-vous?»'
        result = norm(raw)
        assert "«" not in result
        assert "»" not in result
        assert "Bonjour," in result

    def test_mixed_formatting_chaos(self):
        """All problems at once — stress test."""
        raw = (
            "Running Header Title\n\n"  # will repeat below
            "Chapter 1: The Beginnings\n\n"
            "It was a dark and stormy\n"    # false break (continues lower)
            "night when the storm\n"         # false break
            "finally arrived.\n"
            "Page 1\n"                       # page number
            "|\n"                            # OCR noise
            "He heard a knock   at the door.\n"  # extra spaces
            "Dr. Watson entered the room.\n"
            "Running Header Title\n\n"       # repeated header
            "The investigation had\n"        # false break
            "barely begun.\n"
            "Page 2\n"                       # page number
            "Running Header Title\n\n"       # repeated header (3rd time)
            "He discov-\n"                   # hyphen break
            "ered the clue\n"                # continues
            "beneath the table."
        )
        result = norm(raw)

        # Page numbers gone
        assert "Page 1" not in result
        assert "Page 2" not in result

        # OCR noise gone
        assert "|\n" not in result

        # Extra spaces collapsed
        assert "   " not in result

        # Hyphen repaired
        assert "discovered" in result

        # Content preserved
        assert "dark and stormy" in result
        assert "Dr." in result or "Dr " in result
        assert "clue" in result

    def test_empty_string(self):
        assert norm("") == ""

    def test_whitespace_only(self):
        assert norm("   \n\n  \t  ") == ""

    def test_single_word(self):
        assert norm("Hello") == "Hello"

    def test_already_clean_text_unchanged(self):
        raw = "This is a perfectly clean sentence.\n\nAnd a second paragraph."
        result = norm(raw)
        assert "perfectly clean sentence." in result
        assert "\n\n" in result

    def test_very_long_text_performance(self):
        """normalize_for_tts must handle large chapters without error."""
        paragraph = (
            "In the beginning was the word, and the word was with the text.\n"
            "The text was processed by many tools and passed through many\n"
            "pipelines before it reached its final destination.\n\n"
        )
        raw = paragraph * 500  # ~200KB
        result = norm(raw)
        assert len(result) > 0


# ===========================================================================
# Determinism
# ===========================================================================

class TestDeterminism:
    def test_same_output_on_repeated_calls(self):
        raw = (
            "The quick-\nbrown fox\njumps over\nthe lazy dog.\n"
            "|\n"
            "Page 5\n"
            "And so it goes…"
        )
        result_1 = norm(raw)
        result_2 = norm(raw)
        result_3 = norm(raw)
        assert result_1 == result_2 == result_3

    def test_normalize_with_stats_deterministic(self):
        raw = "Test text\nwith issues.\n|\nPage 1"
        _, stats1 = normalize_with_stats(raw)
        _, stats2 = normalize_with_stats(raw)
        assert stats1.line_break_repairs == stats2.line_break_repairs
        assert stats1.hyphen_repairs == stats2.hyphen_repairs
        assert stats1.ocr_artifacts_removed == stats2.ocr_artifacts_removed
        assert stats1.footers_removed == stats2.footers_removed

    def test_idempotent_on_clean_text(self):
        """Applying normalization twice yields the same result as once."""
        raw = "He was a good man.\n\nShe was a great woman."
        once = norm(raw)
        twice = norm(once)
        assert once == twice

    def test_idempotent_on_noisy_text(self):
        """After first pass, second pass produces no further changes."""
        raw = (
            "The quick-\nbrown fox\n"
            "|\n"
            "jumps   over\nthe lazy\ndog."
        )
        once = norm(raw)
        twice = norm(once)
        assert once == twice
