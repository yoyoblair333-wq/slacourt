"""
Direct-mode tests for contracts/sla_court.py.

Real GenVM v0.2.16 Python SDK in-process; status pages and the model are
mocked by regex. `direct_vm.run_validator()` replays the captured validator
through the CURRENT mocks, so swapping mocks between the leader run and the
replay simulates a validator that read something different.

Run:  python -m pytest tests/direct -q
"""

import json
from pathlib import Path

import pytest

from conftest import set_tx_time

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = str(ROOT / "contracts" / "sla_court.py")

NOW = "2026-11-20T12:00:00Z"
STATUS = "https://status.example.com/history"
INCIDENT = "https://status.example.com/incidents/abc123"
OTHER = "https://status.example.com/incidents/def456"
FEE = 1_000_000
TIERS = "[[43,10],[240,25]]"

PAGE = ("Incident with Pull Requests. Resolved - Between 11:30 and 16:00 UTC merges timed out. "
        "Investigating - Nov 16, 11:59 UTC. This incident affected: Pull Requests and Actions.")


def hx(a) -> str:
    if hasattr(a, "as_hex"):
        return a.as_hex
    return "0x" + bytes(a).hex()


@pytest.fixture
def sent(direct_vm):
    out = []

    def hook(_vm, req):
        if "PostMessage" in req:
            m = req["PostMessage"]
            out.append({"to": hx(m["address"]).lower(), "value": int(m["value"])})
        return None

    direct_vm._gl_call_hook = hook
    return out


def page(vm, url=INCIDENT, body=PAGE, status=200, ctype="text/html; charset=utf-8"):
    vm.mock_web("^" + url.replace(".", r"\.") + "$", {"method": "GET", "response": {
        "status": status, "headers": {"content-type": ctype.encode()}, "body": body.encode()}})


def model(vm, status="FOUND", start="2026-11-16T11:30", end="2026-11-16T16:00", severity="degraded", url=INCIDENT):
    vm.mock_llm(r"fetched from " + url.replace(".", r"\."), json.dumps(
        {"status": status, "start_utc": start, "end_utc": end, "severity": severity}))


@pytest.fixture
def court(direct_vm, direct_deploy, direct_alice, sent):
    direct_vm.sender = direct_alice
    c = direct_deploy(CONTRACT, 5)
    set_tx_time(direct_vm, NOW)
    return c


@pytest.fixture
def sla(direct_vm, court, direct_bob):
    """Bob is the provider; pool funded with 500_000 wei, open enrollment."""
    direct_vm.sender = direct_bob
    direct_vm.value = 500_000
    sid = court.register_sla("Pull Requests", "global", [STATUS], 9990, FEE, TIERS, "degraded", True)
    direct_vm.value = 0
    return sid


def file(vm, court, who, sid, start="2026-11-16T12:00Z", end="2026-11-16T15:45Z", ev=INCIDENT):
    vm.sender = who
    return court.file_claim(sid, start, end, "", ev)


def at(vm, ts):
    set_tx_time(vm, ts)


# ------------------------------------------------------------------ registration

class TestRegister:
    def test_register_and_read(self, court, sla, direct_bob):
        s = court.get_sla(sla)
        assert s["service"] == "Pull Requests" and s["urls"] == [STATUS]
        assert s["balance"] == "500000" and s["free"] == "500000" and s["encumbered"] == "0"
        assert s["tiers"] == [[43, 10], [240, 25]]
        assert s["allowed_downtime_min_x10"] == 432          # 99.9 % of 30 days = 43.2 min
        assert s["provider"].lower() == hx(direct_bob).lower()

    @pytest.mark.parametrize("tiers,msg", [
        ("[]", "1..5"), ("[[43,10],[40,25]]", "ascending"), ("[[43,10],[240,5]]", "ascending"),
        ("[[43,101]]", "1..100"), ("nope", "JSON"), ("[[43,10.5]]", "integers"),
    ])
    def test_bad_tiers(self, direct_vm, court, tiers, msg):
        with direct_vm.expect_revert(msg):
            court.register_sla("Svc", "global", [STATUS], 9990, FEE, tiers)

    @pytest.mark.parametrize("url", ["http://status.example.com/", "https://127.0.0.1/", "https://localhost/",
                                     "https://a.example:8443/x", "https://u:p@status.example.com/"])
    def test_bad_urls(self, direct_vm, court, url):
        with direct_vm.expect_revert("url"):
            court.register_sla("Svc", "global", [url], 9990, FEE, TIERS)

    def test_bad_uptime_and_fee(self, direct_vm, court):
        with direct_vm.expect_revert("uptime_bp"):
            court.register_sla("Svc", "global", [STATUS], 10000, FEE, TIERS)
        with direct_vm.expect_revert("monthly_fee"):
            court.register_sla("Svc", "global", [STATUS], 9990, 0, TIERS)


