/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { Switch } from "@makeplane/propel/components/switch";
import { ArrowNarrowRightOutline, CloseOutline } from "@makeplane/propel/icons";
import { ConfirmDialog } from "@plane/blocks/dialog";
import { setToast } from "@plane/blocks/toast";
import type { IState } from "@plane/types";
// components
import { MemberSelect } from "@/components/dropdowns/member/member-select";
import { StateSelect } from "@/components/dropdowns/state/state-select";
// hooks
import { useProjectState } from "@/hooks/store/use-project-state";
import { projectWorkflowService, useProjectWorkflow } from "@/hooks/use-project-workflow";
import type { TWorkflowTemplate, TWorkflowTransition } from "@/services/project/project-workflow.service";

type Props = {
  workspaceSlug: string;
  projectId: string;
  /** Project admins can change the workflow, members only see it. */
  isEditable: boolean;
};

const errorMessage = (error: unknown, fallback: string) =>
  error && typeof error === "object" && "error" in error && typeof error.error === "string" ? error.error : fallback;

function StateChip({ state }: { state: IState | undefined }) {
  if (!state) return null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-subtle px-2 py-0.5 text-body-xs-medium text-primary">
      <span className="size-2 shrink-0 rounded-full" style={{ backgroundColor: state.color }} />
      {state.name}
    </span>
  );
}

/**
 * Jira style workflow: for every state, the states its work items may move to next and (optionally) who
 * may make that move. A state without rules is not restricted.
 */
