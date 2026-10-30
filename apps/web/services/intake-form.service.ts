/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

export type TIntakeFormFieldKey = "title" | "description" | "type" | "priority" | "labels" | "attachments";

export type TIntakeFormField = {
  key: TIntakeFormFieldKey;
  label: string;
  visible: boolean;
  /** always on the form (the title) */
  locked: boolean;
};

/** The request form of a project's Intake: its link (where invited clients log in) and its fields. */
export type TIntakeForm = {
  anchor: string;
  url: string;
  is_enabled: boolean;
  fields: TIntakeFormField[];
};

/** A client invited to the request form. */
export type TIntakeFormInvite = {
  id: string;
  email: string;
  name: string;
  /** they have an account and can log in */
  has_account: boolean;
  request_count: number;
  last_sent_at: string | null;
  created_at: string;
};

const unwrap = <T>(promise: Promise<{ data: T }>): Promise<T> =>
  promise
    .then((response) => response?.data)
    .catch((error) => {
      throw error?.response?.data;
    });

/** The request form of each project's Intake: link, fields and the clients invited to it. */
export class IntakeFormService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private url(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}/intake-form/`;
  }

  fetch(workspaceSlug: string, projectId: string): Promise<TIntakeForm> {
    return unwrap(this.get(this.url(workspaceSlug, projectId)));
  }

  update(
    workspaceSlug: string,
    projectId: string,
    data: { is_enabled?: boolean; fields?: Partial<Record<TIntakeFormFieldKey, { visible: boolean }>> }
  ): Promise<TIntakeForm> {
    return unwrap(this.patch(this.url(workspaceSlug, projectId), data));
  }

  resetLink(workspaceSlug: string, projectId: string): Promise<TIntakeForm> {
    return unwrap(this.post(`${this.url(workspaceSlug, projectId)}reset-link/`));
  }

  fetchInvites(workspaceSlug: string, projectId: string): Promise<TIntakeFormInvite[]> {
    return unwrap(this.get(`${this.url(workspaceSlug, projectId)}invites/`));
  }

  /** Invites the emails (again, for those already invited) — each is emailed the form's link unless `sendEmail` is off. */
  invite(workspaceSlug: string, projectId: string, emails: string[], sendEmail = true): Promise<TIntakeFormInvite[]> {
    return unwrap(this.post(`${this.url(workspaceSlug, projectId)}invites/`, { emails, send_email: sendEmail }));
  }

  removeInvite(workspaceSlug: string, projectId: string, inviteId: string): Promise<void> {
    return unwrap(this.delete(`${this.url(workspaceSlug, projectId)}invites/${inviteId}/`));
  }
}

export const intakeFormService = new IntakeFormService();
