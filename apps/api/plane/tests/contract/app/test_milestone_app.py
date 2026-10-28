# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import uuid
from decimal import Decimal
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from plane.db.models import (
    Deliverable,
    Issue,
    IssueAssignee,
    IssueLabel,
    IssueView,
    Milestone,
    MilestoneModule,
    Module,
    ModuleIssue,
    Project,
    ProjectMember,
    ProjectResource,
    State,
    User,
    WorkspaceMember,
)
from plane.tests.sow_workbook import build_sow_workbook
from plane.utils.sow_descriptions import fill_sow_descriptions


def _create_project(session_client, workspace, **extra):
    response = session_client.post(
        f"/api/workspaces/{workspace.slug}/projects/",
        {"name": "Dale3 Jo3ak", "identifier": "DJ", **extra},
        format="json",
    )
    assert response.status_code == status.HTTP_201_CREATED, response.data
    return Project.objects.get(pk=response.data["id"])


def _url(workspace, project, path):
    return f"/api/workspaces/{workspace.slug}/projects/{project.id}/{path}"


def _sow_file():
    return SimpleUploadedFile(
        "plan.xlsx",
        build_sow_workbook(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@pytest.mark.contract
class TestProjectCreateWithMilestones:
    @pytest.mark.django_db
    def test_create_saves_project_type_milestones_and_deliverables(self, session_client, workspace):
        project = _create_project(
            session_client,
            workspace,
            empro_id="EMP-42",
            project_type="fixed_cost",
            milestones=[{"name": "Advance", "amount": "1000.00"}, {"name": "Design Signoff", "amount": 750}],
            deliverables=["Project Plan", "  ", "Graphic Designs"],
        )

        assert project.empro_id == "EMP-42"
        assert project.project_type == "fixed_cost"
        assert list(Milestone.objects.filter(project=project).values_list("name", "amount")) == [
            ("Advance", Decimal("1000.00")),
            ("Design Signoff", Decimal("750.00")),
        ]
        assert list(Deliverable.objects.filter(project=project).values_list("name", flat=True)) == [
            "Project Plan",
            "Graphic Designs",
        ]

    @pytest.mark.django_db
    def test_create_rejects_invalid_project_type(self, session_client, workspace):
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/",
            {"name": "Bad type", "identifier": "BAD", "project_type": "hourly"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_create_rejects_milestone_without_name(self, session_client, workspace):
        response = session_client.post(
            f"/api/workspaces/{workspace.slug}/projects/",
            {"name": "No name", "identifier": "NON", "milestones": [{"amount": 10}]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Project.objects.filter(name="No name").exists()


@pytest.mark.contract
class TestMilestoneEndpoints:
    @pytest.mark.django_db
    def test_milestone_crud_with_modules_and_progress(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        module = Module.objects.create(name="Admin Panel", project=project)
        done_state = State.objects.get(project=project, group="completed")
        Issue.objects.create(name="Done", project=project, state=done_state)
        open_issue = Issue.objects.create(name="Open", project=project)
        for issue in Issue.objects.filter(project=project):
            ModuleIssue.objects.create(issue=issue, module=module, project=project)

        response = session_client.post(
            _url(workspace, project, "milestones/"),
            {"name": "50% Complete", "amount": "2500", "module_ids": [str(module.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        milestone = response.data
        assert milestone["module_ids"] == [str(module.id)]
        assert milestone["total_issues"] == 2
        assert milestone["completed_issues"] == 1
        assert milestone["is_completed"] is False

        open_issue.state = done_state
        open_issue.save()
        response = session_client.get(_url(workspace, project, f"milestones/{milestone['id']}/"))
        assert response.data["is_completed"] is True
        assert response.data["modules"][0]["is_completed"] is True

        response = session_client.patch(
            _url(workspace, project, f"milestones/{milestone['id']}/"), {"module_ids": []}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["module_ids"] == []

        response = session_client.delete(_url(workspace, project, f"milestones/{milestone['id']}/"))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Milestone.objects.filter(project=project).exists()

    @pytest.mark.django_db
    def test_milestone_rejects_module_of_another_project(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        other = Project.objects.create(name="Other", identifier="OTH", workspace=workspace)
        foreign_module = Module.objects.create(name="Foreign", project=other)

        response = session_client.post(
            _url(workspace, project, "milestones/"),
            {"name": "M1", "module_ids": [str(foreign_module.id)]},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_deliverable_crud(self, session_client, workspace):
        project = _create_project(session_client, workspace, milestones=[{"name": "Advance"}])
        milestone = Milestone.objects.get(project=project)

        response = session_client.post(
            _url(workspace, project, "deliverables/"),
            {"name": "Architecture Diagram", "milestone_id": str(milestone.id)},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        deliverable_id = response.data["id"]

        response = session_client.patch(
            _url(workspace, project, f"deliverables/{deliverable_id}/"), {"milestone_id": None}, format="json"
        )
        assert response.data["milestone_id"] is None

        response = session_client.delete(_url(workspace, project, f"deliverables/{deliverable_id}/"))
        assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.contract
class TestSOWImport:
    @pytest.mark.django_db
    def test_dry_run_returns_summary_without_writing(self, session_client, workspace):
        project = _create_project(session_client, workspace)

        response = session_client.post(
            _url(workspace, project, "sow-import/"), {"file": _sow_file(), "dry_run": "true"}, format="multipart"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["imported"] is False
        assert response.data["summary"]["counts"]["tasks"] == 3
        assert not Milestone.objects.filter(project=project).exists()

    @pytest.mark.django_db
    def test_import_builds_project_structure(self, session_client, workspace):
        # Manually entered milestone is merged with the SOW milestone of the same name, keeping its amount
        project = _create_project(
            session_client, workspace, milestones=[{"name": "Advance", "amount": "500"}], deliverables=["Graphic Designs"]
        )

        response = session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["imported"] is True

        milestones = {m.code: m for m in Milestone.objects.filter(project=project)}
        assert set(milestones) == {"M1", "M2"}
        assert milestones["M1"].amount == Decimal("500.00")
        assert milestones["M1"].payment_percentage == Decimal("40.00")
        assert Deliverable.objects.filter(project=project).count() == 2

        modules = {m.external_id: m for m in Module.objects.filter(project=project)}
        assert set(modules) == {"MOD01", "MOD02"}
        assert set(
            MilestoneModule.objects.filter(milestone=milestones["M2"]).values_list("module__external_id", flat=True)
        ) == {"MOD01", "MOD02"}

        feature = Issue.objects.get(project=project, external_id="F01")
        task = Issue.objects.get(project=project, external_id="T001")
        assert feature.type.name == "Feature"
        assert task.type.name == "Task"
        assert task.parent_id == feature.id
        assert task.milestone_id == milestones["M1"].id
        assert ModuleIssue.objects.filter(issue=task, module=modules["MOD01"]).exists()
        assert set(IssueLabel.objects.filter(issue=task).values_list("label__name", flat=True)) == {
            "Planning",
            "R02 · Full Stack Developer 1 (Backend lead)",
        }

        # Re-importing updates in place
        response = session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")
        assert response.status_code == status.HTTP_200_OK
        assert Issue.objects.filter(project=project).count() == 5
        assert Milestone.objects.filter(project=project).count() == 2

    @pytest.mark.django_db
    def test_import_rejects_unsupported_file(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        upload = SimpleUploadedFile("plan.txt", b"hello", content_type="text/plain")

        response = session_client.post(_url(workspace, project, "sow-import/"), {"file": upload}, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Unsupported file type" in response.data["error"]


@pytest.mark.contract
class TestWorkItemTypeAndMilestone:
    @pytest.mark.django_db
    def test_bug_is_created_under_a_feature_with_milestone(self, session_client, workspace):
        project = _create_project(session_client, workspace, milestones=[{"name": "Advance"}])
        milestone = Milestone.objects.get(project=project)
        types = {t["key"]: t for t in session_client.get(_url(workspace, project, "work-item-types/")).data}
        assert [key for key in types] == ["feature", "task", "bug"]
        assert types["task"]["is_default"] is True

        feature = session_client.post(
            _url(workspace, project, "issues/"), {"name": "Admin Login", "type_id": types["feature"]["id"]}, format="json"
        ).data
        response = session_client.post(
            _url(workspace, project, "issues/"),
            {
                "name": "Reset link expired",
                "type_id": types["bug"]["id"],
                "parent_id": str(feature["id"]),
                "milestone_id": str(milestone.id),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert str(response.data["type_id"]) == types["bug"]["id"]
        assert str(response.data["parent_id"]) == str(feature["id"])
        assert str(response.data["milestone_id"]) == str(milestone.id)

    @pytest.mark.django_db
    def test_milestone_of_another_project_is_rejected(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        other = _create_project(session_client, workspace, name="Other", identifier="OT", milestones=[{"name": "X"}])

        response = session_client.post(
            _url(workspace, project, "issues/"),
            {"name": "Task", "milestone_id": str(Milestone.objects.get(project=other).id)},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_task_inherits_feature_module_and_milestone(self, session_client, workspace):
        project = _create_project(session_client, workspace, milestones=[{"name": "Advance"}])
        milestone = Milestone.objects.get(project=project)
        module = Module.objects.create(name="Admin Panel", project=project)
        types = {t["key"]: t for t in session_client.get(_url(workspace, project, "work-item-types/")).data}
        feature = session_client.post(
            _url(workspace, project, "issues/"),
            {"name": "Admin Login", "type_id": types["feature"]["id"], "milestone_id": str(milestone.id)},
            format="json",
        ).data
        ModuleIssue.objects.create(issue_id=feature["id"], module=module, project=project)

        response = session_client.post(
            _url(workspace, project, "issues/"),
            {"name": "Login UI", "type_id": types["task"]["id"], "parent_id": str(feature["id"])},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        task = Issue.objects.get(pk=response.data["id"])
        assert task.milestone_id == milestone.id
        assert ModuleIssue.objects.filter(issue=task, module=module).exists()

    @pytest.mark.django_db
    def test_search_can_be_limited_to_features(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        types = {t["key"]: t for t in session_client.get(_url(workspace, project, "work-item-types/")).data}
        for name, key in (("Checkout", "feature"), ("Checkout API", "task")):
            session_client.post(
                _url(workspace, project, "issues/"), {"name": name, "type_id": types[key]["id"]}, format="json"
            )

        response = session_client.get(
            _url(workspace, project, "search-issues/"), {"search": "Checkout", "type_id": types["feature"]["id"]}
        )

        assert response.status_code == status.HTTP_200_OK
        assert [issue["name"] for issue in response.data] == ["Checkout"]


@pytest.mark.contract
class TestProjectResources:
    @pytest.mark.django_db
    def test_import_assigns_tasks_to_mapped_members(self, session_client, workspace, create_user):
        project = _create_project(session_client, workspace)

        response = session_client.post(
            _url(workspace, project, "sow-import/"),
            {"file": _sow_file(), "resource_members": json.dumps({"R02": str(create_user.id)})},
            format="multipart",
        )
        assert response.status_code == status.HTTP_200_OK

        resources = {r["code"]: r for r in session_client.get(_url(workspace, project, "resources/")).data}
        assert set(resources) == {"R01", "R02"}
        assert resources["R02"]["member_id"] == create_user.id
        assert resources["R02"]["task_count"] == 2
        assert resources["R01"]["member_id"] is None
        assert set(
            IssueAssignee.objects.filter(assignee=create_user, issue__project=project).values_list(
                "issue__external_id", flat=True
            )
        ) == {"T001", "T002"}

    @pytest.mark.django_db
    def test_remapping_moves_tasks_to_the_new_member(self, session_client, workspace, create_user):
        project = _create_project(session_client, workspace)
        other = User.objects.create(email="ankit@plane.so", username="ankit")
        WorkspaceMember.objects.create(workspace=workspace, member=other, role=15)
        ProjectMember.objects.create(project=project, member=other, role=15)
        session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")
        resource = ProjectResource.objects.get(project=project, code="R01")

        response = session_client.patch(
            _url(workspace, project, f"resources/{resource.id}/"), {"member_id": str(create_user.id)}, format="json"
        )
        assert response.status_code == status.HTTP_200_OK
        assert IssueAssignee.objects.filter(issue__external_id="T003", assignee=create_user).exists()

        session_client.patch(_url(workspace, project, f"resources/{resource.id}/"), {"member_id": str(other.id)}, format="json")
        assert IssueAssignee.objects.filter(issue__external_id="T003", assignee=other).exists()
        assert not IssueAssignee.objects.filter(issue__external_id="T003", assignee=create_user).exists()

    @pytest.mark.django_db
    def test_only_workspace_members_can_be_mapped(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        outsider = User.objects.create(email="outsider@plane.so", username="outsider")

        response = session_client.post(
            _url(workspace, project, "resources/"),
            {"role": "QA Engineer", "member_id": str(outsider.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.django_db
    def test_manual_resource_gets_a_label(self, session_client, workspace, create_user):
        project = _create_project(session_client, workspace)

        response = session_client.post(
            _url(workspace, project, "resources/"),
            {"role": "Flutter Developer", "resource_type": "Flutter Dev", "member_id": str(create_user.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED
        resource = ProjectResource.objects.get(pk=response.data["id"])
        assert resource.label.name == "Flutter Developer"
        assert resource.label.parent.name == "Resource"


@pytest.mark.contract
class TestWorkItemTypeAndMilestoneFilters:
    @pytest.mark.django_db
    def test_filter_and_group_by_type_and_milestone(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")
        types = {t["key"]: t for t in session_client.get(_url(workspace, project, "work-item-types/")).data}
        m1 = Milestone.objects.get(project=project, code="M1")

        def list_issues(**params):
            response = session_client.get(_url(workspace, project, "issues/"), {"per_page": 100, "cursor": "100:0:0", **params})
            assert response.status_code == status.HTTP_200_OK, response.data
            return response.data

        tasks = list_issues(filters=json.dumps({"and": [{"type_id__in": types["task"]["id"]}]}))
        assert tasks["total_count"] == 3

        in_m1 = list_issues(filters=json.dumps({"and": [{"milestone_id__in": str(m1.id)}]}))
        assert [issue["name"] for issue in in_m1["results"]] == ["Requirement walkthrough"]

        grouped = list_issues(group_by="type_id")
        assert grouped["results"][types["feature"]["id"]]["total_results"] == 2
        assert grouped["results"][types["task"]["id"]]["total_results"] == 3

        grouped = list_issues(group_by="milestone_id")
        assert grouped["results"][str(m1.id)]["total_results"] == 1

    @pytest.mark.django_db
    def test_import_creates_views_by_type_and_milestone(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")
        session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")

        names = list(IssueView.objects.filter(project=project).order_by("sort_order").values_list("name", flat=True))
        assert names == ["Features", "Tasks", "Bugs", "M1 · Advance", "M2 · Design Signoff"]
        project.refresh_from_db()
        assert project.issue_views_view and project.module_view

        view = IssueView.objects.get(project=project, name="Tasks")
        response = session_client.get(
            _url(workspace, project, "issues/"),
            {"per_page": 100, "cursor": "100:0:0", "filters": json.dumps(view.rich_filters)},
        )
        assert response.data["total_count"] == 3


@pytest.mark.contract
class TestSeedProjectMembers:
    @pytest.mark.django_db
    def test_seed_adds_members_and_maps_resources(self, session_client, workspace):
        from django.core.management import call_command

        project = _create_project(session_client, workspace)
        session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")

        call_command("seed_project_members", workspace=workspace.slug, project=str(project.id), map_resources=True)
        call_command("seed_project_members", workspace=workspace.slug, project=project.name)

        seeded = ProjectMember.objects.filter(project=project, member__email__endswith="@example.com", is_active=True)
        assert seeded.count() == 5
        designer = ProjectResource.objects.get(project=project, code="R01")
        assert designer.member.display_name == "Priya Shah"
        assert IssueAssignee.objects.filter(issue__external_id="T003", assignee=designer.member).exists()


@pytest.mark.contract
class TestSOWDescriptions:
    @pytest.mark.django_db
    def test_import_writes_task_and_feature_descriptions(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")

        task = Issue.objects.get(project=project, external_id="T002")
        assert "System architecture diagram for the “Project Environment Setup” feature" in task.description_html
        assert "<strong>Feature scope:</strong> Dev, staging environments</p>" in task.description_html
        assert "<strong>Task type:</strong> Architecture" in task.description_html
        assert "R02 · Full Stack Developer 1 (Backend lead)" in task.description_html
        assert "Done when" in task.description_html

        feature = Issue.objects.get(project=project, external_id="F01")
        assert feature.description_html.startswith("<p>Dev, staging environments</p>")
        assert "Requirement walkthrough" in feature.description_html  # its tasks

        # backfilling again (e.g. after the feature description was enriched) keeps the task's feature scope clean
        task.description_html = "<p></p>"
        task.save()
        fill_sow_descriptions(project)
        task.refresh_from_db()
        assert "<strong>Feature scope:</strong> Dev, staging environments</p>" in task.description_html
        # and leaves the already written feature description as it is
        feature_html = feature.description_html
        assert fill_sow_descriptions(project) == 0
        feature.refresh_from_db()
        assert feature.description_html == feature_html

    @pytest.mark.django_db
    def test_edited_descriptions_are_kept_on_reimport(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")
        task = Issue.objects.get(project=project, external_id="T001")
        task.description_html = "<p>Written by the team</p>"
        task.save()
        feature = Issue.objects.get(project=project, external_id="F01")
        feature.description_html = "<p>Edited feature</p>"
        feature.save()

        session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")

        task.refresh_from_db()
        feature.refresh_from_db()
        assert task.description_html == "<p>Written by the team</p>"
        assert feature.description_html == "<p>Edited feature</p>"


@pytest.mark.contract
class TestWorkItemTree:
    @pytest.mark.django_db
    def test_tree_returns_every_work_item_with_relations(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")

        response = session_client.get(_url(workspace, project, "work-item-tree/"))

        assert response.status_code == status.HTTP_200_OK
        items = {item["name"]: item for item in response.data}
        assert len(items) == 5
        feature = items["Project Environment Setup"]
        task = items["Requirement walkthrough"]
        assert task["parent_id"] == feature["id"]
        assert task["module_ids"] == feature["module_ids"] and len(task["module_ids"]) == 1
        assert task["milestone_id"] is not None and task["type_id"] is not None

    @pytest.mark.django_db
    def test_imported_modules_keep_sow_order(self, session_client, workspace):
        project = _create_project(session_client, workspace)
        session_client.post(_url(workspace, project, "sow-import/"), {"file": _sow_file()}, format="multipart")

        ordered = list(Module.objects.filter(project=project).order_by("sort_order").values_list("external_id", flat=True))
        assert ordered == ["MOD01", "MOD02"]


def _workspace_user(workspace, role=15):
    suffix = uuid.uuid4().hex[:6]
    user = User.objects.create(email=f"dev-{suffix}@example.com", username=f"dev_{suffix}")
    WorkspaceMember.objects.create(workspace=workspace, member=user, role=role)
    return user


@pytest.fixture
def invite_email():
    with mock.patch("plane.utils.project_membership.project_add_user_email.delay") as delay:
        yield delay


@pytest.mark.contract
class TestResourceMemberJoinsProject:
    """The member who fills a resource gets full access to the project and the invite email."""

    @pytest.mark.django_db
    def test_added_resource_brings_the_member_in(self, session_client, workspace, invite_email):
        project = _create_project(session_client, workspace)
        tester = _workspace_user(workspace)

        response = session_client.post(
            _url(workspace, project, "resources/"),
            {"role": "QA Engineer", "resource_type": "QA", "member_id": str(tester.id)},
            format="json",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.data
        member = ProjectMember.objects.get(project=project, member=tester)
        assert (member.role, member.designation, member.is_active) == (15, "QA Engineer", True)
        invite_email.assert_called_once()
        assert invite_email.call_args.args[1] == member.id

    @pytest.mark.django_db
    def test_workspace_admin_joins_as_project_admin(self, session_client, workspace, invite_email):
        project = _create_project(session_client, workspace)
        lead = _workspace_user(workspace, role=20)
        resource = ProjectResource.objects.create(project=project, workspace=workspace, role="Tech Lead")

        response = session_client.patch(
            _url(workspace, project, f"resources/{resource.id}/"), {"member_id": str(lead.id)}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        assert ProjectMember.objects.get(project=project, member=lead).role == 20
        invite_email.assert_called_once()

    @pytest.mark.django_db
    def test_existing_project_member_is_not_invited_again(self, session_client, workspace, invite_email):
        project = _create_project(session_client, workspace)
        developer = _workspace_user(workspace)
        ProjectMember.objects.create(project=project, member=developer, role=15, designation="Developer")

        session_client.post(
            _url(workspace, project, "resources/"), {"role": "Backend", "member_id": str(developer.id)}, format="json"
        )

        invite_email.assert_not_called()
        assert ProjectMember.objects.get(project=project, member=developer).designation == "Developer"

    @pytest.mark.django_db
    def test_workspace_guest_cannot_be_mapped(self, session_client, workspace, invite_email):
        project = _create_project(session_client, workspace)
        client = _workspace_user(workspace, role=5)

        response = session_client.post(
            _url(workspace, project, "resources/"), {"role": "QA", "member_id": str(client.id)}, format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not ProjectMember.objects.filter(project=project, member=client).exists()
        invite_email.assert_not_called()

    @pytest.mark.django_db
    def test_sow_import_brings_mapped_members_in(self, session_client, workspace, invite_email):
        project = _create_project(session_client, workspace)
        developer = _workspace_user(workspace)

        response = session_client.post(
            _url(workspace, project, "sow-import/"),
            {"file": _sow_file(), "resource_members": json.dumps({"R02": str(developer.id)})},
            format="multipart",
        )

        assert response.status_code == status.HTTP_200_OK, response.data
        resource = ProjectResource.objects.get(project=project, code="R02")
        assert resource.member_id == developer.id
        member = ProjectMember.objects.get(project=project, member=developer)
        assert member.designation == resource.role
        invite_email.assert_called_once()