export const ProjectWorkflowEditor = observer(function ProjectWorkflowEditor(props: Props) {
  const { workspaceSlug, projectId, isEditable } = props;
  // store hooks
  const { getProjectStates, fetchProjectStates } = useProjectState();
  const { workflow, mutate } = useProjectWorkflow(workspaceSlug, projectId);
  // draft, saved with the "Save workflow" button
  const [isEnabled, setIsEnabled] = useState(false);
  const [transitions, setTransitions] = useState<TWorkflowTransition[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [templateToApply, setTemplateToApply] = useState<TWorkflowTemplate | null>(null);
  const [isApplying, setIsApplying] = useState(false);

  useEffect(() => {
    if (!workflow) return;
    setIsEnabled(workflow.is_enabled);
    setTransitions(
      workflow.transitions.map(({ from_state, to_state, reviewer_ids }) => ({ from_state, to_state, reviewer_ids }))
    );
  }, [workflow]);

  const projectStates = getProjectStates(projectId);
  const states = useMemo(() => projectStates ?? [], [projectStates]);
  const stateMap = useMemo(() => new Map(states.map((state) => [state.id, state])), [states]);

  const isDirty = useMemo(() => {
    if (!workflow) return false;
    const key = (items: TWorkflowTransition[]) => {
      const rows = items.map((item) => {
        // copies are sorted, toSorted needs ES2023
        // oxlint-disable-next-line unicorn/no-array-sort
        const reviewers = [...item.reviewer_ids].sort().join(",");
        return `${item.from_state}>${item.to_state}:${reviewers}`;
      });
      // oxlint-disable-next-line unicorn/no-array-sort
      return JSON.stringify(rows.sort());
    };
    return workflow.is_enabled !== isEnabled || key(workflow.transitions) !== key(transitions);
  }, [workflow, isEnabled, transitions]);

  const addTransition = (fromState: string, toState: string) => {
    if (fromState === toState) return;
    if (transitions.some((item) => item.from_state === fromState && item.to_state === toState)) return;
    setTransitions((items) => [...items, { from_state: fromState, to_state: toState, reviewer_ids: [] }]);
  };

  const updateTransition = (fromState: string, toState: string, update: Partial<TWorkflowTransition> | null) => {
    setTransitions((items) =>
      update === null
        ? items.filter((item) => !(item.from_state === fromState && item.to_state === toState))
        : items.map((item) =>
            item.from_state === fromState && item.to_state === toState ? { ...item, ...update } : item
          )
    );
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const saved = await projectWorkflowService.saveWorkflow(workspaceSlug, projectId, {
        is_enabled: isEnabled,
        transitions,
      });
      await mutate(saved, { revalidate: false });
      setToast({
        type: "success",
        title: "Workflow saved",
        message: isEnabled ? "The rules apply from now on." : "The workflow is off.",
      });
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The workflow could not be saved.") });
    } finally {
      setIsSaving(false);
    }
  };

  const handleApplyTemplate = async () => {
    if (!templateToApply) return;
    setIsApplying(true);
    try {
      const saved = await projectWorkflowService.applyTemplate(workspaceSlug, projectId, templateToApply.key);
      await mutate(saved, { revalidate: false });
      // the template may have added states
      await fetchProjectStates(workspaceSlug, projectId);
      setToast({ type: "success", title: "Workflow applied", message: `${templateToApply.name} workflow is now on.` });
      setTemplateToApply(null);
    } catch (error) {
      setToast({ type: "error", title: "Error!", message: errorMessage(error, "The workflow could not be applied.") });
    } finally {
      setIsApplying(false);
    }
  };

  if (!workflow) return null;

  return (
    <div className="mt-10 border-t border-subtle pt-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-xl">
          <h3 className="text-h5-medium text-primary">Workflow</h3>
          <p className="mt-1 text-body-xs-regular text-tertiary">
            Choose which state a work item can move to next, like a Jira workflow. A state without rules can move to any
            state. Add reviewers to a step to let only them (and project admins) make that move.
          </p>
        </div>
        <div className="flex items-center gap-2 text-body-xs-medium text-secondary">
          Enforce workflow
          <Switch
            size="sm"
            checked={isEnabled}
            onCheckedChange={(checked) => setIsEnabled(checked)}
            disabled={!isEditable}
            aria-label="Enforce workflow"
          />
        </div>
      </div>

      {isEditable && workflow.templates.length > 0 && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="text-caption-md-regular text-tertiary">Start from a template:</span>
          {workflow.templates.map((template) => (
            <Button
              key={template.key}
              variant="secondary"
              size="sm"
              stretch="auto"
              label={template.name}
              onClick={() => setTemplateToApply(template)}
            />
          ))}
        </div>
      )}

      <div className="mt-5 divide-y divide-subtle rounded-lg border border-subtle">
        {states.map((state) => {
          const rules = transitions.filter((item) => item.from_state === state.id);
          return (
            <div key={state.id} className="flex flex-col gap-2 px-4 py-3 md:flex-row md:items-start">
              <div className="flex w-44 shrink-0 items-center gap-2 pt-1">
                <StateChip state={state} />
              </div>
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                {rules.length === 0 && (
                  <span className="pt-1 text-caption-md-regular text-tertiary">No rules: can move to any state</span>
                )}
                {rules.map((rule) => (
                  <div key={rule.to_state} className="flex flex-wrap items-center gap-2">
                    <ArrowNarrowRightOutline className="size-3.5 text-tertiary" aria-hidden="true" />
                    <StateChip state={stateMap.get(rule.to_state)} />
                    <span className="text-caption-md-regular text-tertiary">by</span>
                    <div className="min-w-32">
                      <MemberSelect
                        value={rule.reviewer_ids}
                        onChange={(ids) => updateTransition(rule.from_state, rule.to_state, { reviewer_ids: ids })}
                        projectId={projectId}
                        multiple
                        variant="select-ghost-md"
                        placeholder="Anyone"
                        disabled={!isEditable}
                        showLabel={rule.reviewer_ids.length <= 1}
                        tooltip={{ heading: "Reviewers" }}
                      />
                    </div>
                    {isEditable && (
                      <IconButton
                        variant="ghost"
                        size="sm"
                        icon={<CloseOutline />}
                        aria-label={`Remove move to ${stateMap.get(rule.to_state)?.name ?? "state"}`}
                        onClick={() => updateTransition(rule.from_state, rule.to_state, null)}
                      />
                    )}
                  </div>
                ))}
                {isEditable && (
                  <div className="w-56">
                    <StateSelect
                      projectId={projectId}
                      value={null}
                      onChange={(toState) => addTransition(state.id, toState)}
                      variant="select-ghost-md"
                      placeholder="+ Add permitted state change"
                    />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {isEditable && (
        <div className="mt-4 flex items-center justify-end gap-2">
          {isDirty && <span className="text-caption-md-regular text-tertiary">Unsaved changes</span>}
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            label={isSaving ? "Saving..." : "Save workflow"}
            disabled={!isDirty || isSaving}
            onClick={() => void handleSave()}
          />
        </div>
      )}

      <ConfirmDialog
        isOpen={!!templateToApply}
        handleClose={() => setTemplateToApply(null)}
        handleSubmit={handleApplyTemplate}
        title={`Apply the ${templateToApply?.name ?? ""} workflow?`}
        content={`${templateToApply?.description ?? ""} Missing states are added, your existing states are kept, and the current rules are replaced.`}
        variant="primary"
        isSubmitting={isApplying}
        primaryButtonText={{ loading: "Applying...", default: "Apply workflow" }}
      />
    </div>
  );
});
