"""Regression coverage for the shared South African Desk shell."""

from pathlib import Path

import frappe
from frappe.tests.classes import IntegrationTestCase, UnitTestCase

from za_local_core import hooks
from za_local_core.navigation import (
	APP_NAME,
	APP_ROUTE,
	APP_TITLE,
	LOCALISATION_APPS,
	WORKSPACE_SPECS,
	get_available_workspaces,
	sync_shared_navigation,
)

# The apps the suite currently ships. LOCALISATION_APPS is deliberately wider: it is
# a cleanup allow-list that still names the retired apps, so it cannot be used to
# assert that a workspace points at a live one.
CURRENT_SUITE_APPS = frozenset({"za_local_core", "za_local_payroll"})


class TestSharedNavigationContract(UnitTestCase):
	def test_required_runtime_apps_are_declared(self):
		self.assertEqual(set(hooks.required_apps), {"erpnext"})
		# frappe is always installed, so the marketplace review rejects it here.
		self.assertNotIn("frappe", hooks.required_apps)
		self.assertTrue(all(hooks.required_apps))
		self.assertEqual(len(hooks.required_apps), len(set(hooks.required_apps)))

	def test_core_is_the_only_apps_screen_owner(self):
		self.assertEqual("SA Localisation", hooks.app_title)
		self.assertEqual(APP_TITLE, hooks.app_title)
		# The Apps-screen tile truncates past about 12 characters, so its label is a
		# short form of the app title rather than the title itself.
		tile_title = hooks.add_to_apps_screen[0]["title"]
		self.assertLessEqual(len(tile_title), 12)
		self.assertIn(tile_title, APP_TITLE)
		self.assertEqual(APP_ROUTE, hooks.add_to_apps_screen[0]["route"])

		# Each app's CI checks out only its own dependency chain, so assert the
		# invariant for the sibling apps that are actually present on this bench.
		bench_apps = Path(frappe.get_app_path(APP_NAME)).parents[1]
		for app in sorted(LOCALISATION_APPS - {"za_local", APP_NAME}):
			hooks_path = bench_apps / app / app / "hooks.py"
			if not hooks_path.exists():
				continue
			self.assertNotIn("add_to_apps_screen", hooks_path.read_text(encoding="utf-8"))

	def test_every_workspace_is_attributed_to_an_app_that_ships_it(self):
		"""A workspace attributed to a retired app disappears from the Desk.

		``get_available_workspaces`` filters on ``spec.app in installed_apps`` and
		``_cleanup_stale_navigation`` then deletes the desktop icon of anything it
		excluded. Naming an app that no longer exists therefore silently
		removes a workspace from navigation while leaving the Workspace record intact.
		"""
		bench_apps = Path(frappe.get_app_path(APP_NAME)).resolve().parents[1]
		for spec in WORKSPACE_SPECS:
			# A retired or misspelt app name must fail even on a bench that does not
			# carry it, so check the name against the suite before touching the disk.
			self.assertIn(
				spec.app, CURRENT_SUITE_APPS, f"{spec.label} names an app outside the suite: {spec.app}"
			)
			modules = bench_apps / spec.app / spec.app / "modules.txt"
			if not modules.is_file():
				# Each app's CI clones only its own dependency chain, so a sibling is
				# legitimately absent here. Its own CI asserts the rest.
				continue
			owning_module = frappe.db.get_value("Workspace", spec.label, "module")
			if owning_module:
				self.assertIn(
					owning_module,
					modules.read_text(encoding="utf-8").split("\n"),
					f"{spec.label} is attributed to {spec.app}, which does not declare {owning_module}",
				)

	def test_legacy_domain_icons_are_packaged_by_core(self):
		public = Path(frappe.get_app_path(APP_NAME, "public"))
		for spec in WORKSPACE_SPECS:
			filename = f"{frappe.scrub(spec.label)}.svg"
			self.assertTrue((public / "desktop_icons" / filename).is_file())
			solid = public / "icons" / "desktop_icons" / "solid" / filename
			subtle = public / "icons" / "desktop_icons" / "subtle" / filename
			self.assertTrue(solid.is_file())
			self.assertEqual(solid.read_bytes(), subtle.read_bytes())


