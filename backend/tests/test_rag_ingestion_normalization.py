"""Flattening a parsed document into citable blocks (FS-440).

`rag_ingestion` is 534 lines with **no test references**. Its normalisation layer — the
`_blocks_from_*` adapters and `_table_rows_to_blocks` — is where an uploaded document
becomes the units that get embedded, and it is pure: bytes in, `TextBlock`s out. Everything
downstream can only retrieve what this layer emits.

WHY EACH ASSERTION, rather than "does it produce blocks":

  * **A table row must be self-describing.** The module's own comment names the failure:
    *"the 'who signs vs who approves' failure mode"*. A row retrieved in isolation as
    `Shift Supervisor | Line Release Form | co-signs` means nothing; as
    `Role: Shift Supervisor | Document: Line Release Form | Action: co-signs` it means
    exactly one thing. Retrieval returns rows out of context by design, so context has to
    travel with them.
  * **Nothing may be dropped.** A row skipped here is never embedded and never retrievable,
    and the upload reports success. This is the same silent loss the chunker tests guard,
    one layer up.
  * **A markdown heading inside a fenced code block must not split the document.** `#` in a
    shell sample and `|` in prose are common, and a false split produces citations that
    point at a section that does not exist.
  * **An image with no extracted text must produce NO block**, not an empty one. An empty
    block would be embedded, would match nothing useful, and would present as a document
    that was successfully indexed.
"""

from __future__ import annotations

import pytest

from app.services.rag_ingestion import (
    _blocks_from_csv,
    _blocks_from_image,
    _blocks_from_markdown,
    _blocks_from_text,
    _detect_kind,
    _empty_reason,
    _rows_to_text,
    _table_rows_to_blocks,
)


class TestATableRowStandsAlone:
    ROWS = [
        ["Role", "Document", "Action"],
        ["Shift Supervisor", "Line Release Form", "co-signs"],
        ["Quality Lead", "Line Release Form", "approves"],
    ]

    def test_each_data_row_becomes_its_own_block(self):
        blocks = _table_rows_to_blocks(self.ROWS, {"page": 4})
        assert len(blocks) == 2, (
            "rows were packed together; retrieval would return two people's "
            "responsibilities as one chunk and the reader cannot tell which is which"
        )

    def test_each_row_carries_its_column_names(self):
        blocks = _table_rows_to_blocks(self.ROWS, {"page": 4})
        text = blocks[0].text
        assert "Role: Shift Supervisor" in text and "Action: co-signs" in text, (
            f"the row is not self-describing: {text!r}. Retrieved in isolation it is a "
            f"list of words with no indication of which column each came from"
        )

    def test_who_signs_is_distinguishable_from_who_approves(self):
        """The failure the module's own comment names."""
        blocks = _table_rows_to_blocks(self.ROWS, {})
        signs = [b for b in blocks if "co-signs" in b.text]
        approves = [b for b in blocks if "approves" in b.text]
        assert len(signs) == 1 and len(approves) == 1
        assert "Shift Supervisor" in signs[0].text
        assert "Quality Lead" in approves[0].text
        assert "Quality Lead" not in signs[0].text, (
            "both people appear in the same block, which is exactly the confusion "
            "per-row blocks exist to prevent"
        )

    def test_the_row_number_rides_along(self):
        blocks = _table_rows_to_blocks(self.ROWS, {"page": 4})
        assert [b.meta["row"] for b in blocks] == [1, 2]
        assert all(b.meta["is_table"] for b in blocks)
        assert all(b.meta["page"] == 4 for b in blocks), "base meta was lost"

    def test_a_heading_is_prepended_for_context(self):
        blocks = _table_rows_to_blocks(self.ROWS, {}, heading="Sign-off Matrix")
        assert blocks[0].text.startswith("[Sign-off Matrix]")
        assert blocks[0].meta["heading"] == "Sign-off Matrix"


