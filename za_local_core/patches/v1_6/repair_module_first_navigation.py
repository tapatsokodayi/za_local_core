"""Retire the Workspace Sidebars this app wrote at runtime, and heal what they caused.

Before the shipped ``Sidebar`` and ``Dock`` records existed, ``sync_shared_navigation``
saved a non-standard ``Workspace Sidebar`` for every localisation workspace on every
migrate. In v16.50+ that doctype is an inert archive that Frappe's sidebar migration reads
as its input: each non-standard row becomes a custom module ``<title> (Custom)`` and a
saved site Dock layer holding only that entry, which hides the shipped rail.

This patch removes the rows the app wrote, then removes the copies the migration made from
them. Only records that trace to this app's shipped Sidebars are touched, so a rail someone
arranged by hand survives.
"""

import re

import frappe

APP = "za_local_core"
RUNTIME_SIDEBARS = ("SA Overview", "SA VAT", "SA Payroll", "SA Labour", "SA COIDA", "SA Compliance")


def execute() -> None:
	_remove_runtime_archive_rows()
	_remove_migration_copies()
	frappe.clear_cache()


def _remove_runtime_archive_rows() -> None:
	if not frappe.db.table_exists("Workspace Sidebar"):
		return
	for name in frappe.get_all(
		"Workspace Sidebar",
		filters={"name": ["in", RUNTIME_SIDEBARS], "standard": 0, "app": ["in", [APP, "za_local_payroll"]]},
		pluck="name",
	):
		frappe.delete_doc("Workspace Sidebar", name, force=True, ignore_permissions=True)


def _remove_migration_copies() -> None:
	shipped = {
		row.title: row.module
		for row in frappe.get_all("Sidebar", filters={"app": APP, "standard": 1}, fields=["title", "module"])
	}
	generated = {}
	for module in frappe.get_all("Module Def", filters={"custom": 1}, pluck="name"):
		match = re.fullmatch(r"(.+) \(Custom\)(?: \d+)?", module)
		if match and match.group(1) in shipped:
			generated[module] = shipped[match.group(1)]
	if not generated:
		return

	_drop_generated_site_dock(set(generated))
	for module, home in generated.items():
		for workspace in frappe.get_all("Workspace", filters={"module": module}, fields=["name", "standard"]):
			if workspace.name == module and not workspace.standard:
				frappe.delete_doc("Workspace", workspace.name, force=True, ignore_permissions=True)
				continue
			frappe.db.set_value("Workspace", workspace.name, "module", home, update_modified=False)
		frappe.db.delete("Block Module", {"module": module})
		for sidebar in frappe.get_all("Sidebar", filters={"module": module, "standard": 0}, pluck="name"):
			frappe.delete_doc("Sidebar", sidebar, force=True, ignore_permissions=True, ignore_on_trash=True)
		frappe.delete_doc("Module Def", module, force=True, ignore_permissions=True, ignore_on_trash=True)


def _drop_generated_site_dock(generated: set[str]) -> None:
	for dock in frappe.get_all(
		"Dock", filters={"app": APP, "standard": 0, "user": ["in", ["", None]]}, pluck="name"
	):
		rows = frappe.get_all(
			"Dock Item", filters={"parent": dock, "parenttype": "Dock"}, fields=["link_type", "link_to"]
		)
		targets = {row.link_to for row in rows if row.link_type == "Sidebar"}
		if targets and targets <= generated and len(targets) == len(rows):
			frappe.delete_doc("Dock", dock, force=True, ignore_permissions=True)
