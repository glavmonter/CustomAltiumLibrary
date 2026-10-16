"""Тесты внешнего API (library/api.py) и ключей API.

Запуск (нужен пользователь БД с правом CREATEDB — тестовая база создаётся миграциями):
    docker compose run --rm --entrypoint python -e DB_USER=postgres -e DB_PASSWORD=<POSTGRES_PASSWORD> \\
        web manage.py test library
"""

import json
from datetime import timedelta

from django.contrib.admin.models import ADDITION, CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.utils import timezone

from .models import (ApiKey, Component, ComponentClass, ComponentFootprint, Footprint, Manufacturer, Supplier,
                     Symbol)

BULK, REFS, LIST = "/api/v1/components/bulk/", "/api/v1/references/", "/api/v1/components/"
E24 = ["10", "11", "12", "13", "15", "16", "18", "20", "22", "24", "27", "30",
       "33", "36", "39", "43", "47", "51", "56", "62", "68", "75", "82", "91"]


class ApiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.vishay = Manufacturer.objects.create(name="Vishay")
        cls.yageo = Manufacturer.objects.create(name="Yageo")
        cls.lcsc = Supplier.objects.create(name="LCSC", product_url_template="https://lcsc.com/{pn}")
        cls.chipdip = Supplier.objects.create(name="ChipDip")
        passive = ComponentClass.objects.create(name="Passive")
        cls.resistors = ComponentClass.objects.create(name="Resistor", parent=passive, view_name="resistors")
        ComponentClass.objects.create(name="Resistor", parent=None)   # одноимённый класс в другой ветке
        cls.symbol = Symbol.objects.create(library_ref="STD_RES", library_path="symbols/STD/STD_RES.SchLib")
        cls.fp0603 = Footprint.objects.create(footprint_ref="RESC1608X50AN",
                                              footprint_path="footprints/Resistors/RESC1608X50AN.PcbLib")
        cls.fp0402 = Footprint.objects.create(footprint_ref="RESC1005X40AN",
                                              footprint_path="footprints/Resistors/RESC1005X40AN.PcbLib")
        Footprint.objects.create(footprint_ref="DUP", footprint_path="footprints/A/DUP.PcbLib")
        Footprint.objects.create(footprint_ref="DUP", footprint_path="footprints/B/DUP.PcbLib")

        User = get_user_model()
        cls.editor = User.objects.create_user("editor", password="x", is_staff=True)
        cls.editor.user_permissions.add(*Permission.objects.filter(
            codename__in=["add_component", "change_component", "view_component"]))
        cls.reader = User.objects.create_user("reader", password="x", is_staff=True)
        cls.reader.user_permissions.add(Permission.objects.get(codename="view_component"))
        cls.adder = User.objects.create_user("adder", password="x", is_staff=True)
        cls.adder.user_permissions.add(*Permission.objects.filter(codename__in=["add_component", "view_component"]))

    def key_for(self, user, **fields):
        key = ApiKey(name=f"test {user.username}", user=user, **fields)
        raw = key.issue()
        key.save()
        return raw

    def setUp(self):
        self.key = self.key_for(self.editor)

    def call(self, method, url, body=None, key=None, **extra):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {key or self.key}"} if key is not False else {}
        if method == "post":
            return self.client.post(url, data=json.dumps(body), content_type="application/json", **headers, **extra)
        return self.client.get(url, body or {}, **headers, **extra)

    def series(self, values, **defaults):
        """Ряд резисторов Vishay CRCW0603 1%: общие поля в defaults, в элементах — MPN и номинал."""
        return {
            "defaults": {"manufacturer": "Vishay", "class": "Passive / Resistor", "symbol": "STD_RES",
                         "footprints": ["RESC1608X50AN"], "voltage": "75V", "tolerance": "1%",
                         "tolerance_pct": 1, **defaults},
            "components": [{"manufacturer_pn": f"CRCW0603{v}K0FKEA", "value": f"{v}k", "value_si": float(v) * 1000,
                            "suppliers": [{"supplier": "LCSC", "pn": f"C{v}"}]} for v in values],
        }


