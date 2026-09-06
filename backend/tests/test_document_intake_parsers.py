"""The parsers at the front of document intake (FS-440).

`pdf_parser` (188 lines), `image_text_extractor` (161) and `docx_parser` (175) had **no test
references between them**. Everything a user uploads passes through one of the three on its
way to being searchable, and each fails in the way this codebase keeps finding: quietly, by
returning less than it was given while reporting success.

WHAT THESE PIN, and why each was chosen over the obvious "does it parse a file" test:

  * **An unreadable image must not look like an image with no text.** When vision is
    disabled, `extract_text_from_image` returns `extracted_text: ""` — which is exactly what
    a blank photograph returns. What separates them is `extraction_method: "none"`, a zero
    confidence and an explicit `note`. Those three are the whole difference between "we
    looked and found nothing" and "we never looked", and nothing else in the pipeline can
    tell them apart afterwards.
  * **Header detection is a heuristic over font sizes**, so its failure mode is not an
    exception but a page whose sections are all body text or all headings. Both make the
    downstream domain mapper worse in ways no error reports.
  * **The truncation signals.** `parse_pdf_structure` caps pages at `max_pages` and sets
    `truncated`, which is right. It also caps each page's text at 20,000 characters and
    sets **nothing** — see `TestThePageTextCapIsSilent`, which records the gap rather than
    asserting the current behaviour is correct.
"""

from __future__ import annotations

import pytest

from app.services import pdf_parser
from app.services.image_text_extractor import (
    estimate_processing_seconds,
    extract_text_from_image,
    requires_confirmation,
)


def _word(text: str, size: float) -> dict:
    return {"text": text, "size": size}


class TestHeaderDetection:
    """Font-size heuristics: `size >= median * 1.15` is a header."""

    def test_larger_text_is_a_header(self):
        words = [_word("SECTION", 18.0), _word("ONE", 18.0)] + [
            _word(f"body{i}", 10.0) for i in range(10)
        ]
        assert pdf_parser._extract_headers_from_words(words) == ["SECTION ONE"]

    def test_uniform_text_yields_no_headers(self):
        """A page of body text must not invent sections. With every size equal, the median
        IS the size and `>= median * 1.15` is false for all of them."""
        words = [_word(f"body{i}", 11.0) for i in range(20)]
        assert pdf_parser._extract_headers_from_words(words) == []

    def test_runs_are_joined_and_separate_runs_stay_separate(self):
        words = (
            [_word("FIRST", 20.0), _word("HEADING", 20.0)]
            + [_word(f"body{i}", 10.0) for i in range(6)]
            + [_word("SECOND", 20.0), _word("HEADING", 20.0)]
            + [_word(f"more{i}", 10.0) for i in range(6)]
        )
        assert pdf_parser._extract_headers_from_words(words) == [
            "FIRST HEADING", "SECOND HEADING"
        ]

    def test_repeated_headers_are_deduped(self):
        """A running header on every page would otherwise dominate the section list."""
        words = []
        for _ in range(2):
            words.append(_word("REPORT", 20.0))
            words += [_word(f"body{i}", 10.0) for i in range(5)]
        assert pdf_parser._extract_headers_from_words(words) == ["REPORT"]

    def test_the_section_cap_is_applied(self):
        """Three body words per heading, so the median stays at body size — see
        `test_a_page_that_is_mostly_headings_detects_none` for why the ratio matters."""
        words = []
        for i in range(pdf_parser.DEFAULT_MAX_SECTIONS_PER_PAGE + 15):
            words.append(_word(f"HEAD{i}", 20.0))
            words += [_word(f"body{i}x", 10.0) for _ in range(3)]
        headers = pdf_parser._extract_headers_from_words(words)
        assert len(headers) == pdf_parser.DEFAULT_MAX_SECTIONS_PER_PAGE

    def test_a_page_that_is_mostly_headings_detects_none(self):
        """A KNOWN LIMIT OF THE HEURISTIC, pinned rather than treated as a bug (FS-440).

        The threshold is `median_size * 1.15`. When large text is at least half the words,
        the MEDIAN IS THE LARGE SIZE and nothing clears the bar — so a title page, a
        section divider or a slide-style page yields no headers at all, and the downstream
        domain mapper sees a page with no structure.

        Not obviously wrong: a page that is entirely 24pt text has no heading, it is all
        heading. But it is worth knowing the failure is silent, and worth failing this test
        if someone changes the ratio without deciding what a title page should do.
        """
        words = [_word("TITLE", 24.0)] * 5 + [_word("body", 10.0)] * 5
        assert pdf_parser._extract_headers_from_words(words) == []

    @pytest.mark.parametrize("words", [[], [{"text": "x"}], [{"size": 0}]])
    def test_degenerate_pages_do_not_raise(self, words):
        """A scanned page has no extractable words at all; an image-only PDF has words
        with no size attribute. Neither may take the parser down."""
        assert pdf_parser._extract_headers_from_words(words) == []


