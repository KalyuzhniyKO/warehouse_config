import json
import subprocess
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase


class PwaSupportTests(TestCase):
    def streamed_content(self, response):
        if response.streaming:
            return b"".join(response.streaming_content)
        return response.content

    def test_static_manifest_webmanifest_opens_with_required_install_fields(self):
        response = self.client.get("/static/manifest.webmanifest")

        self.assertEqual(response.status_code, 200)
        manifest = json.loads(self.streamed_content(response))
        self.assertEqual(manifest["name"], "YANTOS Warehouse")
        self.assertEqual(manifest["short_name"], "Warehouse")
        self.assertEqual(manifest["start_url"], "/uk/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["theme_color"], "#f5c400")
        self.assertEqual(
            manifest["icons"],
            [
                {
                    "src": "/static/icons/yantos-warehouse.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any maskable",
                }
            ],
        )

    def test_svg_pwa_icon_is_text_only(self):
        icon = Path("static/icons/yantos-warehouse.svg")

        self.assertTrue(icon.exists())
        self.assertIn("<svg", icon.read_text())
        self.assertIn("WH", icon.read_text())

    def test_base_template_includes_static_manifest_and_tablet_pwa_meta_tags(self):
        template = Path("templates/base.html").read_text()

        self.assertIn('{% load i18n static core_extras %}', template)
        self.assertIn('rel="manifest" href="{% static \'manifest.webmanifest\' %}"', template)
        self.assertIn('name="theme-color" content="#f5c400"', template)
        self.assertIn('name="mobile-web-app-capable" content="yes"', template)
        self.assertIn('name="apple-mobile-web-app-capable" content="yes"', template)
        self.assertIn('name="apple-mobile-web-app-title" content="YANTOS Warehouse"', template)
        self.assertIn('navigator.serviceWorker.register("/service-worker.js")', template)

    def test_service_worker_opens_from_site_root(self):
        response = self.client.get("/service-worker.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")
        service_worker = self.streamed_content(response).decode()
        self.assertIn('addEventListener("fetch"', service_worker)

    def test_service_worker_only_caches_safe_get_static_assets(self):
        service_worker = Path("static/service-worker.js").read_text()

        self.assertIn('request.method !== "GET"', service_worker)
        self.assertIn('url.pathname.startsWith(STATIC_ASSET_PREFIX)', service_worker)
        self.assertIn('".svg"', service_worker)
        self.assertIn('".webmanifest"', service_worker)
        self.assertNotIn('".png"', service_worker)
        self.assertNotIn('".jpg"', service_worker)
        self.assertNotIn('".jpeg"', service_worker)
        self.assertNotIn('".ico"', service_worker)
        self.assertNotIn('".webp"', service_worker)

    def test_service_worker_does_not_cache_stock_operation_pages(self):
        service_worker = Path("static/service-worker.js").read_text()

        self.assertIn("STOCK_OPERATION_PREFIXES", service_worker)
        self.assertIn('"/uk/stock/"', service_worker)
        self.assertIn('"/uk/stockbalances/"', service_worker)
        self.assertIn('"/uk/movements/"', service_worker)
        self.assertIn("isStockOperationPage(url)", service_worker)
        self.assertIn("return false;", service_worker)

    def test_uk_home_page_contains_manifest_link_and_theme_color(self):
        user = get_user_model().objects.create_user(username="pwa-user", password="pw")
        self.client.force_login(user)

        response = self.client.get("/uk/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rel="manifest" href="/static/manifest.webmanifest"')
        self.assertContains(response, 'name="theme-color" content="#f5c400"')

    def test_no_binary_assets_were_added(self):
        forbidden_extensions = (".png", ".jpg", ".jpeg", ".ico", ".webp", ".mo")
        tracked_files = subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True)
        unstaged_files = subprocess.check_output(["git", "diff", "--name-only"], text=True)
        untracked_files = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"], text=True
        )
        changed_files = tracked_files + unstaged_files + untracked_files

        self.assertFalse(
            any(path.endswith(forbidden_extensions) for path in changed_files.splitlines()),
            changed_files,
        )
