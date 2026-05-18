from pathlib import Path

from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class DeploymentAssetTests(SimpleTestCase):
    def read_file(self, relative_path):
        return (PROJECT_ROOT / relative_path).read_text()

    def test_gunicorn_systemd_service_example_exists_and_targets_project(self):
        service = self.read_file("deploy/systemd/warehouse-gunicorn.service")

        self.assertIn("User=warehouse", service)
        self.assertIn("WorkingDirectory=/opt/warehouse_config", service)
        self.assertIn("EnvironmentFile=/opt/warehouse_config/.env", service)
        self.assertIn("/opt/warehouse_config/venv/bin/gunicorn", service)
        self.assertIn("--bind 127.0.0.1:8001", service)
        self.assertIn("--timeout 120", service)
        self.assertIn("config.wsgi:application", service)
        self.assertIn("Restart=always", service)
        self.assertIn("RestartSec=5", service)

    def test_apache_example_serves_static_and_proxies_dynamic_requests(self):
        apache_config = self.read_file("deploy/apache/warehouse.conf.example")

        self.assertIn("Alias /static/ /opt/warehouse_config/staticfiles/", apache_config)
        self.assertIn("ProxyPass /static/ !", apache_config)
        self.assertIn("ProxyPass / http://127.0.0.1:8001/", apache_config)
        self.assertIn("ProxyPassReverse / http://127.0.0.1:8001/", apache_config)
        self.assertNotIn("Alias /manifest.webmanifest", apache_config)
        self.assertNotIn("Alias /service-worker.js", apache_config)

    def test_deployment_docs_include_systemd_and_pwa_endpoint_checks(self):
        docs = self.read_file("DEPLOY_APACHE_UBUNTU.md")

        self.assertIn("sudo cp deploy/systemd/warehouse-gunicorn.service", docs)
        self.assertIn("sudo systemctl enable warehouse-gunicorn", docs)
        self.assertIn("sudo systemctl start warehouse-gunicorn", docs)
        self.assertIn("sudo systemctl status warehouse-gunicorn", docs)
        self.assertIn("curl -I http://127.0.0.1:8001/uk/", docs)
        self.assertIn("curl -I http://127.0.0.1:8081/uk/", docs)
        self.assertIn("curl -I http://127.0.0.1:8081/manifest.webmanifest", docs)
        self.assertIn("curl -I http://127.0.0.1:8081/service-worker.js", docs)
        self.assertIn('sudo pkill -f "manage.py runserver" 2>/dev/null || true', docs)

    def test_server01_gunicorn_switchover_runbook_exists_with_key_markers(self):
        runbook_path = PROJECT_ROOT / "docs/SERVER01_GUNICORN_SWITCHOVER.md"
        self.assertTrue(runbook_path.exists())

        runbook = runbook_path.read_text()

        self.assertIn("warehouse-gunicorn", runbook)
        self.assertIn("/opt/warehouse_config", runbook)
        self.assertIn("systemctl restart warehouse-gunicorn", runbook)
        self.assertIn("curl -I http://127.0.0.1:8081/manifest.webmanifest", runbook)
        self.assertIn("curl -I http://127.0.0.1:8081/service-worker.js", runbook)
        self.assertIn("curl -I http://10.52.83.10/manifest.webmanifest", runbook)
        self.assertIn("curl -I http://10.52.83.10/service-worker.js", runbook)
        self.assertIn("emergency temporary fallback", runbook)
        self.assertIn("python manage.py runserver 0.0.0.0:8000", runbook)