class TestSharedNavigationSync(IntegrationTestCase):
	def test_installed_domains_share_one_app_icon_and_switcher(self):
		sync_shared_navigation()
		available = get_available_workspaces()
		labels = [spec.label for spec in available]

		app_icons = frappe.get_all(
			"Desktop Icon",
			filters={"icon_type": "App", "app": ["in", sorted(LOCALISATION_APPS)]},
			fields=["label", "app", "link", "logo_url"],
		)
		self.assertEqual(1, len(app_icons))
		self.assertEqual(APP_TITLE, app_icons[0].label)
		self.assertEqual(APP_NAME, app_icons[0].app)
		self.assertEqual(APP_ROUTE, app_icons[0].link)

		children = frappe.get_all(
			"Desktop Icon",
			filters={"parent_icon": APP_TITLE},
			fields=["label", "app", "link_type", "link_to", "hidden", "logo_url"],
			order_by="idx asc",
		)
		self.assertEqual(labels, [child.label for child in children])
		for child, spec in zip(children, available, strict=True):
			self.assertEqual(APP_NAME, child.app)
			self.assertEqual("Workspace Sidebar", child.link_type)
			self.assertEqual(child.label, child.link_to)
			self.assertEqual(0, child.hidden)
			self.assertEqual(spec.logo_url, child.logo_url)

		if frappe.db.table_exists("Workspace Sidebar"):
			# The archive Frappe's sidebar migration reads. Writing to it recreates the
			# "(Custom)" modules and the one-entry Dock layer the repair patch removes.
			self.assertEqual(
				[],
				frappe.get_all(
					"Workspace Sidebar", filters={"name": ["in", labels], "standard": 0}, pluck="name"
				),
			)

		for stale_label in (
			"SA Compliance",
			"SA Localisation Core",
			"SA Localisation Finance",
			"SA Localisation Payroll",
			"SA Localisation Workplace",
		):
			self.assertFalse(frappe.db.exists("Desktop Icon", stale_label))


class TestWorkspaceOnboarding(IntegrationTestCase):
	"""A module offers the onboarding whose ``module`` matches it.

	v16.50+ computes this per user in ``get_permitted_onboardings``; it replaced the
	``Sidebar.module_onboarding`` pointer.
	"""

	def test_every_installed_workspace_offers_its_onboarding(self):
		sync_shared_navigation()
		for spec in get_available_workspaces():
			self.assertTrue(spec.onboarding, f"{spec.label} declares no onboarding")
			self.assertTrue(
				frappe.db.exists("Module Onboarding", spec.onboarding),
				f"{spec.label} names a Module Onboarding that is not installed: {spec.onboarding}",
			)
			module = frappe.db.get_value("Workspace", spec.label, "module")
			self.assertEqual(
				module,
				frappe.db.get_value("Module Onboarding", spec.onboarding, "module"),
				f"{spec.onboarding} is not in the module of {spec.label}",
			)

	def test_onboarding_steps_use_the_canonical_desk_route(self):
		"""v16 redirects /app/* to /desk/*, so a shipped /app/ path costs a round trip."""
		modules = [spec.onboarding for spec in get_available_workspaces()]
		steps = frappe.get_all("Onboarding Step Map", filters={"parent": ("in", modules)}, pluck="step")
		self.assertTrue(steps)
		for step in steps:
			path = frappe.db.get_value("Onboarding Step", step, "path") or ""
			self.assertFalse(path.startswith("/app/"), f"{step} uses the legacy /app/ route")

	def test_every_shipped_step_explains_itself(self):
		"""A checklist of bare titles is a list, not guidance."""
		modules = [spec.onboarding for spec in get_available_workspaces()]
		steps = frappe.get_all("Onboarding Step Map", filters={"parent": ("in", modules)}, pluck="step")
		undescribed = [
			step
			for step in steps
			if not (frappe.db.get_value("Onboarding Step", step, "description") or "").strip()
		]
		self.assertEqual([], undescribed)


class TestShippedSidebars(UnitTestCase):
	"""The Sidebar files are what the module-first desk renders."""

	def _sidebars(self):
		import json

		root = Path(frappe.get_app_path(APP_NAME))
		return [
			json.loads(path.read_text(encoding="utf-8")) for path in sorted(root.glob("*/sidebar/*/*.json"))
		]

	def test_rows_open_in_the_current_tab(self):
		for sidebar in self._sidebars():
			for row in sidebar["items"]:
				self.assertFalse(
					row.get("open_in_new_tab"), f"{sidebar['title']}: '{row['label']}' opens in a new tab"
				)

	def test_every_sidebar_names_its_dock_entry_and_icon(self):
		import json

		dock = json.loads(
			Path(frappe.get_app_path(APP_NAME, "dock", APP_NAME, f"{APP_NAME}.json")).read_text(
				encoding="utf-8"
			)
		)
		titles = {row["link_to"] for row in dock["items"] if row["link_type"] == "Sidebar"}
		for sidebar in self._sidebars():
			self.assertIn(sidebar["title"], titles)
			self.assertTrue(sidebar["header_icon"].endswith("-duotone"))

	def test_every_report_is_reachable_from_its_sidebar(self):
		"""A report nobody links to is only reachable by typing its URL."""
		import json

		root = Path(frappe.get_app_path(APP_NAME))
		for sidebar in self._sidebars():
			linked = {row.get("link_to") for row in sidebar["items"]}
			module_dir = frappe.scrub(sidebar["module"])
			for path in (root / module_dir / "report").glob("*/*.json"):
				report = json.loads(path.read_text(encoding="utf-8"))
				if path.stem == path.parent.name:
					self.assertIn(
						report["report_name"], linked, f"{report['report_name']} is not in the sidebar"
					)
