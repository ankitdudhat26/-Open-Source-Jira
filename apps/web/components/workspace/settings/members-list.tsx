/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "next/navigation";
import useSWR from "swr";
// plane imports
import { Collapsible } from "@makeplane/propel/components/collapsible";
import { Pagination } from "@makeplane/propel/components/pagination";
import { useTranslation } from "@plane/i18n";
// components
import { CountChip } from "@/components/common/count-chip";
import { MembersSettingsLoader } from "@/components/ui/loader/settings/members";
// hooks
import { useMember } from "@/hooks/store/use-member";
// local imports
import { WorkspaceInvitationsListItem } from "./invitations-list-item";
import { WorkspaceMembersListItem } from "./members-list-item";

const PAGE_SIZES = [25, 50, 100];

export const WorkspaceMembersList = observer(function WorkspaceMembersList(props: {
  searchQuery: string;
  isAdmin: boolean;
}) {
  const { searchQuery, isAdmin } = props;
  const [showPendingInvites, setShowPendingInvites] = useState<boolean>(true);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  // a new search starts from the first page
  useEffect(() => setPage(1), [searchQuery]);

  // router
  const { workspaceSlug } = useParams();
  // store hooks
  const {
    workspace: {
      fetchWorkspaceMembers,
      fetchWorkspaceMemberInvitations,
      workspaceMemberIds,
      getFilteredWorkspaceMemberIds,
      getSearchedWorkspaceMemberIds,
      workspaceMemberInvitationIds,
      getSearchedWorkspaceInvitationIds,
      getWorkspaceMemberDetails,
    },
  } = useMember();
  const { t } = useTranslation();
  // fetching workspace invitations
  useSWR(
    workspaceSlug ? `WORKSPACE_MEMBERS_AND_MEMBER_INVITATIONS_${workspaceSlug.toString()}` : null,
    workspaceSlug
      ? async () => {
          await fetchWorkspaceMemberInvitations(workspaceSlug.toString());
          await fetchWorkspaceMembers(workspaceSlug.toString());
        }
      : null
  );

  if (!workspaceMemberIds && !workspaceMemberInvitationIds) return <MembersSettingsLoader />;

  // derived values
  const filteredMemberIds = workspaceSlug ? getFilteredWorkspaceMemberIds(workspaceSlug.toString()) : [];
  const searchedMemberIds = searchQuery ? getSearchedWorkspaceMemberIds(searchQuery) : filteredMemberIds;
  const searchedInvitationsIds = getSearchedWorkspaceInvitationIds(searchQuery);
  // active members first, each group in its own order
  const allMemberDetails = searchedMemberIds?.map((memberId) => getWorkspaceMemberDetails(memberId));
  const memberDetails = allMemberDetails && [
    ...allMemberDetails.filter((member) => member?.is_active),
    ...allMemberDetails.filter((member) => !member?.is_active),
  ];
  const memberCount = memberDetails?.length ?? 0;
  const pageCount = Math.max(1, Math.ceil(memberCount / pageSize));
  // a filter can leave fewer pages than the one open
  const currentPage = Math.min(page, pageCount);
  const pageStart = (currentPage - 1) * pageSize;
  const pageMembers = memberDetails?.slice(pageStart, pageStart + pageSize);

  return (
    <>
      <div className="divide-y-[0.5px] divide-subtle overflow-scroll">
        {searchedMemberIds?.length !== 0 && <WorkspaceMembersListItem memberDetails={pageMembers ?? []} />}
        {searchedInvitationsIds?.length === 0 && searchedMemberIds?.length === 0 && (
          <h4 className="mt-16 text-center text-body-xs-regular text-placeholder">{t("no_matching_members")}</h4>
        )}
      </div>
      {memberCount > PAGE_SIZES[0] && (
        <div className="flex justify-end pt-3">
          <Pagination
            page={currentPage}
            pageCount={pageCount}
            onPageChange={setPage}
            pageSize={{
              value: pageSize,
              options: PAGE_SIZES,
              onValueChange: (size) => {
                setPageSize(size);
                setPage(1);
              },
            }}
            range={{ current: `${pageStart + 1}-${Math.min(pageStart + pageSize, memberCount)}`, total: memberCount }}
          />
        </div>
      )}
      {isAdmin && searchedInvitationsIds && searchedInvitationsIds.length > 0 && (
        <div className="pt-4">
          <Collapsible
            open={showPendingInvites}
            onOpenChange={setShowPendingInvites}
            trigger={
              <span className="inline-flex items-center gap-2 py-2">
                <span className="text-h5-medium">{t("workspace_settings.settings.members.pending_invites")}</span>
                {searchedInvitationsIds && <CountChip count={searchedInvitationsIds.length} className="h-5" />}
              </span>
            }
          >
            <div className="ml-auto items-center gap-1.5 rounded-md bg-surface-1 py-1.5">
              {searchedInvitationsIds?.map((invitationId) => (
                <WorkspaceInvitationsListItem key={invitationId} invitationId={invitationId} />
              ))}
            </div>
          </Collapsible>
        </div>
      )}
    </>
  );
});
