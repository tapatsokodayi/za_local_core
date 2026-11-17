"""Shared Frappe Desk navigation for the South African localisation suite.

The module-first desk reads the shipped ``Dock`` and ``Sidebar`` records, so nothing is
built here for it. What remains is the icon grid, which only a site that has switched
Desktop Settings away from "Apps" still shows, and the cleanup of retired icons.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import frappe

APP_NAME = "za_local_core"
APP_TITLE = "SA Localisation"
APP_ROUTE = "/desk/sa-overview"
APP_LOGO = "/assets/za_local_core/images/za_local_core_logo.svg"

# Every app name the suite has ever shipped under, including retired ones. This is
# a cleanup allow-list, not a dependency list: a site that once had a retired app
# installed still carries its Desktop Icon, and only a name listed here is removed.
LOCALISATION_APPS = {
	"za_local",
	"za_local_core",
	"za_local_finance",
	"za_local_payroll",
	"za_local_workplace",
}

STALE_APP_LABELS = {
	"SA Localisation Core",
	"SA Localisation Finance",
	"SA Localisation Payroll",
	"SA Localisation Workplace",
}


@dataclass(frozen=True)
class WorkspaceSpec:
	label: str
	app: str
	icon: str
	asset_name: str
	onboarding: str

	@property
	def logo_url(self) -> str:
		return f"/assets/{APP_NAME}/desktop_icons/{self.asset_name}"


WORKSPACE_SPECS = (
	WorkspaceSpec(
		"SA Overview", "za_local_core", "shield-check", "sa_overview.svg", "SA Localisation Onboarding"
	),
	WorkspaceSpec("SA Payroll", "za_local_payroll", "calculator", "sa_payroll.svg", "SA Payroll Onboarding"),
	WorkspaceSpec("SA VAT", "za_local_core", "receipt", "sa_vat.svg", "SA VAT Onboarding"),
	WorkspaceSpec("SA Labour", "za_local_payroll", "users", "sa_labour.svg", "SA Labour Onboarding"),
	WorkspaceSpec("SA COIDA", "za_local_payroll", "shield-plus", "sa_coida.svg", "SA COIDA Onboarding"),
)


def sync_shared_navigation() -> None:
	"""Expose installed localisation domains through one shared Desk app."""
	if not frappe.db.table_exists("Desktop Icon"):
		return

	available = get_available_workspaces()
	_cleanup_stale_navigation(available)
	_sync_desktop_icons(available)
	_repair_saved_desktop_layouts(available)
	_clear_navigation_cache()


def get_available_workspaces() -> tuple[WorkspaceSpec, ...]:
	"""Return installed domain workspaces in their stable display order."""
	installed_apps = set(frappe.get_installed_apps() or ())
	return tuple(
		spec
		for spec in WORKSPACE_SPECS
		if spec.app in installed_apps and frappe.db.exists("Workspace", spec.label)
	)


def _cleanup_stale_navigation(available: tuple[WorkspaceSpec, ...]) -> None:
	available_labels = {spec.label for spec in available}
	all_workspace_labels = {spec.label for spec in WORKSPACE_SPECS}

	for label in all_workspace_labels - available_labels:
		_delete_exact("Desktop Icon", label)

	for label in STALE_APP_LABELS | {"SA Compliance"}:
		_delete_exact("Desktop Icon", label)

	for icon in frappe.get_all(
		"Desktop Icon",
		filters={"icon_type": "App", "app": ["in", sorted(LOCALISATION_APPS)]},
		fields=["name", "label", "app"],
	):
		if icon.label == APP_TITLE and icon.app == APP_NAME:
			continue
		_delete_exact("Desktop Icon", icon.name)


def _sync_desktop_icons(available: tuple[WorkspaceSpec, ...]) -> None:
	app_icon = _get_or_create_app_icon()
	app_icon.update(
		{
			"label": APP_TITLE,
			"icon_type": "App",
			"link_type": "External",
			"link": APP_ROUTE,
			"logo_url": APP_LOGO,
			"app": APP_NAME,
			"hidden": 0,
			"standard": 0,
		}
	)
	_save_icon(app_icon)

	for index, spec in enumerate(available):
		if frappe.db.exists("Desktop Icon", spec.label):
			icon = frappe.get_doc("Desktop Icon", spec.label)
		else:
			icon = frappe.new_doc("Desktop Icon")
			icon.label = spec.label
		icon.update(
			{
				"icon_type": "Link",
				"link_type": "Workspace Sidebar",
				"link_to": spec.label,
				"link": "",
				"icon": spec.icon,
				"app": APP_NAME,
				"parent_icon": APP_TITLE,
				"hidden": 0,
				"standard": 0,
				"idx": index,
				"logo_url": spec.logo_url,
				"icon_image": "",
			}
		)
		_save_icon(icon)


def _get_or_create_app_icon():
	name = frappe.db.get_value("Desktop Icon", {"icon_type": "App", "app": APP_NAME}, "name")
	if name:
		return frappe.get_doc("Desktop Icon", name)
	if frappe.db.exists("Desktop Icon", APP_TITLE):
		return frappe.get_doc("Desktop Icon", APP_TITLE)
	icon = frappe.new_doc("Desktop Icon")
	icon.label = APP_TITLE
	return icon


def _save_icon(icon) -> None:
	# `link_to` is typed off `link_type`, and the "Workspace Sidebar" doctype it names is an
	# inert archive in v16.50+, so validating the link would refuse every icon.
	if icon.is_new():
		icon.insert(ignore_permissions=True, ignore_links=True)
	else:
		icon.flags.ignore_links = True
		icon.save(ignore_permissions=True)


def _repair_saved_desktop_layouts(available: tuple[WorkspaceSpec, ...]) -> None:
	if not frappe.db.table_exists("Desktop Layout"):
		return

	desired_labels = [APP_TITLE, *(spec.label for spec in available)]
	desired_icons = {
		row.label: dict(row)
		for row in frappe.get_all(
			"Desktop Icon",
			filters={"label": ["in", desired_labels]},
			fields=[
				"name",
				"label",
				"bg_color",
				"link",
				"link_type",
				"app",
				"icon_type",
				"parent_icon",
				"icon",
				"link_to",
				"idx",
				"standard",
				"logo_url",
				"hidden",
				"restrict_removal",
				"icon_image",
			],
		)
	}
	if APP_TITLE not in desired_icons:
		return

	relevant_labels = set(desired_labels) | STALE_APP_LABELS | {"SA Compliance"}
	for saved in frappe.get_all("Desktop Layout", fields=["name", "layout"]):
		try:
			layout = json.loads(saved.layout or "[]")
		except (TypeError, ValueError):
			continue
		if not isinstance(layout, list) or not any(
			isinstance(icon, dict) and icon.get("label") in relevant_labels for icon in layout
		):
			continue

		first_index = next(
			index
			for index, icon in enumerate(layout)
			if isinstance(icon, dict) and icon.get("label") in relevant_labels
		)
		cleaned = [
			icon for icon in layout if not (isinstance(icon, dict) and icon.get("label") in relevant_labels)
		]
		for offset, label in enumerate(desired_labels):
			cleaned.insert(first_index + offset, desired_icons[label])
		frappe.db.set_value(
			"Desktop Layout",
			saved.name,
			"layout",
			json.dumps(cleaned),
			update_modified=False,
		)


def _delete_exact(doctype: str, name: str) -> None:
	if frappe.db.exists(doctype, name):
		frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)


def _clear_navigation_cache() -> None:
	frappe.cache.delete_key("desktop_icons")
	frappe.cache.delete_key("bootinfo")
	frappe.clear_cache()
