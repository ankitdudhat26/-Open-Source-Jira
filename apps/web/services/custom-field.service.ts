/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
// services
import { APIService } from "@/services/api.service";

export type TCustomFieldType =
  | "text"
  | "textarea"
  | "number"
  | "date"
  | "select"
  | "multi_select"
  | "checkbox"
  | "url"
  | "user";

export type TCustomField = {
  id: string;
  project: string;
  name: string;
  field_type: TCustomFieldType;
  description: string;
  options: string[];
  sort_order: number;
  external_source: string | null;
};

export type TCustomFieldValue = string | number | boolean | string[] | null;

export const CUSTOM_FIELD_TYPE_LABELS: Record<TCustomFieldType, string> = {
  text: "Text",
  textarea: "Paragraph",
  number: "Number",
  date: "Date",
  select: "Dropdown",
  multi_select: "Multi select",
  checkbox: "Checkbox",
  url: "URL",
  user: "People",
};

const unwrap = <T>(promise: Promise<{ data: T }>): Promise<T> =>
  promise
    .then((response) => response?.data)
    .catch((error) => {
      throw error?.response?.data;
    });

export class CustomFieldService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private base(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}`;
  }

  list(workspaceSlug: string, projectId: string): Promise<TCustomField[]> {
    return unwrap(this.get(`${this.base(workspaceSlug, projectId)}/custom-fields/`));
  }

  create(workspaceSlug: string, projectId: string, data: Partial<TCustomField>): Promise<TCustomField> {
    return unwrap(this.post(`${this.base(workspaceSlug, projectId)}/custom-fields/`, data));
  }

  update(
    workspaceSlug: string,
    projectId: string,
    fieldId: string,
    data: Partial<TCustomField>
  ): Promise<TCustomField> {
    return unwrap(this.patch(`${this.base(workspaceSlug, projectId)}/custom-fields/${fieldId}/`, data));
  }

  remove(workspaceSlug: string, projectId: string, fieldId: string): Promise<void> {
    return unwrap(this.delete(`${this.base(workspaceSlug, projectId)}/custom-fields/${fieldId}/`));
  }

  getValues(workspaceSlug: string, projectId: string, issueId: string): Promise<Record<string, TCustomFieldValue>> {
    return unwrap(this.get(`${this.base(workspaceSlug, projectId)}/issues/${issueId}/custom-field-values/`));
  }

  setValue(
    workspaceSlug: string,
    projectId: string,
    issueId: string,
    fieldId: string,
    value: TCustomFieldValue
  ): Promise<{ field_id: string; value: TCustomFieldValue }> {
    return unwrap(
      this.put(`${this.base(workspaceSlug, projectId)}/issues/${issueId}/custom-field-values/`, {
        field_id: fieldId,
        value,
      })
    );
  }
}

export const customFieldService = new CustomFieldService();