# ------------------------------------------------------------------ happy path

class TestFlow:
    def test_confirmed_claim_pays_after_window(self, direct_vm, court, sla, direct_charlie, sent):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm)
        model(direct_vm)
        r = court.assess(cid)
        # claimed 12:00-15:45 inside incident 11:30-16:00 -> 225 min -> over 43 -> 10 %
        assert r["record"] == {"verdict": "CONFIRMED", "overlaps": True, "minutes": 225, "severity": "degraded"}
        assert r["credit"] == str(FEE * 10 // 100) and r["status"] == "ASSESSED"
        assert court.get_sla(sla)["encumbered"] == "100000"
        with direct_vm.expect_revert("challenge window open"):
            court.finalize(cid)
        at(direct_vm, "2026-11-20T12:06:00Z")
        f = court.finalize(cid)
        assert f["status"] == "FINAL"
        s = court.get_sla(sla)
        assert s["balance"] == "400000" and s["encumbered"] == "0" and s["paid"] == "100000"
        assert court.credit_of(hx(direct_charlie)) == "100000"
        direct_vm.sender = direct_charlie
        assert court.withdraw_credit() == 100000
        assert sent[-1] == {"to": hx(direct_charlie).lower(), "value": 100000}
        assert court.credit_of(hx(direct_charlie)) == "0"
        with direct_vm.expect_revert("no credit"):
            court.withdraw_credit()

    def test_minutes_floor_to_15_and_top_tier(self, direct_vm, court, sla, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla, "2026-11-16T11:00Z", "2026-11-16T15:44Z")
        page(direct_vm)
        model(direct_vm)
        r = court.assess(cid)
        # overlap 11:30..15:44 = 254 min -> floored to 240 -> NOT over 240 -> 10 %
        assert r["record"]["minutes"] == 240 and r["credit"] == "100000"

    def test_top_tier(self, direct_vm, court, sla, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla, "2026-11-16T11:00Z", "2026-11-16T16:30Z")
        page(direct_vm)
        model(direct_vm)
        r = court.assess(cid)
        assert r["record"]["minutes"] == 270 and r["credit"] == "250000"

    def test_below_first_tier_pays_zero(self, direct_vm, court, sla, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla, "2026-11-16T15:30Z", "2026-11-16T16:30Z")
        page(direct_vm)
        model(direct_vm)
        r = court.assess(cid)
        assert r["record"]["minutes"] == 30 and r["credit"] == "0"

    def test_min_severity_outage_blocks_degraded(self, direct_vm, court, direct_bob, direct_charlie):
        direct_vm.sender = direct_bob
        direct_vm.value = 500_000
        sid = court.register_sla("Pull Requests", "global", [STATUS], 9990, FEE, TIERS, "outage", True)
        direct_vm.value = 0
        cid = file(direct_vm, court, direct_charlie, sid)
        page(direct_vm)
        model(direct_vm, severity="degraded")
        assert court.assess(cid)["credit"] == "0"


# ------------------------------------------------------------------ adversarial

class TestFailClosed:
    def test_window_outside_incident_pays_zero(self, direct_vm, court, sla, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla, "2026-11-16T18:00Z", "2026-11-16T20:00Z")
        page(direct_vm)
        model(direct_vm)
        r = court.assess(cid)
        assert r["record"] == {"verdict": "NO_OVERLAP", "overlaps": False, "minutes": 0, "severity": "none"}
        assert r["credit"] == "0"

    @pytest.mark.parametrize("status", [404, 500, 403])
    def test_unreadable_page_pays_zero(self, direct_vm, court, sla, direct_charlie, status):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm, status=status, body="error")
        model(direct_vm)
        r = court.assess(cid)
        assert r["record"]["verdict"] == "UNREADABLE" and r["credit"] == "0"

    def test_binary_content_type_unreadable(self, direct_vm, court, sla, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm, ctype="application/pdf")
        model(direct_vm)
        assert court.assess(cid)["record"]["verdict"] == "UNREADABLE"

    def test_page_not_naming_service_is_no_incident(self, direct_vm, court, sla, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm, body="Incident with Webhooks. Resolved 16:00 UTC.")
        model(direct_vm)       # even if the model claims FOUND, the deterministic gate fails closed
        r = court.assess(cid)
        assert r["record"]["verdict"] == "NO_INCIDENT" and r["credit"] == "0"
        assert r["details"][0]["why"] == "service_not_named"

    @pytest.mark.parametrize("reply", ["not json", '{"status":"MAYBE"}',
                                       '{"status":"FOUND","start_utc":"yesterday","end_utc":"","severity":"degraded"}',
                                       '{"status":"FOUND","start_utc":"2026-11-16T16:00","end_utc":"2026-11-16T11:00","severity":"degraded"}',
                                       '{"status":"FOUND","start_utc":"2026-11-16T11:00","end_utc":"2026-11-16T16:00","severity":"catastrophic"}',
                                       '{"status":"AMBIGUOUS","start_utc":"","end_utc":"","severity":""}'])
    def test_bad_or_ambiguous_model_reply_pays_zero(self, direct_vm, court, sla, direct_charlie, reply):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm)
        direct_vm.mock_llm(r"fetched from", reply)
        r = court.assess(cid)
        assert r["record"]["verdict"] == "AMBIGUOUS" and r["credit"] == "0"

    def test_not_found_reply(self, direct_vm, court, sla, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm)
        model(direct_vm, status="NOT_FOUND", start="", end="", severity="")
        assert court.assess(cid)["record"]["verdict"] == "NO_INCIDENT"

    def test_conflicting_sources_are_ambiguous(self, direct_vm, court, direct_bob, direct_charlie):
        a, b = "https://status.example.com/", "https://status.other.net/"
        direct_vm.sender = direct_bob
        direct_vm.value = 500_000
        sid = court.register_sla("Pull Requests", "global", [a, b], 9990, FEE, TIERS, "degraded", True)
        direct_vm.value = 0
        cid = file(direct_vm, court, direct_charlie, sid, ev="")
        page(direct_vm, a)
        page(direct_vm, b)
        model(direct_vm, url=a, end="2026-11-16T16:00")
        model(direct_vm, url=b, end="2026-11-16T13:00")
        assert court.assess(cid)["record"]["verdict"] == "AMBIGUOUS"