class AuthTests(ApiTestCase):
    def test_no_key(self):
        response = self.call("get", REFS, key=False)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Bearer", response["WWW-Authenticate"])

    def test_wrong_key_and_x_api_key_header(self):
        self.assertEqual(self.call("get", REFS, key="alk_00000000_wrong").status_code, 401)
        self.assertEqual(self.client.get(REFS, HTTP_X_API_KEY=self.key).status_code, 200)

    def test_revoked_expired_inactive_user(self):
        revoked = self.key_for(self.editor, is_active=False)
        expired = self.key_for(self.editor, expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.call("get", REFS, key=revoked).status_code, 401)
        self.assertEqual(self.call("get", REFS, key=expired).status_code, 401)
        self.editor.is_active = False
        self.editor.save()
        self.assertEqual(self.call("get", REFS).status_code, 401)

    def test_only_hash_is_stored_and_last_used_updated(self):
        stored = ApiKey.objects.get(user=self.editor)
        self.assertNotIn(self.key, (stored.key_hash, stored.prefix))
        self.assertIsNone(stored.last_used_at)
        self.call("get", REFS)
        stored.refresh_from_db()
        self.assertIsNotNone(stored.last_used_at)

    def test_permissions(self):
        reader = self.key_for(self.reader)
        adder = self.key_for(self.adder)
        self.assertEqual(self.call("post", BULK, self.series(["10"]), key=reader).status_code, 403)
        self.assertEqual(self.call("post", BULK, {**self.series(["10"]), "mode": "upsert"}, key=adder).status_code, 403)
        self.assertEqual(self.call("post", BULK, self.series(["10"]), key=adder).status_code, 201)

    def test_no_csrf_or_session_needed(self):
        self.client = self.client_class(enforce_csrf_checks=True)
        self.assertEqual(self.call("post", BULK, self.series(["10"])).status_code, 201)


class ReferenceTests(ApiTestCase):
    def test_references(self):
        data = self.call("get", REFS).json()
        self.assertIn({"id": self.resistors.id, "name": "Resistor", "path": "Passive / Resistor",
                       "altium_table": "resistors"}, data["classes"])
        self.assertIn("Vishay", [m["name"] for m in data["manufacturers"]])
        self.assertIn("RESC1608X50AN", [f["ref"] for f in data["footprints"]])


