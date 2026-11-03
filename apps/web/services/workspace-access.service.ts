/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

export type TAccessAction = "view" | "create" | "edit" | "delete";
export type TAccessRole = "sub_admin" | "member" | "client";

/** {feature: {action: true (allowed) | false (denied)}} — only the cells an admin set */
export type TAccessCells = Record<string, Partial<Record<TAccessAction, boolean>>>;

export type TAccessFeature = {
  key: string;
  label: string;
  description: string;
  scope: "project" | "workspace";
  actions: TAccessAction[];
};

/** Everything Settings → Roles & access shows */
export type TWorkspaceAccess = {
  features: TAccessFeature[];
  roles: { key: TAccessRole; label: string }[];
  /** the built-in rules of each role */
  defaults: Record<TAccessRole, Record<string, Record<TAccessAction, boolean>>>;
  /** where admins changed them */
  rules: Partial<Record<TAccessRole, TAccessCells>>;
  custom_count: number;
};

/** A person's custom access and what they end up with */
export type TPersonAccess = {
  id: string;
  member_id: string;
  display_name: string;
  full_name: string;
  email: string;
  role: TAccessRole | "admin";
  custom_access: TAccessCells;
  access: Record<string, Record<TAccessAction, { allowed: boolean; set: boolean }>>;
};

/** What the settings set for the current user */
export type TMyAccess = {
  is_admin: boolean;
  is_sub_admin: boolean;
  rules: Partial<Record<TAccessRole, TAccessCells>>;
  custom_access: TAccessCells;
};

const unwrap = <T>(promise: Promise<{ data: T }>): Promise<T> =>
  promise
    .then((response) => response?.data)
    .catch((error) => {
      throw error?.response?.data;
    });

export class WorkspaceAccessService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private url(workspaceSlug: string) {
    return `/api/workspaces/${workspaceSlug}/access/`;
  }

  fetch(workspaceSlug: string): Promise<TWorkspaceAccess> {
    return unwrap(this.get(this.url(workspaceSlug)));
  }

  setRoleAccess(
    workspaceSlug: string,
    data: { role: TAccessRole; feature: string; action: TAccessAction; allowed: boolean }
  ): Promise<{ rules: TWorkspaceAccess["rules"] }> {
    return unwrap(this.patch(this.url(workspaceSlug), data));
  }

  resetRole(workspaceSlug: string, role: TAccessRole): Promise<{ rules: TWorkspaceAccess["rules"] }> {
    return unwrap(this.delete(`${this.url(workspaceSlug)}?role=${role}`));
  }

  fetchPeople(workspaceSlug: string): Promise<TPersonAccess[]> {
    return unwrap(this.get(`${this.url(workspaceSlug)}people/`));
  }

  fetchPerson(workspaceSlug: string, memberId: string): Promise<TPersonAccess> {
    return unwrap(this.get(`${this.url(workspaceSlug)}people/${memberId}/`));
  }

  setPersonAccess(
    workspaceSlug: string,
    memberId: string,
    data: { feature: string; action: TAccessAction; value: "allow" | "deny" | "default" }
  ): Promise<TPersonAccess> {
    return unwrap(this.patch(`${this.url(workspaceSlug)}people/${memberId}/`, data));
  }

  resetPerson(workspaceSlug: string, memberId: string): Promise<TPersonAccess> {
    return unwrap(this.delete(`${this.url(workspaceSlug)}people/${memberId}/`));
  }

  fetchMine(workspaceSlug: string): Promise<TMyAccess> {
    return unwrap(this.get(`${this.url(workspaceSlug)}me/`));
  }
}

export const workspaceAccessService = new WorkspaceAccessService();
