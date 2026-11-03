/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { EUserPermissions, ROLE } from "@plane/constants";

/** A workspace role as people pick it. Sub Admin is a Member (`is_sub_admin`) who can also create projects — with full
 *  access to them — and invite people as Member or Client. */
export type TWorkspaceRoleOption = { key: string; label: string; role: EUserPermissions; isSubAdmin: boolean };

export const WORKSPACE_ROLE_OPTIONS: TWorkspaceRoleOption[] = [
  { key: "client", label: ROLE[EUserPermissions.GUEST], role: EUserPermissions.GUEST, isSubAdmin: false },
  { key: "member", label: ROLE[EUserPermissions.MEMBER], role: EUserPermissions.MEMBER, isSubAdmin: false },
  { key: "sub_admin", label: "Sub Admin", role: EUserPermissions.MEMBER, isSubAdmin: true },
  { key: "admin", label: ROLE[EUserPermissions.ADMIN], role: EUserPermissions.ADMIN, isSubAdmin: false },
];

/** The option for a member's role: Client, Member, Sub Admin or Admin */
export const workspaceRoleOption = (role: EUserPermissions | undefined, isSubAdmin?: boolean) =>
  WORKSPACE_ROLE_OPTIONS.find(
    (option) => option.role === role && option.isSubAdmin === (role === EUserPermissions.MEMBER && !!isSubAdmin)
  );

/** The roles someone may give when inviting: an Admin gives any; a Sub Admin only Member or Client */
export const invitableRoleOptions = (inviterRole: EUserPermissions | undefined, inviterIsSubAdmin?: boolean) => {
  if (inviterRole === EUserPermissions.ADMIN) return WORKSPACE_ROLE_OPTIONS;
  if (inviterRole === EUserPermissions.MEMBER && inviterIsSubAdmin)
    return WORKSPACE_ROLE_OPTIONS.filter((option) => option.role !== EUserPermissions.ADMIN && !option.isSubAdmin);
  return [];
};