class TestDuplicatesAndAccess:
    def test_duplicate_overlapping_claim_rejected(self, direct_vm, court, sla, direct_charlie):
        file(direct_vm, court, direct_charlie, sla)
        with direct_vm.expect_revert("duplicate claim"):
            file(direct_vm, court, direct_charlie, sla, "2026-11-16T13:00Z", "2026-11-16T14:00Z", ev=OTHER)

    def test_split_window_same_incident_rejected(self, direct_vm, court, sla, direct_charlie):
        file(direct_vm, court, direct_charlie, sla, "2026-11-16T12:00Z", "2026-11-16T12:59Z", ev="")
        with direct_vm.expect_revert("within 24 h"):
            file(direct_vm, court, direct_charlie, sla, "2026-11-16T13:00Z", "2026-11-16T13:59Z", ev="")

    def test_same_incident_url_rejected(self, direct_vm, court, sla, direct_charlie):
        file(direct_vm, court, direct_charlie, sla, "2026-11-10T12:00Z", "2026-11-10T13:00Z")
        with direct_vm.expect_revert("already claimed"):
            file(direct_vm, court, direct_charlie, sla)

    def test_other_customer_may_claim_same_incident(self, direct_vm, court, sla, direct_charlie, direct_alice):
        file(direct_vm, court, direct_charlie, sla)
        assert file(direct_vm, court, direct_alice, sla) == 2

    def test_provider_cannot_claim(self, direct_vm, court, sla, direct_bob):
        with direct_vm.expect_revert("provider cannot claim"):
            file(direct_vm, court, direct_bob, sla)

    def test_closed_enrollment(self, direct_vm, court, direct_bob, direct_charlie):
        direct_vm.sender = direct_bob
        sid = court.register_sla("Pull Requests", "global", [STATUS], 9990, FEE, TIERS, "degraded", False)
        with direct_vm.expect_revert("not enrolled"):
            file(direct_vm, court, direct_charlie, sid)
        direct_vm.sender = direct_bob
        court.enroll(sid, hx(direct_charlie))
        assert file(direct_vm, court, direct_charlie, sid) >= 1

    @pytest.mark.parametrize("start,end,msg", [
        ("2026-11-16T12:00Z", "2026-11-16T12:10Z", "15 minutes"),
        ("2026-11-01T12:00Z", "2026-11-16T12:10Z", "7 days"),
        ("2026-11-20T11:00Z", "2026-11-20T13:00Z", "must have ended"),
        ("2024-01-01T12:00Z", "2024-01-01T13:00Z", "within the last"),
        ("16 Nov noon", "2026-11-16T13:00Z", "YYYY-MM-DD"),
    ])
    def test_bad_windows(self, direct_vm, court, sla, direct_charlie, start, end, msg):
        with direct_vm.expect_revert(msg):
            file(direct_vm, court, direct_charlie, sla, start, end)

    def test_evidence_url_must_be_registered_host(self, direct_vm, court, sla, direct_charlie):
        with direct_vm.expect_revert("registered status-page host"):
            file(direct_vm, court, direct_charlie, sla, ev="https://evil.example.net/incident")

    def test_assess_twice_rejected(self, direct_vm, court, sla, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm)
        model(direct_vm)
        court.assess(cid)
        with direct_vm.expect_revert("not FILED"):
            court.assess(cid)


