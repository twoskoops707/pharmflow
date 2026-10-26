"""SSP display must get the phone Client Hints. The page host already does."""

from __future__ import annotations

from automation.mantis_inject_proxy import _is_dabflow_host, _is_ssp_display_host


def test_ssp_display_host_is_hinted() -> None:
    assert _is_ssp_display_host("ssp.mantis.marketing") is True
    assert _is_ssp_display_host("SSP.mantis.marketing:443") is True
    assert _is_ssp_display_host("bids.mantis.marketing") is False
    assert _is_dabflow_host("getdabflow.app") is True
    assert _is_ssp_display_host("getdabflow.app") is False
