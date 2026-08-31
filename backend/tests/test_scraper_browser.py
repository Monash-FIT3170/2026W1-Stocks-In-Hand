from pathlib import Path

from scrapers.browser import chromium_launch_options


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_lambda_chromium_uses_writable_paths_and_disables_gpu(monkeypatch) -> None:
    monkeypatch.setenv("AWS_LAMBDA_RUNTIME_API", "runtime.test")
    monkeypatch.setenv("HOME", "/home/read-only")

    options = chromium_launch_options(extra_args=("--disable-http2",))

    assert options["headless"] is True
    assert options["env"]["HOME"] == "/tmp"
    assert options["env"]["TMPDIR"] == "/tmp"
    assert options["env"]["XDG_CACHE_HOME"] == "/tmp/.cache"
    assert options["env"]["XDG_CONFIG_HOME"] == "/tmp/.config"
    assert "--disable-gpu" in options["args"]
    assert "--no-zygote" in options["args"]
    assert "--disable-software-rasterizer" not in options["args"]
    assert "--disable-http2" in options["args"]
    assert "--single-process" not in options["args"]


def test_all_deployed_scrapers_use_shared_browser_options() -> None:
    company_directory = REPOSITORY_ROOT / "backend" / "scrapers" / "companies"
    for module in company_directory.glob("*.py"):
        source = module.read_text(encoding="utf-8")
        if "chromium.launch" not in source:
            continue
        assert "chromium_launch_options" in source, module.name
        assert '"--headless=new"' not in source, module.name

    downloader = (
        REPOSITORY_ROOT / "backend" / "lambdas" / "source_download.py"
    ).read_text(encoding="utf-8")
    assert "chromium_launch_options" in downloader
    assert '"--headless=new"' not in downloader


def test_scraper_image_smoke_tests_browser_before_release() -> None:
    dockerfile = (
        REPOSITORY_ROOT / "backend" / "Dockerfile.scraper"
    ).read_text(encoding="utf-8")

    assert "smoke_scraper_browser.py" in dockerfile
    assert "AWS_LAMBDA_RUNTIME_API=build-smoke" in dockerfile