class TestPool:
    def test_provider_cannot_withdraw_encumbered(self, direct_vm, court, sla, direct_bob, direct_charlie, sent):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm)
        model(direct_vm)
        court.assess(cid)                    # reserves 100_000 of 500_000
        direct_vm.sender = direct_bob
        with direct_vm.expect_revert("exceeds unencumbered"):
            court.withdraw(sla, 400_001)
        assert court.withdraw(sla, 400_000) == 100_000
        assert sent[-1]["value"] == 400_000
        s = court.get_sla(sla)
        assert s["free"] == "0" and s["encumbered"] == "100000"

    def test_only_provider_withdraws_or_tops_up(self, direct_vm, court, sla, direct_charlie):
        direct_vm.sender = direct_charlie
        with direct_vm.expect_revert("only the provider"):
            court.withdraw(sla, 1)
        direct_vm.value = 5
        with direct_vm.expect_revert("only the provider"):
            court.top_up(sla)
        direct_vm.value = 0

    def test_top_up(self, direct_vm, court, sla, direct_bob):
        direct_vm.sender = direct_bob
        direct_vm.value = 1_000
        assert court.top_up(sla) == 501_000
        direct_vm.value = 0

    def test_pool_cannot_overdraw(self, direct_vm, court, direct_bob, direct_charlie, direct_alice):
        """Pool of 150_000, two claims each worth 100_000: the second is capped at 50_000."""
        direct_vm.sender = direct_bob
        direct_vm.value = 150_000
        sid = court.register_sla("Pull Requests", "global", [STATUS], 9990, FEE, TIERS, "degraded", True)
        direct_vm.value = 0
        page(direct_vm)
        model(direct_vm)
        c1 = file(direct_vm, court, direct_charlie, sid)
        c2 = file(direct_vm, court, direct_alice, sid)
        assert court.assess(c1)["credit"] == "100000"
        r2 = court.assess(c2)
        assert r2["credit"] == "50000" and r2["capped"] is True
        s = court.get_sla(sid)
        assert s["free"] == "0" and s["encumbered"] == "150000"
        direct_vm.sender = direct_bob
        with direct_vm.expect_revert("exceeds unencumbered"):
            court.withdraw(sid, 1)
        at(direct_vm, "2026-11-20T12:10:00Z")
        court.finalize(c1)
        court.finalize(c2)
        s = court.get_sla(sid)
        assert s["balance"] == "0" and s["encumbered"] == "0" and s["paid"] == "150000"

    def test_empty_pool_pays_zero_capped(self, direct_vm, court, direct_bob, direct_charlie):
        direct_vm.sender = direct_bob
        sid = court.register_sla("Pull Requests", "global", [STATUS], 9990, FEE, TIERS, "degraded", True)
        cid = file(direct_vm, court, direct_charlie, sid)
        page(direct_vm)
        model(direct_vm)
        r = court.assess(cid)
        assert r["credit"] == "0" and r["capped"] is True