class BulkTests(ApiTestCase):
    def test_series_created_with_slots_and_log(self):
        response = self.call("post", BULK, self.series(E24))
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual((data["created"], data["updated"]), (24, 0))
        self.assertTrue(all(r["design_item_id"].startswith("CMP-") for r in data["results"]))
        c = Component.objects.get(manufacturer_pn="CRCW060347K0FKEA")
        self.assertEqual((c.value, c.voltage, c.tolerance, c.value_si), ("47k", "75V", "1%", 47000.0))
        self.assertEqual((c.component_class, c.symbol, c.manufacturer), (self.resistors, self.symbol, self.vishay))
        self.assertEqual([s.footprint for s in c.footprint_slots.all()], [self.fp0603])
        self.assertEqual([(s.supplier.name, s.supplier_pn, s.url) for s in c.supplier_slots.all()],
                         [("LCSC", "C47", "https://lcsc.com/C47")])
        log = LogEntry.objects.filter(action_flag=ADDITION, user=self.editor)
        self.assertEqual(log.count(), 24)
        self.assertIn("Через API", log.first().change_message)

    def test_all_or_nothing(self):
        body = self.series(["10", "22"])
        body["components"].append({"manufacturer_pn": "BAD", "value_si": "not a number"})
        response = self.call("post", BULK, body)
        self.assertEqual(response.status_code, 400)
        results = response.json()["results"]
        self.assertNotIn("errors", results[0])
        self.assertTrue(any("value_si" in e for e in results[2]["errors"]))
        self.assertEqual(Component.objects.count(), 0)

    def test_dry_run_writes_nothing(self):
        data = self.call("post", BULK, {**self.series(E24[:5]), "dry_run": True}).json()
        self.assertEqual((data["dry_run"], data["created"]), (True, 5))
        self.assertEqual(Component.objects.count(), 0)

    def test_create_rejects_existing_upsert_updates(self):
        self.call("post", BULK, self.series(["10", "22"]))
        response = self.call("post", BULK, self.series(["10"]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("mode=upsert", response.json()["results"][0]["errors"][0])

        # upsert: поля из запроса обновляются, не переданные — сохраняются
        body = {"mode": "upsert", "components": [
            {"manufacturer": "Vishay", "manufacturer_pn": "CRCW060310K0FKEA", "tolerance": "0.5%",
             "footprints": ["RESC1608X50AN", "RESC1005X40AN"]}]}
        data = self.call("post", BULK, body).json()
        self.assertEqual((data["created"], data["updated"]), (0, 1))
        c = Component.objects.get(manufacturer_pn="CRCW060310K0FKEA")
        self.assertEqual((c.tolerance, c.voltage, c.value), ("0.5%", "75V", "10k"))
        self.assertEqual([s.footprint for s in c.footprint_slots.all()], [self.fp0603, self.fp0402])
        self.assertEqual(c.supplier_slots.count(), 1)   # suppliers не переданы — остались
        self.assertEqual(LogEntry.objects.filter(action_flag=CHANGE).count(), 1)

    def test_same_mpn_other_manufacturer_is_new(self):
        self.call("post", BULK, self.series(["10"]))
        body = self.series(["10"], manufacturer="Yageo")
        self.assertEqual(self.call("post", BULK, body).status_code, 201)

    def test_reference_errors_are_explained(self):
        body = {"components": [
            {"manufacturer": "Nobody", "manufacturer_pn": "A", "class": "Passive / Resistor", "symbol": "STD_RES"},
            {"manufacturer": "Vishay", "manufacturer_pn": "B", "class": "Resistor", "symbol": "STD_RES"},
            {"manufacturer": "Vishay", "manufacturer_pn": "C", "class": "Passive / Resistor", "symbol": "NOPE",
             "footprints": ["DUP"]},
            {"manufacturer": "Vishay", "manufacturer_pn": "D", "class": "Passive / Resistor", "symbol": "STD_RES",
             "footprints": ["RESC1608X50AN"] * 2, "suppliers": [{"supplier": "Nope", "pn": "1"}]},
            {"manufacturer": "Vishay", "manufacturer_pn": "D", "class": "Passive / Resistor", "symbol": "STD_RES"},
            {"manufacturer": "Vishay", "class": "Passive / Resistor", "symbol": "STD_RES", "colour": "red"},
        ]}
        errors = [" | ".join(r.get("errors", [])) for r in self.call("post", BULK, body).json()["results"]]
        self.assertIn("производитель «Nobody» не найден", errors[0])
        self.assertIn("неоднозначен", errors[1])
        self.assertIn("символ «NOPE»", errors[2])
        self.assertIn("в нескольких файлах", errors[2])
        self.assertIn("указано дважды", errors[3])
        self.assertIn("магазин «Nope» не найден", errors[3])
        self.assertIn("повторяется в запросе", errors[4])
        self.assertIn("нет manufacturer_pn", errors[5])
        self.assertIn("неизвестные поля: colour", errors[5])

    def test_footprint_by_path_and_id(self):
        body = self.series(["10", "22"])
        body["components"][0]["footprints"] = [{"ref": "DUP", "path": "footprints/B/DUP.PcbLib"}]
        body["components"][1]["footprints"] = [{"id": self.fp0402.id}]
        self.assertEqual(self.call("post", BULK, body).status_code, 201)
        c = Component.objects.get(manufacturer_pn="CRCW060310K0FKEA")
        self.assertEqual(c.footprint_slots.get().footprint.footprint_path, "footprints/B/DUP.PcbLib")

    def test_validation_of_fields(self):
        body = self.series(["10"], status="sold-out", datasheet_url="not a url")
        errors = " | ".join(self.call("post", BULK, body).json()["results"][0]["errors"])
        self.assertIn("status", errors)
        self.assertIn("datasheet_url", errors)

    @override_settings(LIBRARY_API_MAX_ITEMS=3)
    def test_items_limit(self):
        self.assertEqual(self.call("post", BULK, self.series(E24[:4])).status_code, 413)

    @override_settings(LIBRARY_API_MAX_BODY_BYTES=200)
    def test_body_limit(self):
        self.assertEqual(self.call("post", BULK, self.series(E24)).status_code, 413)

    def test_bad_json(self):
        response = self.client.post(BULK, data="{oops", content_type="application/json",
                                    HTTP_AUTHORIZATION=f"Bearer {self.key}")
        self.assertEqual(response.status_code, 400)


class ListTests(ApiTestCase):
    def test_find_by_mpn(self):
        self.call("post", BULK, self.series(["10", "22"]))
        data = self.call("get", LIST, {"manufacturer": "vishay", "mpn": "CRCW060322K0FKEA"}).json()
        self.assertEqual(data["count"], 1)
        item = data["results"][0]
        self.assertEqual((item["value"], item["class"], item["footprints"][0]["ref"]),
                         ("22k", "Passive / Resistor", "RESC1608X50AN"))
        self.assertEqual((item["value_si"], item["tolerance_pct"]), (22000.0, 1.0))   # числа, не строки


class ApiKeyAdminTests(ApiTestCase):
    def test_staff_can_issue_key_only_for_self(self):
        self.editor.user_permissions.add(*Permission.objects.filter(codename__in=["add_apikey", "view_apikey"]))
        superuser = get_user_model().objects.create_superuser("root", password="x")
        self.client.force_login(self.editor)
        response = self.client.post("/admin/library/apikey/add/",
                                    {"name": "script", "user": superuser.pk, "is_active": "on"}, follow=True)
        self.assertEqual(ApiKey.objects.filter(user=superuser).count(), 0)
        self.assertNotIn("script", [k.name for k in ApiKey.objects.all()])
        self.assertContains(response, "Выберите корректный вариант")

        response = self.client.post("/admin/library/apikey/add/",
                                    {"name": "script", "user": self.editor.pk, "is_active": "on"}, follow=True)
        key = ApiKey.objects.get(name="script")
        shown = [str(m) for m in response.context["messages"]]
        raw = shown[0].split("<code style=\"user-select:all\">")[1].split("</code>")[0]
        self.assertEqual(ApiKey.find(raw), key)
        self.assertEqual(self.call("get", REFS, key=raw).status_code, 200)
        # повторно ключ не показывается
        page = self.client.get(f"/admin/library/apikey/{key.pk}/change/")
        self.assertNotContains(page, raw)


class OpenApiTests(TestCase):
    def test_spec_served_without_key_and_lists_all_routes(self):
        response = self.client.get("/api/v1/openapi.yaml")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/yaml"))
        text = response.content.decode()
        self.assertTrue(text.startswith("openapi: 3.1"))
        for route in ("/api/v1/references/:", "/api/v1/components/:", "/api/v1/components/bulk/:"):
            self.assertIn(route, text)


class AdminMenuTests(ApiTestCase):
    def sections(self, response):
        return {app["app_label"]: [m["object_name"] for m in app["models"]] for app in response.context["app_list"]}

    def test_superuser_order_and_api_keys_in_auth(self):
        self.client.force_login(get_user_model().objects.create_superuser("root", password="x"))
        menu = self.sections(self.client.get("/admin/"))
        self.assertEqual(menu["library"], ["ComponentClass", "Component", "Symbol", "Footprint",
                                           "Manufacturer", "Supplier"])
        self.assertEqual(menu["auth"][-1], "ApiKey")
        self.assertIn("Group", menu["auth"])
        self.assertNotIn("ApiKey", self.sections(self.client.get("/admin/library/"))["library"])
        self.assertIn("ApiKey", self.sections(self.client.get("/admin/auth/"))["auth"])

    def test_staff_without_auth_perms_sees_only_api_keys_there(self):
        self.editor.user_permissions.add(*Permission.objects.filter(codename__in=["add_apikey", "view_apikey"]))
        self.client.force_login(self.editor)
        menu = self.sections(self.client.get("/admin/"))
        self.assertEqual(menu["auth"], ["ApiKey"])
        self.assertEqual(menu["library"], ["Component"])
        self.assertEqual(self.client.get("/admin/auth/").status_code, 200)
