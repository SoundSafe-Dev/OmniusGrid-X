"""The chunker must not lose text, and must not blend two pages into one citation (FS-440).

`rag_chunker` is 152 lines of pure function with **no test references at all**, sitting in
the middle of the document-intake path: everything a user uploads passes through it on its
way to being searchable. Its own docstring calls it "trivially unit-testable".

WHAT FAILS SILENTLY HERE, which is why these are the assertions chosen:

  * **Text dropped.** A segment that falls out of the packing loop is not an error — it is
    a fact that is never indexed, never retrieved, and never cited. The document uploads
    fine, the chunk count looks plausible, and the answer to a question about that
    paragraph is "I don't know". Nothing in the system can report this, because nothing
    else knows what was in the file.
  * **A chunk that spans two blocks.** The whole point of chunking per block is that a
    citation resolves to exactly one page or section. A chunk carrying text from page 4
    and the `meta` of page 3 produces a citation that looks precise and points at the
    wrong place — worse than no citation, because a reader checks it and is reassured.
  * **Overlap that does not overlap.** The reason for overlap is that a fact spanning a
    boundary survives whole in at least one chunk. If it silently stops working, retrieval
    degrades for exactly the facts that sit at boundaries, and nothing looks broken.

WHAT IS NOT ASSERTED, deliberately: exact chunk sizes. `max_chars` is a target, not a
bound — the packing loop appends a unit after taking an overlap tail, so a chunk can exceed
it — and pinning the arithmetic would break on any tuning change while proving nothing
about correctness.
"""

from __future__ import annotations

import re

import pytest

from app.services.rag_chunker import Chunk, TextBlock, chunk_blocks, chunk_text


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def _sentences(count: int, word: str = "alpha") -> str:
    return " ".join(f"This is sentence number {i} about {word}." for i in range(count))


class TestNothingIsLost:
    """The silent failure: a fact that is never indexed and never missed."""

    def test_every_word_survives_chunking(self):
        text = _sentences(60)
        chunks = chunk_text(text, target_tokens=20, overlap_tokens=4, chars_per_token=4.0)
        assert chunks, "the chunker returned nothing for a 60-sentence document"

        source = _words(text)
        emitted = set()
        for chunk in chunks:
            emitted.update(_words(chunk.text))
        missing = [w for w in dict.fromkeys(source) if w not in emitted]
        assert not missing, (
            f"{len(missing)} distinct words never appear in any chunk: {missing[:8]}. A "
            f"dropped segment is unsearchable forever and nothing downstream can notice"
        )

    def test_a_single_oversized_segment_is_split_not_dropped(self):
        """One sentence longer than the whole chunk budget. The hard-split path."""
        long_word_run = " ".join(f"token{i}" for i in range(400))
        chunks = chunk_text(long_word_run, target_tokens=20, chars_per_token=4.0)
        emitted = set()
        for chunk in chunks:
            emitted.update(_words(chunk.text))
        missing = [w for w in _words(long_word_run) if w not in emitted]
        assert not missing, f"the hard-split dropped {len(missing)} tokens: {missing[:5]}"

    def test_a_segment_with_no_spaces_is_still_split(self):
        """`_hard_split` falls back to a blind cut when there is no space to break on —
        a base64 blob or a long identifier, both of which appear in real documents."""
        blob = "A" * 500
        chunks = chunk_text(blob, target_tokens=10, chars_per_token=4.0)
        assert chunks
        assert sum(len(c.text) for c in chunks) >= len(blob), (
            "characters were lost splitting a segment with no break points"
        )

    def test_a_short_trailing_sliver_is_merged_not_discarded(self):
        text = _sentences(9) + " Tiny."
        chunks = chunk_text(text, target_tokens=25, overlap_tokens=0, chars_per_token=4.0)
        assert any("tiny" in _words(c.text) for c in chunks), (
            "the trailing sliver was dropped rather than merged into the previous chunk"
        )


class TestACitationPointsAtOneBlock:
    """Chunks never cross a block boundary — that is what makes a citation resolvable."""

    def test_no_chunk_mixes_two_blocks(self):
        blocks = [
            TextBlock(text=_sentences(30, "pageone"), meta={"page": 1}),
            TextBlock(text=_sentences(30, "pagetwo"), meta={"page": 2}),
        ]
        chunks = chunk_blocks(blocks, target_tokens=20, overlap_tokens=4, chars_per_token=4.0)
        for chunk in chunks:
            words = set(_words(chunk.text))
            assert not ({"pageone"} <= words and {"pagetwo"} <= words), (
                f"a chunk carries text from BOTH blocks: {chunk.text[:120]!r}. Its meta "
                f"names one page, so the citation would point at the wrong one"
            )

    def test_each_chunk_carries_its_own_blocks_meta(self):
        blocks = [
            TextBlock(text=_sentences(20, "pageone"), meta={"page": 1}),
            TextBlock(text=_sentences(20, "pagetwo"), meta={"page": 2}),
        ]
        chunks = chunk_blocks(blocks, target_tokens=20, overlap_tokens=4, chars_per_token=4.0)
        for chunk in chunks:
            words = set(_words(chunk.text))
            expected = 1 if "pageone" in words else 2
            assert chunk.meta.get("page") == expected, (
                f"a chunk of page {expected} carries meta {chunk.meta} — a citation that "
                f"looks precise and points at the wrong page is worse than none, because "
                f"a reader checks it and is reassured"
            )

    def test_an_empty_block_is_skipped_without_shifting_the_others(self):
        blocks = [
            TextBlock(text=_sentences(6, "first"), meta={"page": 1}),
            TextBlock(text="   \n  ", meta={"page": 2}),
            TextBlock(text=_sentences(6, "third"), meta={"page": 3}),
        ]
        chunks = chunk_blocks(blocks, target_tokens=40, chars_per_token=4.0)
        pages = {c.meta.get("page") for c in chunks}
        assert pages == {1, 3}, f"expected pages 1 and 3 only, got {pages}"