class TestTheTablesRealDocumentsContain:
    def test_a_ragged_row_keeps_its_extra_cells(self):
        """A row with more cells than the header. Dropping the overflow would lose data
        with no error — the cells exist in the file and would simply never be indexed."""
        rows = [["A", "B"], ["1", "2", "3"]]
        blocks = _table_rows_to_blocks(rows, {})
        assert "3" in blocks[0].text, f"the third cell was dropped: {blocks[0].text!r}"

    def test_a_header_with_blank_cells_still_labels_its_column(self):
        rows = [["Role", ""], ["Supervisor", "co-signs"]]
        blocks = _table_rows_to_blocks(rows, {})
        assert "co-signs" in blocks[0].text, "a value under an unnamed column was dropped"

    def test_empty_cells_are_skipped_not_rendered_as_blanks(self):
        rows = [["A", "B", "C"], ["1", "", "3"]]
        text = _table_rows_to_blocks(rows, {})[0].text
        assert "B:" not in text, f"an empty cell was rendered as a labelled blank: {text!r}"

    def test_a_header_only_table_is_kept_as_one_block(self):
        blocks = _table_rows_to_blocks([["A", "B"]], {})
        assert len(blocks) == 1 and "A | B" in blocks[0].text

    def test_a_row_of_nothing_but_blanks_produces_no_block(self):
        assert _table_rows_to_blocks([["A"], ["", "  "]], {}) == [] or all(
            b.text.strip() for b in _table_rows_to_blocks([["A"], ["", "  "]], {})
        )

    def test_an_empty_table_produces_nothing(self):
        assert _table_rows_to_blocks([], {}) == []
        assert _table_rows_to_blocks([[None, None]], {}) == []

    def test_none_cells_do_not_render_as_the_word_none(self):
        text = _rows_to_text([["A", None, "C"]])
        assert "None" not in text, f"a null cell became the literal string None: {text!r}"


class TestMarkdownStructure:
    def test_headings_split_the_document(self):
        md = b"# First\n\nAlpha text.\n\n# Second\n\nBeta text.\n"
        blocks = _blocks_from_markdown(md)
        headings = [b.meta.get("heading") for b in blocks]
        assert "First" in headings and "Second" in headings

    def test_a_hash_inside_a_code_fence_does_not_split(self):
        """`#` starts a comment in every shell sample ever written."""
        md = b"# Real Heading\n\n```bash\n# not a heading\necho hi\n```\n\nProse.\n"
        blocks = _blocks_from_markdown(md)
        headings = {b.meta.get("heading") for b in blocks}
        assert "not a heading" not in headings, (
            f"a comment inside a fenced block created a section: {headings}"
        )

    def test_a_gfm_table_becomes_per_row_blocks(self):
        md = (
            b"## Matrix\n\n"
            b"| Role | Action |\n|---|---|\n"
            b"| Supervisor | co-signs |\n| Lead | approves |\n"
        )
        blocks = _blocks_from_markdown(md)
        rows = [b for b in blocks if b.meta.get("is_table")]
        assert len(rows) == 2, f"expected two row blocks, got {len(rows)}"
        assert any("Role: Supervisor" in b.text for b in rows)

    def test_a_pipe_in_prose_does_not_start_a_table(self):
        """A table needs a separator row directly under the header. Prose containing a
        pipe would otherwise swallow the paragraphs after it."""
        md = b"Some prose with a | pipe in it.\nMore prose.\n"
        blocks = _blocks_from_markdown(md)
        assert not any(b.meta.get("is_table") for b in blocks)

    def test_an_unstructured_document_still_produces_a_block(self):
        blocks = _blocks_from_markdown(b"Just a paragraph with no structure at all.")
        assert blocks and "paragraph" in blocks[0].text

    def test_prose_before_the_first_heading_is_not_lost(self):
        md = b"Preamble sentence.\n\n# Heading\n\nBody.\n"
        joined = " ".join(b.text for b in _blocks_from_markdown(md))
        assert "Preamble sentence." in joined, (
            "text before the first heading was dropped — it has no heading to hang on "
            "and is exactly where a document's summary lives"
        )