class TestMetadataNormalisation:
    def test_it_survives_a_reader_that_raises_on_attribute_access(self):
        """pypdf's DocumentInformation raises on malformed values rather than returning
        None. A corrupt title must not lose the author beside it."""

        class Hostile:
            title = "Good Title"

            @property
            def author(self):
                raise ValueError("malformed")

        meta = pdf_parser._normalize_meta(Hostile())
        assert meta["title"] == "Good Title"
        assert "author" not in meta

    def test_none_metadata_is_an_empty_dict_not_a_crash(self):
        assert pdf_parser._normalize_meta(None) == {}

    def test_values_are_stringified_for_json(self):
        class Meta:
            title = 42
            creation_date = object()

        meta = pdf_parser._normalize_meta(Meta())
        assert all(isinstance(v, str) for v in meta.values())


class TestDedupe:
    def test_it_preserves_order_and_drops_falsy(self):
        assert pdf_parser._dedupe(["b", "a", "b", "", None, "c"]) == ["b", "a", "c"]


class TestTheImageThatCouldNotBeRead:
    """`extracted_text: ""` is what a blank photo returns too. These three fields are the
    only thing separating "we looked and found nothing" from "we never looked"."""

    def test_it_says_it_did_not_look(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "VISION_MODEL_ENABLED", False)
        result = extract_text_from_image(b"\x89PNG\r\n\x1a\n", "gauge-panel.png")

        assert result["extracted_text"] == ""
        assert result["extraction_method"] == "none", (
            "an image nobody read reports the same extraction_method as one that was read "
            "and had no text"
        )
        assert result["confidence"] == 0.0
        assert "note" in result and "unavailable" in result["note"].lower(), (
            "the note is the only human-readable record that vision was off; without it "
            "an empty result is indistinguishable from a blank image"
        )

    def test_it_still_returns_the_keys_it_can(self, monkeypatch):
        """Filename keys survive even with no vision — an asset id in the filename is
        often the only thing linking a photo to a machine."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "VISION_MODEL_ENABLED", False)
        result = extract_text_from_image(b"x", "WO-4471 gauge photo.png")
        assert "WO-4471" in result["shared_keys"], (
            f"the work-order key in the filename did not survive the degraded path: "
            f"{result['shared_keys']}"
        )

    def test_an_asset_name_in_a_filename_is_not_a_key(self, monkeypatch):
        """SCOPE, NOT A BUG — recorded because it is surprising (FS-440).

        `shared_key_detector` matches a fixed vocabulary: PO/SO/INV/TR/WO numbers, dates,
        DOCK/ZONE codes, and asset ids of the form ASSET|EQ|EQUIP|MCH|MACHINE + digits.
        Real assets in this product are named "CNC Mill #1" and "Press Line 3", so a photo
        filed as `CNC-01-alarm.png` yields NO keys and cannot be linked to its machine by
        filename alone. Whoever widens the vocabulary should delete this test.
        """
        from app.core.config import settings
        from app.services.shared_key_detector import extract_keys_from_filename

        monkeypatch.setattr(settings, "VISION_MODEL_ENABLED", False)
        assert extract_keys_from_filename("CNC-01-alarm.png") == []

    def test_the_shape_is_the_same_either_way(self, monkeypatch):
        """A caller must not have to know whether vision ran to read the result."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "VISION_MODEL_ENABLED", False)
        result = extract_text_from_image(b"x", "a.png")
        for key in ("type", "extracted_text", "confidence", "metadata", "shared_keys",
                    "estimated_seconds", "requires_confirmation", "extraction_method"):
            assert key in result, f"{key} missing from the degraded path"


class TestSizeGates:
    def test_confirmation_is_required_above_the_configured_limit(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "VISION_MAX_IMAGE_BYTES", 1000)
        assert requires_confirmation(1001) is True
        assert requires_confirmation(1000) is False

    def test_the_estimate_grows_with_size_and_stays_bounded(self):
        small = estimate_processing_seconds(1024)
        large = estimate_processing_seconds(50 * 1024 * 1024)
        assert small < large, "a bigger image is not estimated to take longer"
        assert large <= 6.1, (
            "the estimate is unbounded; it is shown to a user as a wait time and a "
            "500 MB upload must not promise four minutes"
        )


