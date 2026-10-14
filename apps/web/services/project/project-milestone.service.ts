/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { API_BASE_URL } from "@plane/constants";
import type {
  TDeliverable,
  TIssue,
  TDeliverablePayload,
  TMilestone,
  TMilestonePayload,
  TProjectResource,
  TProjectResourcePayload,
  TSOWImportResponse,
  TWorkItemType,
} from "@plane/types";
// services
import { APIService } from "@/services/api.service";

export class ProjectMilestoneService extends APIService {
  constructor() {
    super(API_BASE_URL);
  }

  private projectUrl(workspaceSlug: string, projectId: string) {
    return `/api/workspaces/${workspaceSlug}/projects/${projectId}`;
  }

  async getMilestones(workspaceSlug: string, projectId: string): Promise<TMilestone[]> {
    return this.get(`${this.projectUrl(workspaceSlug, projectId)}/milestones/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async createMilestone(workspaceSlug: string, projectId: string, data: TMilestonePayload): Promise<TMilestone> {
    return this.post(`${this.projectUrl(workspaceSlug, projectId)}/milestones/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async updateMilestone(
    workspaceSlug: string,
    projectId: string,
    milestoneId: string,
    data: TMilestonePayload
  ): Promise<TMilestone> {
    return this.patch(`${this.projectUrl(workspaceSlug, projectId)}/milestones/${milestoneId}/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async deleteMilestone(workspaceSlug: string, projectId: string, milestoneId: string): Promise<void> {
    return this.delete(`${this.projectUrl(workspaceSlug, projectId)}/milestones/${milestoneId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getDeliverables(workspaceSlug: string, projectId: string): Promise<TDeliverable[]> {
    return this.get(`${this.projectUrl(workspaceSlug, projectId)}/deliverables/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async createDeliverable(workspaceSlug: string, projectId: string, data: TDeliverablePayload): Promise<TDeliverable> {
    return this.post(`${this.projectUrl(workspaceSlug, projectId)}/deliverables/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async updateDeliverable(
    workspaceSlug: string,
    projectId: string,
    deliverableId: string,
    data: TDeliverablePayload
  ): Promise<TDeliverable> {
    return this.patch(`${this.projectUrl(workspaceSlug, projectId)}/deliverables/${deliverableId}/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async deleteDeliverable(workspaceSlug: string, projectId: string, deliverableId: string): Promise<void> {
    return this.delete(`${this.projectUrl(workspaceSlug, projectId)}/deliverables/${deliverableId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /** Every work item of the project (for the hierarchy view). */
  async getWorkItemTree(workspaceSlug: string, projectId: string): Promise<TIssue[]> {
    return this.get(`${this.projectUrl(workspaceSlug, projectId)}/work-item-tree/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getWorkItemTypes(workspaceSlug: string, projectId: string): Promise<TWorkItemType[]> {
    return this.get(`${this.projectUrl(workspaceSlug, projectId)}/work-item-types/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async getResources(workspaceSlug: string, projectId: string): Promise<TProjectResource[]> {
    return this.get(`${this.projectUrl(workspaceSlug, projectId)}/resources/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async createResource(
    workspaceSlug: string,
    projectId: string,
    data: TProjectResourcePayload
  ): Promise<TProjectResource> {
    return this.post(`${this.projectUrl(workspaceSlug, projectId)}/resources/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async updateResource(
    workspaceSlug: string,
    projectId: string,
    resourceId: string,
    data: TProjectResourcePayload
  ): Promise<TProjectResource> {
    return this.patch(`${this.projectUrl(workspaceSlug, projectId)}/resources/${resourceId}/`, data)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  async deleteResource(workspaceSlug: string, projectId: string, resourceId: string): Promise<void> {
    return this.delete(`${this.projectUrl(workspaceSlug, projectId)}/resources/${resourceId}/`)
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }

  /**
   * Uploads a SOW (.xlsx / .pdf). With dryRun the server only parses and validates it.
   * resourceMembers maps SOW resource IDs (e.g. "R03") to the project member who fills the role.
   */
  async importSOW(
    workspaceSlug: string,
    projectId: string,
    file: File,
    dryRun: boolean,
    resourceMembers: Record<string, string> = {}
  ): Promise<TSOWImportResponse> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("dry_run", String(dryRun));
    formData.append("resource_members", JSON.stringify(resourceMembers));
    return this.post(`${this.projectUrl(workspaceSlug, projectId)}/sow-import/`, formData, {
      headers: { "Content-Type": "multipart/form-data" },
    })
      .then((response) => response?.data)
      .catch((error) => {
        throw error?.response?.data;
      });
  }
}
