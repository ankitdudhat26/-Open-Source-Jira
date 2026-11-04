/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
// plane imports
import { EUserPermissions } from "@plane/constants";
import type { IWorkspaceMember, TProjectMembership } from "@plane/types";
import { renderFormattedDate } from "@plane/utils";
// components
import { MemberHeaderColumn } from "@/components/project/member-header-column";
import {
  AccountTypeColumn,
  NameColumn,
  ProjectRoleColumn,
  RemoveMemberColumn,
} from "@/components/project/settings/member-columns";
// hooks
import { useMember } from "@/hooks/store/use-member";
import { useUserPermissions } from "@/hooks/store/user";
import { useProjectAccess } from "@/hooks/use-feature-access";
import type { IMemberFilters } from "@/store/member/utils";

export interface RowData extends Pick<TProjectMembership, "original_role" | "designation"> {
  member: IWorkspaceMember;
}

type TUseProjectColumnsProps = {
  projectId: string;
  workspaceSlug: string;
};

export const useProjectColumns = (props: TUseProjectColumnsProps) => {
  const { projectId, workspaceSlug } = props;
  // states
  const [removeMemberModal, setRemoveMemberModal] = useState<RowData | null>(null);

  // store hooks
  const { getProjectRoleByWorkspaceSlugAndProjectId } = useUserPermissions();
  const {
    project: {
      filters: { getFilters, updateFilters },
    },
  } = useMember();
  // derived values
  // Settings → Roles & access: Project members → Edit / Delete, the same in every project
  const { canChangeMembers, canRemoveMembers } = useProjectAccess(workspaceSlug.toString(), projectId.toString());
  const currentProjectRole =
    getProjectRoleByWorkspaceSlugAndProjectId(workspaceSlug.toString(), projectId.toString()) ?? EUserPermissions.GUEST;

  const displayFilters = getFilters(projectId);

  // handlers
  const handleDisplayFilterUpdate = (filters: Partial<IMemberFilters>) => {
    updateFilters(projectId, filters);
  };

  const columns = [
    {
      key: "Full Name",
      content: "Full name",
      thClassName: "text-left",
      thRender: () => (
        <MemberHeaderColumn
          property="full_name"
          displayFilters={displayFilters}
          handleDisplayFilterUpdate={handleDisplayFilterUpdate}
        />
      ),
      tdRender: (rowData: RowData) => <NameColumn rowData={rowData} workspaceSlug={workspaceSlug} />,
    },
    {
      key: "Display Name",
      content: "Display name",
      thRender: () => (
        <MemberHeaderColumn
          property="display_name"
          displayFilters={displayFilters}
          handleDisplayFilterUpdate={handleDisplayFilterUpdate}
        />
      ),
      tdRender: (rowData: RowData) => <div className="w-32">{rowData.member.display_name}</div>,
    },
    {
      key: "Email",
      content: "Email",
      thRender: () => (
        <MemberHeaderColumn
          property="email"
          displayFilters={displayFilters}
          handleDisplayFilterUpdate={handleDisplayFilterUpdate}
        />
      ),
      tdRender: (rowData: RowData) => <div className="w-48 text-secondary">{rowData.member.email}</div>,
    },
    {
      key: "Project Role",
      content: "Project role",
      thRender: () => <span className="text-left">Project role</span>,
      tdRender: (rowData: RowData) => (
        <ProjectRoleColumn
          rowData={rowData}
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          isEditable={canChangeMembers}
        />
      ),
    },
    {
      key: "Account Type",
      content: "Access",
      thRender: () => (
        <MemberHeaderColumn
          property="role"
          displayFilters={displayFilters}
          handleDisplayFilterUpdate={handleDisplayFilterUpdate}
        />
      ),
      tdRender: (rowData: RowData) => (
        <AccountTypeColumn
          rowData={rowData}
          currentProjectRole={currentProjectRole}
          canChangeMembers={canChangeMembers}
          projectId={projectId}
          workspaceSlug={workspaceSlug}
        />
      ),
    },
    {
      key: "Joining Date",
      content: "Joining date",
      thRender: () => (
        <MemberHeaderColumn
          property="joining_date"
          displayFilters={displayFilters}
          handleDisplayFilterUpdate={handleDisplayFilterUpdate}
        />
      ),
      tdRender: (rowData: RowData) => <div>{renderFormattedDate(rowData?.member?.joining_date)}</div>,
    },
    {
      // Remove / Leave, at the far right of each row
      key: "Remove",
      content: "",
      // stays in view when the table is wider than the page
      pinned: "end" as const,
      thRender: () => <span className="sr-only">Remove</span>,
      tdRender: (rowData: RowData) => (
        <RemoveMemberColumn
          rowData={rowData}
          canRemoveMembers={canRemoveMembers}
          currentProjectRole={currentProjectRole}
          setRemoveMemberModal={setRemoveMemberModal}
        />
      ),
    },
  ];
  return {
    columns,
    removeMemberModal,
    setRemoveMemberModal,
    displayFilters,
    handleDisplayFilterUpdate,
  };
};