class TestAppeal:
    def test_appeal_reruns_and_releases_reservation(self, direct_vm, court, sla, direct_bob, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm)
        model(direct_vm)
        assert court.assess(cid)["credit"] == "100000"
        # provider appeals; the page now shows the incident was elsewhere in time
        direct_vm.clear_mocks()
        page(direct_vm)
        model(direct_vm, start="2026-11-16T17:00", end="2026-11-16T18:00")
        at(direct_vm, "2026-11-20T12:03:00Z")
        direct_vm.sender = direct_bob
        r = court.appeal(cid)
        assert r["record"]["verdict"] == "NO_OVERLAP" and r["credit"] == "0" and r["appeals"] == 1
        assert court.get_sla(sla)["encumbered"] == "0"
        # the window restarts from the appeal
        at(direct_vm, "2026-11-20T12:06:00Z")
        with direct_vm.expect_revert("challenge window open"):
            court.finalize(cid)
        with direct_vm.expect_revert("appeal already used"):
            court.appeal(cid)
        at(direct_vm, "2026-11-20T12:09:00Z")
        assert court.finalize(cid)["status"] == "FINAL"
        assert court.credit_of(hx(direct_charlie)) == "0"

    def test_appeal_after_window_rejected(self, direct_vm, court, sla, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm)
        model(direct_vm)
        court.assess(cid)
        at(direct_vm, "2026-11-20T12:05:00Z")
        direct_vm.sender = direct_charlie
        with direct_vm.expect_revert("challenge window has closed"):
            court.appeal(cid)

    def test_outsider_cannot_appeal(self, direct_vm, court, sla, direct_charlie, direct_alice):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm)
        model(direct_vm)
        court.assess(cid)
        direct_vm.sender = direct_alice
        with direct_vm.expect_revert("only the customer or the provider"):
            court.appeal(cid)

    def test_final_claim_cannot_be_appealed_or_refinalized(self, direct_vm, court, sla, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla)
        page(direct_vm)
        model(direct_vm)
        court.assess(cid)
        at(direct_vm, "2026-11-20T12:06:00Z")
        court.finalize(cid)
        with direct_vm.expect_revert("only an ASSESSED"):
            court.finalize(cid)
        direct_vm.sender = direct_charlie
        with direct_vm.expect_revert("only an ASSESSED"):
            court.appeal(cid)


# ------------------------------------------------------------------ consensus

