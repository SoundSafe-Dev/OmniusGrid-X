-- 068_seal_status_has_no_default.sql
--
-- A trailer whose seal nobody reported must not claim the seal was intact (FS-666).
--
-- `yard_trailers.seal_status` is one of intact / broken / missing. Migration 050 gave it a
-- SERVER DEFAULT of 'intact', and the ORM carries `default="intact"` beside it. So a check-in
-- that says nothing about the seal records a POSITIVE SECURITY CLAIM: not "unknown", but
-- "this seal was intact". It is the most reassuring of the three values and it is written
-- precisely when nobody looked.
--
-- WHY 050 DID THIS, AND WHY IT WAS RIGHT ABOUT THE OTHER 38 COLUMNS. That migration gave
-- server defaults to 39 logistics columns whose ORM `default=` fired only through SQLAlchemy,
-- so a raw INSERT wrote NULL and the API then could not serialise the row. Its reasoning:
--
--     "a NULL `is_active` or `status` is a missing value, not an unknown moment, so writing
--      the documented default is a correction, not an invention"
--
-- That holds for `is_active`, for `{}` on a JSON column, for every other column in the list.
-- It does not hold here, and the difference is what the value ASSERTS. An absent `is_active`
-- has an obvious intended reading; an absent seal check has none, and supplying one invents
-- an inspection result. `seal_status` was swept along with 38 columns whose defaults are
-- genuinely harmless.
--
-- WHAT THIS MIGRATION DOES NOT DO, and this is the part worth reading. It does NOT reverse
-- 050's backfill. That statement was:
--
--     UPDATE yard_trailers SET seal_status = 'intact' WHERE seal_status IS NULL;
--
-- so every row that had never recorded a seal check now says 'intact', and it is
-- INDISTINGUISHABLE from a row where a guard genuinely reported an intact seal. That
-- information is gone. Setting them all back to NULL would erase the real checks to undo the
-- invented ones, which trades a known fabrication for a certain data loss. Existing rows are
-- left alone and this limitation is recorded rather than quietly worked around.
--
-- So: this stops the fabrication for every check-in from here on. It cannot undo the ones
-- already written, and nothing can.
--
-- Idempotent: DROP DEFAULT is repeatable and the guard makes it safe where the table is absent.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'yard_trailers'
      AND column_name = 'seal_status'
  ) THEN
    EXECUTE 'ALTER TABLE yard_trailers ALTER COLUMN seal_status DROP DEFAULT';
  END IF;
END $$;