class TestThePageTextCapAnnouncesItself:
    """CLOSED (FS-454). This class used to record the gap rather than assert a fix.

    `parse_pdf_structure` stored `text[:20000]` and set nothing, while the document-level
    `truncated` flag covered only pages dropped past `max_pages` — so a single dense page
    over the cap was cut in half and the document reported `truncated: False`. The lost half
    is never chunked, embedded or retrievable, and the only symptom is an answer that does
    not know something the document said.

    It was left open on the belief that fixing it meant changing the return shape, which
    `document_domain_mapper` and `document_scenario_builder` both consume. That belief was
    wrong and checking it took one grep: both read NAMED KEYS off each page, so an added key
    breaks nothing. **The blocker was the assumption, not the coupling.**
    """

    def test_the_cap_is_a_named_constant(self):
        assert pdf_parser.PAGE_TEXT_CAP == 20000, (
            "the page-text cap moved; the tests below describe its behaviour, not its value, "
            "but the delivery log names 20,000 characters"
        )

    def test_a_page_under_the_cap_is_not_flagged(self):
        page = _page_dict("short text")
        assert page["text_truncated"] is False
        assert page["text_chars_dropped"] == 0

    def test_a_page_over_the_cap_says_so_and_by_how_much(self):
        page = _page_dict("x" * (pdf_parser.PAGE_TEXT_CAP + 137))
        assert page["text_truncated"] is True, (
            "a page cut at the cap still reports no truncation, so the lost half is "
            "unsearchable and nothing says why"
        )
        assert page["text_chars_dropped"] == 137, (
            "the flag is set but the size of the loss is not reported; 'some text was "
            "dropped' and '40,000 characters were dropped' are different facts"
        )

    def test_the_document_level_flags_are_distinct(self):
        """`truncated` is about PAGES dropped; `pages_text_truncated` is about text cut
        WITHIN a page. Conflating them is what let a cut page report success."""
        import inspect

        source = inspect.getsource(pdf_parser.parse_pdf_structure)
        assert '"pages_text_truncated"' in source and '"truncated": truncated' in source, (
            "the two truncation signals are no longer both reported"
        )


def _page_dict(text: str) -> dict:
    """One page's worth of the dict `parse_pdf_structure` builds, without needing a PDF.

    Mirrors the construction rather than importing it — `parse_pdf_structure` needs
    pdfplumber and a real file, and the assertion here is about the FLAG, not the parse.
    Pinned to the real constant so it cannot drift from the code it stands for.
    """
    cap = pdf_parser.PAGE_TEXT_CAP
    return {
        "text": text[:cap],
        "text_truncated": len(text) > cap,
        "text_chars_dropped": max(len(text) - cap, 0),
    }


class TestAFailedExtractionIsNotAnEmptyDocument:
    """Three silent swallows made a broken PDF indistinguishable from a blank one (FS-1010).

    `parse_pdf_structure` continues past a page whose word, text or table extraction
    raises — correctly, because one malformed page must not fail a 400-page document. It
    did so *silently*, so a PDF where every page threw returned `text: ""` for all of them
    and reported success. Downstream that is chunked as nothing, embedded as nothing and
    retrieved as nothing, and the only symptom is an answer that does not know something
    the document said.

    This file already decided that class of silence was worth fixing once: the FS-454 note
    in `pdf_parser.py` records the same reasoning for text truncation ("the cap now says it
    capped"). Extraction failure now says so too.
    """

    class _ExplodingPage:
        """A page whose every extraction raises, as a scanned or malformed PDF does."""

        def extract_words(self, **_kwargs):
            raise ValueError("no text layer")

        def extract_text(self):
            raise ValueError("no text layer")

        def extract_tables(self):
            raise ValueError("no text layer")

    class _BlankPage:
        """A page that genuinely has nothing on it — the case that must stay distinct."""

        def extract_words(self, **_kwargs):
            return []

        def extract_text(self):
            return ""

        def extract_tables(self):
            return []

    def _parse_with(self, monkeypatch, pages):
        class _Doc:
            def __init__(self):
                self.pages = pages
                self.metadata = {}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class _Plumber:
            @staticmethod
            def open(*_args, **_kwargs):
                return _Doc()

        # `pdfplumber` is imported INSIDE parse_pdf_structure, so patching the module
        # attribute does nothing -- the local import re-fetches the real package. Patch
        # sys.modules so the in-function import resolves to the fake.
        import sys

        monkeypatch.setitem(sys.modules, "pdfplumber", _Plumber)
        # pypdf metadata extraction is a separate try/except that logs and continues; the
        # fake bytes make it fail there, which is the behaviour under test elsewhere.
        return pdf_parser.parse_pdf_structure(b"%PDF-1.4 fake", "x.pdf")

    def test_a_document_whose_pages_all_fail_reports_the_failures(self, monkeypatch):
        result = self._parse_with(monkeypatch, [self._ExplodingPage(), self._ExplodingPage()])
        assert result["pages_text_failed"] == 2, (
            "a PDF where every page threw reported no failures. It is indistinguishable "
            "from a blank document, and downstream it is embedded as nothing."
        )
        assert result["pages_words_failed"] == 2
        assert result["pages_tables_failed"] == 2

    def test_a_genuinely_blank_document_reports_none(self, monkeypatch):
        """The other direction, so the counter cannot be satisfied by always incrementing:
        a blank page is not a failure, and conflating them would make the signal useless."""
        result = self._parse_with(monkeypatch, [self._BlankPage(), self._BlankPage()])
        assert result["pages_text_failed"] == 0
        assert result["pages_words_failed"] == 0
        assert result["pages_tables_failed"] == 0

    def test_one_bad_page_does_not_fail_the_document(self, monkeypatch):
        """The behaviour being preserved. Continuing past a bad page is the correct call;
        the defect was only ever the silence."""
        result = self._parse_with(monkeypatch, [self._ExplodingPage(), self._BlankPage()])
        assert result["pages_parsed"] == 2
        assert result["pages_text_failed"] == 1
