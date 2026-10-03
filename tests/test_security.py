"""The security fixes from the 2026-10-02 audit: input validation, signature trust, ACL checks, admin gating."""

import ctypes
import os

import pytest

from storemgr import admin, helper, secure, winapps

MS_SIGNER = "CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US"
MARKETPLACE = "CN=Microsoft Marketplace CA G 026, OU=EOC, O=Microsoft Corporation, L=Redmond, S=Washington, C=US"
JOB = "0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize("fam", ["Microsoft.WindowsCalculator_8wekyb3d8bbwe", "OpenAI.Codex_2p2nqsd0c76g0",
                                 "5319275A.WhatsAppDesktop_cv1g1gvanyjgm"])
def test_family_re_accepts_real_names(fam):
    assert winapps.FAMILY_RE.match(fam)


@pytest.mark.parametrize("fam", ["x'; Remove-Item C:\\ -Recurse; '_8wekyb3d8bbwe", 'a" -Action Cleanup "_8wekyb3d8bbwe',
                                 "Microsoft.*_8wekyb3d8bbwe", "9WZDNCRFJBMP", "Foo_8WEKYB3D8BBWE", "Foo_8wekyb3d8bbwe\n",
                                 "Foo Bar_8wekyb3d8bbwe", ""])
def test_family_re_rejects_injection_and_junk(fam):
    assert not winapps.FAMILY_RE.match(fam)


def test_dn_parses_quoted_values():
    d = winapps.dn('CN=Contoso, O="Contoso, Ltd", C=US')
    assert d == {"CN": "Contoso", "O": "Contoso, Ltd", "C": "US"}


def test_store_and_microsoft_signed_packages_are_trusted():
    assert winapps.signature_trusted("Valid", MS_SIGNER, MARKETPLACE, None)
    assert winapps.signature_trusted("Valid", MS_SIGNER, MARKETPLACE, MS_SIGNER)
    assert winapps.signature_trusted(
        "Valid", MS_SIGNER, "CN=Microsoft Windows Production PCA 2011, O=Microsoft Corporation, C=US", None)


def test_third_party_store_package_must_match_installed_publisher():
    pub = "CN=24803D75-212C-471A-BC57-9EF86AB91435"
    assert winapps.signature_trusted("Valid", pub, MARKETPLACE, pub)
    assert winapps.signature_trusted("Valid", "CN=24803D75-212C-471A-BC57-9EF86AB91435", MARKETPLACE, pub + " ")
    assert not winapps.signature_trusted("Valid", "CN=SomeoneElse", MARKETPLACE, pub)


@pytest.mark.parametrize("status,signer,issuer", [
    ("NotSigned", MS_SIGNER, MARKETPLACE),
    ("HashMismatch", MS_SIGNER, MARKETPLACE),
    # Microsoft's code-signing service for other people: issuer O is Microsoft, but it isn't Microsoft's code
    ("Valid", "CN=Evil Ltd, O=Evil Ltd", "CN=Microsoft ID Verified CS EOC CA 01, O=Microsoft Corporation, C=US"),
    ("Valid", "CN=Evil, O=Microsoft Corporation Fans Ltd", "CN=Microsoft ID Verified CS AOC CA 02, O=Microsoft Corporation"),
    ("Valid", "CN=Evil, O=Evil", "CN=Microsoft Marketplace CA G 026, O=Not Microsoft"),
    ("Valid", "CN=Evil, O=Evil", "CN=Fake Microsoft Marketplace CA G 026, O=Microsoft Corporation"),
])
def test_untrusted_signatures_rejected(status, signer, issuer):
    assert not winapps.signature_trusted(status, signer, issuer, None)


def test_writers_in_sddl():
    program_files = "O:BAD:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICIIO;GA;;;CO)(A;OICI;0x1200a9;;;BU)"
    assert secure.writers_in(program_files) == []
    g_drive = "O:S-1-5-21-1-2-3-1001D:AI(A;ID;FA;;;BA)(A;OICIID;0x1301bf;;;AU)(A;ID;0x1200a9;;;BU)"
    assert secure.writers_in(g_drive) == ["owner S-1-5-21-1-2-3-1001", "S-1-5-11"]
    programdata = "O:SYD:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;CI;DCLCRPCR;;;BU)"
    assert secure.writers_in(programdata) == ["S-1-5-32-545"]
    assert secure.writers_in("O:BAD:NO_ACCESS_CONTROL")
    assert secure.writers_in("O:BAD:(A;;FA;;;WD)") == ["S-1-1-0"]


def test_protected_sddl_is_itself_protected():
    assert secure.writers_in("O:BA" + secure.PROTECTED_SDDL) == []


def test_real_acls():
    assert secure.untrusted_writers(os.environ["SystemRoot"] + r"\System32") == []
    assert "S-1-5-32-545" in secure.untrusted_writers(os.environ["ProgramData"])


@pytest.mark.parametrize("argv", [
    ["unjam", "--job", JOB, "--family", "x'; whoami; '_8wekyb3d8bbwe"],
    ["unjam", "--job", "../../evil"],
    ["unjam"],
    ["format-c", "--job", JOB],
    ["store-auto-update", "--job", JOB, "--value", "maybe"],
])
def test_helper_rejects_bad_arguments(argv):
    p = helper._parser("--elevated", ["unjam", "install", "cleanup", "store-auto-update"])
    p.add_argument("--value", choices=["on", "off"], default="off")
    assert helper._parse(p, argv) is None


def test_helper_accepts_good_arguments():
    p = helper._parser("--system-task", ["move-rslc", "cleanup-deleted"])
    a = helper._parse(p, ["move-rslc", "--job", JOB, "--family", "Microsoft.Todos_8wekyb3d8bbwe"])
    assert a.family == "Microsoft.Todos_8wekyb3d8bbwe"


def test_elevated_main_refuses_bad_input_before_doing_anything():
    assert helper.elevated_main(["unjam", "--job", JOB, "--family", "bad'name_8wekyb3d8bbwe"]) == 2
    assert helper.system_main(["move-rslc", "--job", "nope"]) == 2


def test_admin_refuses_from_a_modifiable_copy(monkeypatch):
    monkeypatch.setattr(admin, "untrusted_code", lambda: [r"G:\StoreManager (S-1-5-11)"])
    called = []
    monkeypatch.setattr(admin._shell32, "ShellExecuteExW", lambda *a: called.append(a))
    r = admin.unjam("Microsoft.Todos_8wekyb3d8bbwe")
    assert not r["ok"] and "installed My Store" in r["errors"][0] and not called


def test_admin_validates_family_before_prompting(monkeypatch):
    monkeypatch.setattr(admin, "_elevated", lambda *a, **k: pytest.fail("must not elevate"))
    assert not admin.unjam("evil'_8wekyb3d8bbwe")["ok"]


@pytest.mark.skipif(not ctypes.windll.shell32.IsUserAnAdmin(), reason="needs an elevated test run")
def test_ensure_protected_dir_moves_aside_a_squatted_folder(tmp_path):
    d = tmp_path / "squat"
    d.mkdir()
    notes = secure.ensure_protected_dir(d)
    assert secure.protected(d)
    assert notes and (tmp_path / notes[0].split(" aside to ")[1].split("\\")[-1]).exists()
