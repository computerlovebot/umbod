import pytest
from scripts.release_versions import main


@pytest.mark.parametrize(
    ("tag", "sdk_version", "release_version"),
    [
        ("umbod-v1.2.3", "1.2.3", "1.2.3"),
        ("umbod-v0.0.0", "0.0.0", "0.0.0"),
        ("umbod-v1.2.3-beta.0", "1.2.3b0", "1.2.3-beta.0"),
        ("umbod-v1.2.3-beta.12", "1.2.3b12", "1.2.3-beta.12"),
    ],
)
def test_tag_cli_emits_synchronized_versions(
    tag: str, sdk_version: str, release_version: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--tag", tag]) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"sdk_version={sdk_version}",
        f"image_version={release_version}",
        f"chart_version={release_version}",
    ]


@pytest.mark.parametrize(
    "tag",
    [
        "",
        "1.2.3",
        "v1.2.3",
        "desktop-v1.2.3",
        "refs/tags/umbod-v1.2.3",
        "umbod-v01.2.3",
        "umbod-v1.02.3",
        "umbod-v1.2.03",
        "umbod-v1.2.3-beta.01",
        "umbod-v1.2",
        "umbod-v1.2.3.4",
        "umbod-v1x2x3",
        "umbod-v1.2.3b1",
        "umbod-v1.2.3-beta",
        "umbod-v1.2.3-beta.-1",
        "umbod-v1.2.3-alpha.1",
        "umbod-v1.2.3-rc.1",
        "umbod-v1.2.3+build",
        "umbod-v1.2.3-beta.1+build",
        "umbod-v1.2.3\n",
        " umbod-v1.2.3",
        "umbod-v1.2.3 ",
        "umbod-v１.2.3",
    ],
)
def test_tag_cli_rejects_noncanonical_tags_without_outputs(tag: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--tag", tag])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Unsupported release tag" in captured.err


@pytest.mark.parametrize("arguments", [[], ["--current", "1.2.3"], ["--latest"], ["--shared"]])
def test_tag_cli_requires_tag_and_rejects_obsolete_modes(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2
