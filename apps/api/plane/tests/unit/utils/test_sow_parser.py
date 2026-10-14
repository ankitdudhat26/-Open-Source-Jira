# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import copy
from decimal import Decimal

import pytest

from plane.tests.sow_workbook import SOW_SHEETS, build_sow_workbook
from plane.utils.sow_import import build_summary
from plane.utils.sow_parser import SOWParseError, _line_cells, _join_wrapped, parse_sow


@pytest.mark.unit
class TestSOWParserXlsx:
    def test_parses_every_table(self):
        data, errors, warnings = parse_sow("plan.xlsx", build_sow_workbook())

        assert errors == []
        assert warnings == []
        assert [row["id"] for row in data["milestones"]] == ["M1", "M2"]
        assert [row["id"] for row in data["deliverables"]] == ["D01", "D02"]
        assert [row["id"] for row in data["resources"]] == ["R01", "R02"]
        assert [row["id"] for row in data["modules"]] == ["MOD01", "MOD02"]
        assert [row["id"] for row in data["features"]] == ["F01", "F02"]
        assert [row["id"] for row in data["tasks"]] == ["T001", "T002", "T003"]

    def test_maps_columns_by_header(self):
        data, _, _ = parse_sow("plan.xlsx", build_sow_workbook())

        assert data["milestones"][0] == {
            "id": "M1",
            "name": "Advance",
            "scope": "Project kick-off on SOW signature",
            # Excel stores 40% as 0.4
            "payment_percentage": Decimal("40.00"),
            "amount": None,
        }
        task = data["tasks"][1]
        assert task["feature_id"] == "F01"
        assert task["name"] == "System architecture diagram"
        assert task["task_type"] == "Architecture"
        assert task["resource_id"] == "R02"
        # The extra "Est. Hours" column does not shift the Milestone ID column
        assert task["milestone_id"] == "M2"

    def test_reports_unknown_references(self):
        sheets = copy.deepcopy(SOW_SHEETS)
        sheets["Tasks"][1][1] = "F99"
        sheets["Features"][2][5] = "M9"
        sheets["Deliverables"][1][3] = "M7"

        _, errors, _ = parse_sow("plan.xlsx", build_sow_workbook(sheets))

        assert "Task T001 refers to unknown feature F99" in errors
        assert "Feature F02 refers to unknown milestone M9" in errors
        assert "Deliverable D01 refers to unknown milestone M7" in errors

    def test_reports_duplicate_ids_and_module_mismatch(self):
        sheets = copy.deepcopy(SOW_SHEETS)
        sheets["Modules"][2][0] = "MOD01"
        sheets["Tasks"][3][4] = "MOD01"

        _, errors, _ = parse_sow("plan.xlsx", build_sow_workbook(sheets))

        assert "Duplicate module ID MOD01" in errors
        assert any(error.startswith("Task T003 is in module MOD01 but its feature F02") for error in errors)

    def test_warns_when_payment_does_not_total_100(self):
        sheets = copy.deepcopy(SOW_SHEETS)
        sheets["Milestones"][2][3] = 0.5

        _, errors, warnings = parse_sow("plan.xlsx", build_sow_workbook(sheets))

        assert errors == []
        assert "Milestone payment percentages add up to 90.00%, not 100%" in warnings

    def test_missing_table_is_rejected(self):
        sheets = copy.deepcopy(SOW_SHEETS)
        del sheets["Resources"]

        with pytest.raises(SOWParseError, match="resources"):
            parse_sow("plan.xlsx", build_sow_workbook(sheets))

    def test_unsupported_file_type_is_rejected(self):
        with pytest.raises(SOWParseError, match="Unsupported file type"):
            parse_sow("plan.docx", b"")


@pytest.mark.unit
class TestSOWSummary:
    def test_modules_are_linked_to_every_milestone_they_deliver_in(self):
        data, _, _ = parse_sow("plan.xlsx", build_sow_workbook())

        summary = build_summary(data)

        milestones = {row["id"]: row for row in summary["milestones"]}
        # T001 (MOD01) is delivered in M1; F01, F02 and the remaining tasks in M2
        assert [module["id"] for module in milestones["M1"]["modules"]] == ["MOD01"]
        assert [module["id"] for module in milestones["M2"]["modules"]] == ["MOD01", "MOD02"]
        assert milestones["M2"]["deliverables"] == ["D02"]
        assert summary["counts"] == {
            "milestones": 2,
            "deliverables": 2,
            "resources": 2,
            "modules": 2,
            "features": 2,
            "tasks": 3,
        }


@pytest.mark.unit
class TestSOWParserPdfLayout:
    def test_line_cells_split_on_column_gaps(self):
        line = "T006        F01          Project Environment Setup     Third-party sandbox setup (FCM,     MOD01"
        assert [text for _, text in _line_cells(line)] == [
            "T006",
            "F01",
            "Project Environment Setup",
            "Third-party sandbox setup (FCM,",
            "MOD01",
        ]

    def test_wrapped_cell_text_is_joined(self):
        assert _join_wrapped("Order Status Notifications", "(WhatsApp)") == "Order Status Notifications (WhatsApp)"
        assert _join_wrapped("rating, 3-order limit, re-", "assign)") == "rating, 3-order limit, re-assign)"
