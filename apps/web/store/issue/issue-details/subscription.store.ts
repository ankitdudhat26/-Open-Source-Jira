/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { set } from "lodash-es";
import { action, makeObservable, observable, runInAction } from "mobx";
// services
import type { EIssueServiceType } from "@plane/types";
import { IssueService } from "@/services/issue/issue.service";
// types
import type { IIssueDetail } from "./root.store";
export interface IIssueSubscriptionStoreActions {
  addSubscription: (issueId: string, isSubscribed: boolean | undefined | null) => void;
  fetchSubscriptions: (workspaceSlug: string, projectId: string, issueId: string) => Promise<boolean>;
  createSubscription: (workspaceSlug: string, projectId: string, issueId: string) => Promise<void>;
  removeSubscription: (workspaceSlug: string, projectId: string, issueId: string) => Promise<void>;
  fetchWatchers: (workspaceSlug: string, projectId: string, issueId: string) => Promise<string[]>;
  addWatchers: (workspaceSlug: string, projectId: string, issueId: string, userIds: string[]) => Promise<void>;
  removeWatcher: (workspaceSlug: string, projectId: string, issueId: string, userId: string) => Promise<void>;
}

export interface IIssueSubscriptionStore extends IIssueSubscriptionStoreActions {
  // observables
  subscriptionMap: Record<string, Record<string, boolean>>; // Record defines subscriptionId as key and link as value
  // issueId -> ids of the users watching it (oldest first)
  watcherMap: Record<string, string[]>;
  // helper methods
  getSubscriptionByIssueId: (issueId: string) => boolean | undefined;
  getWatcherIdsByIssueId: (issueId: string) => string[] | undefined;
}

export class IssueSubscriptionStore implements IIssueSubscriptionStore {
  // observables
  subscriptionMap: Record<string, Record<string, boolean>> = {};
  watcherMap: Record<string, string[]> = {};
  // root store
  rootIssueDetail: IIssueDetail;
  // services
  issueService;

  constructor(rootStore: IIssueDetail, serviceType: EIssueServiceType) {
    makeObservable(this, {
      // observables
      subscriptionMap: observable,
      watcherMap: observable,
      // actions
      addSubscription: action.bound,
      fetchSubscriptions: action,
      createSubscription: action,
      removeSubscription: action,
      fetchWatchers: action,
      addWatchers: action,
      removeWatcher: action,
    });
    // root store
    this.rootIssueDetail = rootStore;
    // services
    this.issueService = new IssueService(serviceType);
  }

  // helper methods
  getSubscriptionByIssueId = (issueId: string) => {
    if (!issueId) return undefined;
    const currentUserId = this.rootIssueDetail.rootIssueStore.currentUserId;
    if (!currentUserId) return undefined;
    return this.subscriptionMap[issueId]?.[currentUserId] ?? undefined;
  };

  getWatcherIdsByIssueId = (issueId: string) => (issueId ? this.watcherMap[issueId] : undefined);

  /** Keeps the watcher list in step with the current user's watch state (only when the list is loaded). */
  private setCurrentUserWatching = (issueId: string, isWatching: boolean) => {
    const currentUserId = this.rootIssueDetail.rootIssueStore.currentUserId;
    const watcherIds = this.watcherMap[issueId];
    if (!currentUserId || !watcherIds) return;
    const others = watcherIds.filter((id) => id !== currentUserId);
    set(this.watcherMap, [issueId], isWatching ? [...others, currentUserId] : others);
  };

  addSubscription = (issueId: string, isSubscribed: boolean | undefined | null) => {
    const currentUserId = this.rootIssueDetail.rootIssueStore.currentUserId;
    if (!currentUserId) throw new Error("user id not available");

    runInAction(() => {
      set(this.subscriptionMap, [issueId, currentUserId], isSubscribed ?? false);
    });
  };

  fetchSubscriptions = async (workspaceSlug: string, projectId: string, issueId: string) => {
    const subscription = await this.issueService.getIssueNotificationSubscriptionStatus(
      workspaceSlug,
      projectId,
      issueId
    );
    this.addSubscription(issueId, subscription?.subscribed);
    return subscription?.subscribed;
  };

  createSubscription = async (workspaceSlug: string, projectId: string, issueId: string) => {
    try {
      const currentUserId = this.rootIssueDetail.rootIssueStore.currentUserId;
      if (!currentUserId) throw new Error("user id not available");

      runInAction(() => {
        set(this.subscriptionMap, [issueId, currentUserId], true);
        this.setCurrentUserWatching(issueId, true);
      });

      await this.issueService.subscribeToIssueNotifications(workspaceSlug, projectId, issueId);
    } catch (error) {
      this.fetchSubscriptions(workspaceSlug, projectId, issueId);
      if (this.watcherMap[issueId]) this.fetchWatchers(workspaceSlug, projectId, issueId);
      throw error;
    }
  };

  removeSubscription = async (workspaceSlug: string, projectId: string, issueId: string) => {
    try {
      const currentUserId = this.rootIssueDetail.rootIssueStore.currentUserId;
      if (!currentUserId) throw new Error("user id not available");

      runInAction(() => {
        set(this.subscriptionMap, [issueId, currentUserId], false);
        this.setCurrentUserWatching(issueId, false);
      });

      await this.issueService.unsubscribeFromIssueNotifications(workspaceSlug, projectId, issueId);
    } catch (error) {
      this.fetchSubscriptions(workspaceSlug, projectId, issueId);
      if (this.watcherMap[issueId]) this.fetchWatchers(workspaceSlug, projectId, issueId);
      throw error;
    }
  };

  private setWatchers = (issueId: string, watcherIds: string[]) => {
    runInAction(() => {
      set(this.watcherMap, [issueId], watcherIds);
      const currentUserId = this.rootIssueDetail.rootIssueStore.currentUserId;
      if (currentUserId) set(this.subscriptionMap, [issueId, currentUserId], watcherIds.includes(currentUserId));
    });
  };

  fetchWatchers = async (workspaceSlug: string, projectId: string, issueId: string) => {
    const watchers = await this.issueService.listIssueWatchers(workspaceSlug, projectId, issueId);
    const watcherIds = (watchers ?? []).map((watcher) => watcher.subscriber);
    this.setWatchers(issueId, watcherIds);
    return watcherIds;
  };

  addWatchers = async (workspaceSlug: string, projectId: string, issueId: string, userIds: string[]) => {
    if (userIds.length === 0) return;
    const watchers = await this.issueService.addIssueWatchers(workspaceSlug, projectId, issueId, userIds);
    this.setWatchers(
      issueId,
      (watchers ?? []).map((watcher) => watcher.subscriber)
    );
  };

  removeWatcher = async (workspaceSlug: string, projectId: string, issueId: string, userId: string) => {
    const previous = this.watcherMap[issueId];
    if (previous)
      this.setWatchers(
        issueId,
        previous.filter((id) => id !== userId)
      );
    try {
      await this.issueService.removeIssueWatcher(workspaceSlug, projectId, issueId, userId);
    } catch (error) {
      await this.fetchWatchers(workspaceSlug, projectId, issueId);
      throw error;
    }
  };
}
