"""DriverWaitTimeCreate no longer offers fields nothing ever honours (FS-907).

Nine fields on the shared DriverWaitTimeBase -- check_out_at, docked_at, unloaded_at,
total_wait_minutes, detention_minutes, demurrage_minutes, detention_charge,
demurrage_charge, is_billed -- are all computed by `close_driver_wait_time` at checkout.
DriverWaitTimeCreate used to inherit all of them, so a caller could send
`{"is_billed": true, "detention_charge": 0}` at creation time and the API would accept it
with a 200, silently ignoring every one -- an operator watching the request succeed had no
way to know none of it was recorded.
"""
from __future__ import annotations

from app.models.schemas import DriverWaitTimeCreate, DriverWaitTimeResponse

COMPUTED_AT_CHECKOUT = {
    "check_out_at",
    "docked_at",
    "unloaded_at",
    "total_wait_minutes",
    "detention_minutes",
    "demurrage_minutes",
    "detention_charge",
    "demurrage_charge",
    "is_billed",
}


class TestCreateDoesNotOfferComputedFields:
    def test_none_of_the_nine_are_on_the_create_schema(self):
        present = COMPUTED_AT_CHECKOUT & set(DriverWaitTimeCreate.model_fields)
        assert not present, (
            f"DriverWaitTimeCreate declares {present}, which nothing at creation time "
            f"computes -- a caller can set them and the API silently ignores it"
        )

    def test_the_genuine_create_time_fields_are_still_there(self):
        """Not overcorrected: the fields the handler DOES read must still be declared."""
        genuine = {"driver_id", "trailer_id", "check_in_at", "detention_rate", "demurrage_rate", "metadata"}
        missing = genuine - set(DriverWaitTimeCreate.model_fields)
        assert not missing, f"DriverWaitTimeCreate is missing genuine input fields: {missing}"

    def test_the_response_schema_still_reports_all_nine(self):
        """The fix is schema-side on Create only -- Response must be untouched, since
        the whole point of computing these fields is to report them back."""
        missing = COMPUTED_AT_CHECKOUT - set(DriverWaitTimeResponse.model_fields)
        assert not missing, (
            f"DriverWaitTimeResponse is missing {missing} -- the checkout figures can no "
            f"longer be reported to a caller"
        )
