"""Guard for ERPDataTransformer numeric parsing.

_parse_currency / _parse_number returned None on ANY failure via a bare
`except:` with no log, so a malformed ERP currency value silently became NULL in
financial records — invisible data loss. (Bare `except:` also swallowed
KeyboardInterrupt/SystemExit.) The parsers now narrow the catch and log a
warning when a *present* value fails to parse, while a genuinely absent value
(None) stays silent.
"""

from unittest.mock import patch

from app.services.erp_data_transformer import ERPDataTransformer


def _txf():
    return ERPDataTransformer(organization_id="org-1", integration_id="int-1")


def test_valid_currency_and_number_parse():
    t = _txf()
    assert t._parse_currency("123.45") == 123.45
    assert t._parse_currency(10) == 10.0
    assert t._parse_number("0.5") == 0.5


def test_absent_value_is_silent_none():
    t = _txf()
    with patch("app.services.erp_data_transformer.logger") as log:
        assert t._parse_currency(None) is None
        assert t._parse_number(None) is None
    log.warning.assert_not_called()


def test_malformed_currency_returns_none_and_logs():
    t = _txf()
    with patch("app.services.erp_data_transformer.logger") as log:
        assert t._parse_currency("1,234.56") is None  # comma format lost -> None
        assert t._parse_currency("abc") is None
    assert log.warning.call_count == 2, log.warning.call_args_list
    assert all(c.args[0] == "erp_currency_parse_failed" for c in log.warning.call_args_list)


def test_malformed_number_returns_none_and_logs():
    t = _txf()
    with patch("app.services.erp_data_transformer.logger") as log:
        assert t._parse_number("not-a-number") is None
    log.warning.assert_called_once()
    assert log.warning.call_args.args[0] == "erp_number_parse_failed"


def test_parsers_do_not_swallow_keyboard_interrupt():
    """A bare `except:` would catch KeyboardInterrupt; the narrowed one must not."""
    class Boom:
        def __float__(self):
            raise KeyboardInterrupt

    t = _txf()
    try:
        t._parse_currency(Boom())
    except KeyboardInterrupt:
        pass
    else:  # pragma: no cover
        raise AssertionError("KeyboardInterrupt was swallowed by the parser")