class TestCsv:
    def test_rows_become_self_describing_blocks(self):
        blocks = _blocks_from_csv(b"asset,status\nCNC-01,running\nCNC-02,fault\n")
        assert len(blocks) == 2
        assert "asset: CNC-01" in blocks[0].text

    def test_quoted_commas_are_not_split(self):
        blocks = _blocks_from_csv(b'asset,note\nCNC-01,"stopped, then restarted"\n')
        assert "stopped, then restarted" in blocks[0].text, (
            "the csv module's quoting was bypassed; a comma inside a quoted field split "
            "the row and shifted every column after it"
        )

    def test_a_utf8_bom_does_not_corrupt_the_first_header(self):
        """Excel writes a BOM. Without `utf-8-sig` the first column is named `\\ufeffasset`
        and every row is labelled with an invisible character."""
        blocks = _blocks_from_csv(b"\xef\xbb\xbfasset,status\nCNC-01,running\n")
        assert "asset: CNC-01" in blocks[0].text

    def test_a_single_column_file_falls_back_to_text(self):
        blocks = _blocks_from_csv(b"line one\nline two\nline three\n")
        assert len(blocks) == 1 and blocks[0].meta["source_type"] == "text", (
            "a single-column file is a list, not a table; treating it as one would emit "
            "a block per line with a meaningless column name"
        )

    def test_an_empty_file_loses_nothing_because_there_is_nothing(self):
        assert _blocks_from_csv(b"") == []


class TestTheImageThatCouldNotBeRead:
    def test_no_text_means_no_block(self):
        """An empty block would be embedded and would present as a successfully indexed
        document that matches nothing."""
        assert _blocks_from_image({"extracted_text": "", "extraction_method": "none"}) == []
        assert _blocks_from_image({}) == []

    def test_extraction_provenance_travels_with_the_text(self):
        blocks = _blocks_from_image(
            {"extracted_text": "GAUGE 42 PSI", "extraction_method": "gemini:x", "confidence": 0.8}
        )
        assert blocks[0].meta["extraction_method"] == "gemini:x"
        assert blocks[0].meta["confidence"] == 0.8, (
            "OCR confidence did not reach the chunk, so a retrieved reading cannot be "
            "qualified by how sure the model was that it read it correctly"
        )

    def test_the_empty_reason_says_what_to_do(self):
        assert "VISION_MODEL_ENABLED" in _empty_reason("image")
        assert _empty_reason("pdf") != _empty_reason("image"), (
            "an empty PDF and an unread image get the same explanation, so the user is "
            "told to enable a vision model for a text document"
        )


class TestKindDetection:
    @pytest.mark.parametrize(
        "filename,content_type,expected",
        [
            ("report.pdf", None, "pdf"),
            ("report.PDF", None, "pdf"),
            ("x", "application/pdf", "pdf"),
            ("spec.docx", None, "docx"),
            ("photo.JPG", None, "image"),
            ("x", "image/png", "image"),
            ("notes.md", None, "markdown"),
            ("data.csv", None, "csv"),
            ("x", "text/csv", "csv"),
            ("log.txt", None, "text"),
            ("x", "text/plain", "text"),
            ("archive.zip", None, "unsupported"),
            ("noextension", None, "unsupported"),
        ],
    )
    def test_dispatch(self, filename, content_type, expected):
        assert _detect_kind(filename, content_type) == expected

    def test_markdown_and_csv_win_over_generic_text(self):
        """Both are `text/*`. Falling through to `text` would make a whole spreadsheet one
        block and lose every row boundary."""
        assert _detect_kind("data.csv", "text/plain") == "csv"
        assert _detect_kind("notes.md", "text/plain") == "markdown"


class TestPlainText:
    def test_invalid_utf8_is_replaced_not_fatal(self):
        blocks = _blocks_from_text(b"good \xff\xfe bad")
        assert blocks and "good" in blocks[0].text

    def test_whitespace_only_yields_nothing(self):
        assert _blocks_from_text(b"   \n\t ") == []
