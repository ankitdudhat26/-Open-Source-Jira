/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useRef, useState } from "react";
import { observer } from "mobx-react";
// plane imports
import { Icon as PropelIcon } from "@makeplane/propel/components/icon";
import { Pill } from "@makeplane/propel/components/pill";
import { AttachOutline, BlockingOutline, CloseOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
// components
import { ExistingIssuesListModal } from "@/components/core/modals/existing-issues-list-modal";
// hooks
import { useIssueModal } from "@/hooks/context/use-issue-modal";
import { useFileSize } from "@/hooks/use-file-size";

type Props = {
  workspaceSlug: string;
  projectId: string | null;
};

function RemovableChip(props: { label: string; onRemove: () => void; removeLabel: string }) {
  const { label, onRemove, removeLabel } = props;
  return (
    <span className="inline-flex max-w-60 items-center gap-1 rounded-sm border border-subtle bg-layer-1 py-0.5 pr-0.5 pl-1.5 text-caption-sm-regular text-secondary">
      <span className="truncate">{label}</span>
      <button
        type="button"
        aria-label={removeLabel}
        className="grid size-4 shrink-0 place-items-center rounded-sm hover:bg-layer-2"
        onClick={onRemove}
      >
        <CloseOutline className="size-3" />
      </button>
    </span>
  );
}

/** File attachments and "blocked by" work items of a work item that is being created. */
export const IssueAttachmentsAndBlockedBy = observer(function IssueAttachmentsAndBlockedBy(props: Props) {
  const { workspaceSlug, projectId } = props;
  // refs
  const fileInputRef = useRef<HTMLInputElement>(null);
  // states
  const [isBlockedByModalOpen, setIsBlockedByModalOpen] = useState(false);
  // hooks
  const { maxFileSize } = useFileSize();
  const { pendingAttachments, setPendingAttachments, pendingBlockedByIssues, setPendingBlockedByIssues } =
    useIssueModal();

  // nothing picked here should leak into the next work item
  useEffect(
    () => () => {
      setPendingAttachments([]);
      setPendingBlockedByIssues([]);
    },
    [setPendingAttachments, setPendingBlockedByIssues]
  );

  const handleFilesSelected = (files: FileList | null) => {
    if (!files) return;
    const selected = Array.from(files);
    const tooLarge = selected.filter((file) => file.size > maxFileSize);
    if (tooLarge.length > 0)
      setToast({
        type: "error",
        title: "Error!",
        message: `Files must be smaller than ${maxFileSize / 1024 / 1024} MB: ${tooLarge.map((file) => file.name).join(", ")}`,
      });
    setPendingAttachments((current) => [...current, ...selected.filter((file) => file.size <= maxFileSize)]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        aria-label="Attach files"
        onChange={(e) => handleFilesSelected(e.target.files)}
      />
      <Pill
        size="sm"
        variant="outline"
        startIcon={<PropelIcon icon={<AttachOutline className="size-3.5" />} />}
        onClick={() => fileInputRef.current?.click()}
        label={pendingAttachments.length > 0 ? `Attachments (${pendingAttachments.length})` : "File attachment"}
      />
      {pendingAttachments.map((file, index) => (
        <RemovableChip
          key={`${file.name}-${file.size}-${file.lastModified}`}
          label={file.name}
          removeLabel={`Remove ${file.name}`}
          onRemove={() => setPendingAttachments((current) => current.filter((_, i) => i !== index))}
        />
      ))}

      <Pill
        size="sm"
        variant="outline"
        startIcon={<PropelIcon icon={<BlockingOutline className="size-3.5" />} />}
        onClick={() => setIsBlockedByModalOpen(true)}
        label={pendingBlockedByIssues.length > 0 ? `Blocked by (${pendingBlockedByIssues.length})` : "Blocked by"}
      />
      {pendingBlockedByIssues.map((issue) => (
        <RemovableChip
          key={issue.id}
          label={`${issue.project__identifier}-${issue.sequence_id} ${issue.name}`}
          removeLabel={`Remove ${issue.name}`}
          onRemove={() => setPendingBlockedByIssues((current) => current.filter((item) => item.id !== issue.id))}
        />
      ))}
      <ExistingIssuesListModal
        workspaceSlug={workspaceSlug}
        projectId={projectId ?? undefined}
        isOpen={isBlockedByModalOpen}
        handleClose={() => setIsBlockedByModalOpen(false)}
        searchParams={{}}
        selectedWorkItemIds={pendingBlockedByIssues.map((issue) => issue.id)}
        handleOnSubmit={async (issues) => {
          setPendingBlockedByIssues((current) => [
            ...current,
            ...issues.filter((issue) => !current.some((item) => item.id === issue.id)),
          ]);
        }}
        workspaceLevelToggle
      />
    </div>
  );
});
