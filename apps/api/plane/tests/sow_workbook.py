# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Builds a small SOW workbook in the same layout as the project plan template (one table per sheet)."""

import io

from openpyxl import Workbook

SOW_SHEETS = {
    "Milestones": [
        ["Milestone ID", "Milestone", "Scope / Acceptance Criteria", "Payment %"],
        ["M1", "Advance", "Project kick-off on SOW signature", 0.4],
        ["M2", "Design Signoff", "UI/UX designs approved by client", 0.6],
    ],
    "Deliverables": [
        ["Deliverable ID", "Deliverable", "Description", "Milestone ID", "Milestone"],
        ["D01", "Project Plan & Kick-off Minutes", "Plan, timeline, communication", "M1", "Advance"],
        ["D02", "Graphic Designs", "Customer Web, Admin Panel", "M2", "Design Signoff"],
    ],
    "Resources": [
        ["Resource ID", "Role", "Resource Type", "Responsibilities"],
        ["R01", "UI/UX Designer", "Designer", "Graphic designs"],
        ["R02", "Full Stack Developer 1 (Backend lead)", "Full Stack Dev", "NodeJS APIs"],
    ],
    "Modules": [
        ["Module ID", "Module", "Scope"],
        ["MOD01", "Project Environment Setup", "Architecture, environments"],
        ["MOD02", "Graphic Designing", "UI/UX for all platforms"],
    ],
    "Features": [
        ["Feature ID", "Module ID", "Module", "Feature", "Details (from SOW)", "Milestone ID"],
        ["F01", "MOD01", "Project Environment Setup", "Project Environment Setup", "Dev, staging environments", "M2"],
        ["F02", "MOD02", "Graphic Designing", "Graphic Designing", "UI/UX for Customer Web", "M2"],
    ],
    "Tasks": [
        [
            "Task ID",
            "Feature ID",
            "Feature",
            "Task",
            "Module ID",
            "Task Type",
            "Resource ID",
            "Resource Type",
            "Est. Hours",
            "Milestone ID",
        ],
        ["T001", "F01", "Project Environment Setup", "Requirement walkthrough", "MOD01", "Planning", "R02", "Full Stack Dev", 8, "M1"],
        ["T002", "F01", "Project Environment Setup", "System architecture diagram", "MOD01", "Architecture", "R02", "Full Stack Dev", 16, "M2"],
        ["T003", "F02", "Graphic Designing", "Design discovery & style guide", "MOD02", "Design", "R01", "Designer", 24, "M2"],
    ],
}


def build_sow_workbook(sheets=None):
    """Return the bytes of an .xlsx SOW. Each sheet starts with a title row, like the real template."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in (sheets or SOW_SHEETS).items():
        sheet = workbook.create_sheet(title)
        sheet.append([title])
        sheet.append([])
        for row in rows:
            sheet.append(row)
        sheet.append(["Total"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