class TestOverlapActuallyOverlaps:
    def test_adjacent_chunks_share_text(self):
        chunks = chunk_text(
            _sentences(40), target_tokens=20, overlap_tokens=8, chars_per_token=4.0
        )
        assert len(chunks) > 2, "not enough chunks to test overlap"
        shared = [
            bool(set(_words(a.text)[-4:]) & set(_words(b.text)[:8]))
            for a, b in zip(chunks, chunks[1:])
        ]
        assert sum(shared) >= len(shared) // 2, (
            "adjacent chunks do not share a trailing window, so a fact spanning a boundary "
            "survives in neither — retrieval degrades for exactly the facts at boundaries "
            "and nothing looks broken"
        )

    def test_zero_overlap_is_honoured(self):
        """A caller asking for no overlap must get none — the setting is not advisory."""
        chunks = chunk_text(
            _sentences(30), target_tokens=20, overlap_tokens=0, chars_per_token=4.0
        )
        joined = " ".join(c.text for c in chunks)
        source = _sentences(30)
        assert len(_words(joined)) == len(_words(source)), (
            "with overlap_tokens=0 the chunks should partition the text exactly; "
            "duplication means the overlap tail is being taken anyway"
        )


class TestItAlwaysTerminates:
    """The packing loop takes an overlap tail and then appends — the guard that keeps it
    making progress is `overlap_chars = min(overlap_chars, max_chars - 1)`."""

    @pytest.mark.parametrize(
        # At and above the 32-character floor (FS-441). `(1, 1)` and `(2, 100)` were here
        # and now raise by design — a 4-character budget is the shredding case, covered by
        # `test_a_degenerate_target_is_refused_not_shredded` instead. What matters here is
        # overlap >= target, which the clamp has to absorb.
        "target,overlap", [(8, 8), (10, 10), (10, 40), (8, 100)]
    )
    def test_overlap_at_or_above_the_target_does_not_hang(self, target, overlap):
        chunks = chunk_text(
            _sentences(25), target_tokens=target, overlap_tokens=overlap, chars_per_token=4.0
        )
        assert chunks, f"target={target} overlap={overlap} produced nothing"

    def test_a_degenerate_target_is_refused_not_shredded(self):
        """FOUND BY THIS TEST FAILING (FS-441).

        It originally asserted the text survived a `target_tokens=0`, and it did — as
        ELEVEN CHUNKS, one per character. `max_chars` was floored at 1, which is not a
        fallback, it is a different operation.

        `rag_ingestion` passes `settings.RAG_CHUNK_TOKENS`, which is env-overridable, so one
        mistyped deployment variable would embed a 40-page manual one letter at a time,
        report `indexed: True` with an enormous `num_chunks`, and retrieve nothing. Success,
        an embedding bill, and no searchable document — and nothing downstream can tell that
        corpus apart from a genuinely unhelpful one.
        """
        with pytest.raises(ValueError, match="shred|characters"):
            chunk_text("hello world", target_tokens=0, chars_per_token=4.0)

    def test_a_workable_target_is_still_accepted(self):
        """The floor must not reject a small-but-sane budget — 8 tokens is unusual, not
        nonsense, and refusing it would trade one silent failure for a loud wrong one."""
        chunks = chunk_text("hello world", target_tokens=8, chars_per_token=4.0)
        assert chunks and "hello world" in " ".join(c.text for c in chunks)


class TestOrdinals:
    def test_they_run_sequentially_across_the_whole_document(self):
        blocks = [
            TextBlock(text=_sentences(12, "first"), meta={"page": 1}),
            TextBlock(text=_sentences(12, "second"), meta={"page": 2}),
        ]
        chunks = chunk_blocks(blocks, target_tokens=20, chars_per_token=4.0)
        assert [c.ordinal for c in chunks] == list(range(len(chunks))), (
            "ordinals are not 0-based and sequential across blocks; they are the only "
            "thing recording a chunk's position in the source document"
        )


class TestTheDegenerateInputsAScannerProduces:
    def test_no_blocks_is_no_chunks(self):
        assert chunk_blocks([]) == []

    def test_a_whitespace_only_document_yields_nothing(self):
        assert chunk_text("   \n\t  \n ") == []

    def test_a_document_of_table_rows_keeps_each_row_whole(self):
        """Serialized tables arrive newline-separated and each row is its own segment.
        A row split down the middle is a row that means nothing."""
        rows = "\n".join(f"Asset-{i} | 12.{i} | OK" for i in range(30))
        chunks = chunk_text(rows, target_tokens=30, overlap_tokens=0, chars_per_token=4.0)
        joined = " ".join(c.text for c in chunks)
        for i in range(30):
            assert f"Asset-{i} | 12.{i} | OK" in joined, (
                f"row {i} did not survive chunking intact"
            )

    def test_the_return_type_is_what_the_ingester_expects(self):
        chunks = chunk_text("A short document.")
        assert all(isinstance(c, Chunk) for c in chunks)
        assert all(isinstance(c.meta, dict) for c in chunks)
