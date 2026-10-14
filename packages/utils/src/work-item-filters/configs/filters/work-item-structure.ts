/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// plane imports
import type { TFilterProperty, TMilestone, TSupportedOperators, TWorkItemType } from "@plane/types";
import { EQUALITY_OPERATOR, COLLECTION_OPERATOR } from "@plane/types";
// local imports
import type { TCreateFilterConfigParams, IFilterIconConfig, TCreateFilterConfig } from "../../../rich-filters";
import { createFilterConfig, getMultiSelectConfig, createOperatorConfigEntry } from "../../../rich-filters";

// ------------ Work item type (Feature / Task / Bug) ------------

export type TCreateWorkItemTypeFilterParams = TCreateFilterConfigParams &
  IFilterIconConfig<TWorkItemType> & {
    workItemTypes: TWorkItemType[];
  };

export const getWorkItemTypeMultiSelectConfig = (
  params: TCreateWorkItemTypeFilterParams,
  singleValueOperator: TSupportedOperators
) =>
  getMultiSelectConfig<TWorkItemType, string, TWorkItemType>(
    {
      items: params.workItemTypes,
      getId: (type) => type.id,
      getLabel: (type) => type.name,
      getValue: (type) => type.id,
      getIconData: (type) => type,
    },
    { singleValueOperator, ...params },
    { ...params }
  );

export const getWorkItemTypeFilterConfig =
  <P extends TFilterProperty>(key: P): TCreateFilterConfig<P, TCreateWorkItemTypeFilterParams> =>
  (params: TCreateWorkItemTypeFilterParams) =>
    createFilterConfig<P>({
      id: key,
      label: "Type",
      ...params,
      icon: params.filterIcon,
      supportedOperatorConfigsMap: new Map([
        createOperatorConfigEntry(COLLECTION_OPERATOR.IN, params, (updatedParams) =>
          getWorkItemTypeMultiSelectConfig(updatedParams, EQUALITY_OPERATOR.EXACT)
        ),
      ]),
    });

// ------------ Milestone ------------

export type TCreateMilestoneFilterParams = TCreateFilterConfigParams &
  IFilterIconConfig<TMilestone> & {
    milestones: TMilestone[];
  };

export const getMilestoneMultiSelectConfig = (
  params: TCreateMilestoneFilterParams,
  singleValueOperator: TSupportedOperators
) =>
  getMultiSelectConfig<TMilestone, string, TMilestone>(
    {
      items: params.milestones,
      getId: (milestone) => milestone.id,
      getLabel: (milestone) => (milestone.code ? `${milestone.code} · ${milestone.name}` : milestone.name),
      getValue: (milestone) => milestone.id,
      getIconData: (milestone) => milestone,
    },
    { singleValueOperator, ...params },
    { ...params }
  );

export const getMilestoneFilterConfig =
  <P extends TFilterProperty>(key: P): TCreateFilterConfig<P, TCreateMilestoneFilterParams> =>
  (params: TCreateMilestoneFilterParams) =>
    createFilterConfig<P>({
      id: key,
      label: "Milestone",
      ...params,
      icon: params.filterIcon,
      supportedOperatorConfigsMap: new Map([
        createOperatorConfigEntry(COLLECTION_OPERATOR.IN, params, (updatedParams) =>
          getMilestoneMultiSelectConfig(updatedParams, EQUALITY_OPERATOR.EXACT)
        ),
      ]),
    });