class TestConsensus:
    def setup_claim(self, vm, court, sla, who):
        cid = file(vm, court, who, sla)
        page(vm)
        model(vm)
        court.assess(cid)
        return cid

    def test_validator_agrees_on_same_reading(self, direct_vm, court, sla, direct_charlie):
        self.setup_claim(direct_vm, court, sla, direct_charlie)
        assert direct_vm.run_validator() is True

    def test_validator_agrees_when_raw_times_differ_but_canonical_equal(self, direct_vm, court, sla, direct_charlie):
        """Leader read 11:30-16:00, this validator reads 11:59-16:26: the claimed window
        12:00-15:45 lies inside both, so the canonical record is identical."""
        self.setup_claim(direct_vm, court, sla, direct_charlie)
        direct_vm.clear_mocks()
        page(direct_vm)
        model(direct_vm, start="2026-11-16T11:59", end="2026-11-16T16:26")
        assert direct_vm.run_validator() is True

    def test_minutes_differ_no_consensus(self, direct_vm, court, sla, direct_charlie):
        """Leader 225 min, validator reads an end of 15:30 -> 210 min. Both are in the
        same 10 % tier, but the canonical field differs, so the validator rejects."""
        self.setup_claim(direct_vm, court, sla, direct_charlie)
        direct_vm.clear_mocks()
        page(direct_vm)
        model(direct_vm, end="2026-11-16T15:30")
        assert direct_vm.run_validator() is False

    def test_severity_differs_no_consensus(self, direct_vm, court, sla, direct_charlie):
        self.setup_claim(direct_vm, court, sla, direct_charlie)
        direct_vm.clear_mocks()
        page(direct_vm)
        model(direct_vm, severity="outage")
        assert direct_vm.run_validator() is False

    def test_validator_cannot_read_page_no_consensus(self, direct_vm, court, sla, direct_charlie):
        self.setup_claim(direct_vm, court, sla, direct_charlie)
        direct_vm.clear_mocks()
        page(direct_vm, status=503, body="down")
        assert direct_vm.run_validator() is False

    @pytest.mark.parametrize("forged", [
        {"record": {"verdict": "CONFIRMED", "overlaps": True, "minutes": 300, "severity": "degraded"}, "details": []},
        {"record": {"verdict": "CONFIRMED", "overlaps": True, "minutes": 226, "severity": "degraded"}, "details": []},
        {"record": {"verdict": "CONFIRMED", "overlaps": True, "minutes": 225, "severity": "degraded", "extra": 1}, "details": []},
        {"record": {"verdict": "NO_OVERLAP", "overlaps": False, "minutes": 225, "severity": "none"}, "details": []},
        {"record": {"verdict": "CONFIRMED", "overlaps": True, "minutes": 225, "severity": "outage"}, "details": []},
        {"record": "CONFIRMED", "details": []},
    ])
    def test_forged_leader_rejected(self, direct_vm, court, sla, direct_charlie, forged):
        self.setup_claim(direct_vm, court, sla, direct_charlie)
        assert direct_vm.run_validator(leader_result=forged) is False

    def test_honest_leader_shape_accepted(self, direct_vm, court, sla, direct_charlie):
        self.setup_claim(direct_vm, court, sla, direct_charlie)
        ok = {"record": {"verdict": "CONFIRMED", "overlaps": True, "minutes": 225, "severity": "degraded"}, "details": []}
        assert direct_vm.run_validator(leader_result=ok) is True

    def test_leader_error_rejected(self, direct_vm, court, sla, direct_charlie):
        self.setup_claim(direct_vm, court, sla, direct_charlie)
        assert direct_vm.run_validator(leader_error=Exception("boom")) is False


class TestViews:
    def test_lists_and_quote(self, direct_vm, court, sla, direct_charlie):
        cid = file(direct_vm, court, direct_charlie, sla)
        assert court.list_slas()[0]["id"] == sla
        assert court.list_claims()[0]["id"] == cid and court.list_claims()[0]["status"] == "FILED"
        assert court.quote(sla, "CONFIRMED", 250, "degraded") == "250000"
        assert court.quote(sla, "NO_OVERLAP", 250, "degraded") == "0"
        st = court.stats()
        assert st["slas"] == 1 and st["claims"] == 1 and st["challenge_minutes"] == 5
