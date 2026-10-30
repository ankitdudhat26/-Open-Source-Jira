/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useId, useState } from "react";
// plane imports
import { Button } from "@makeplane/propel/components/button";
import {
  Dialog,
  DialogActions,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { TextArea, TextAreaGroup } from "@makeplane/propel/components/text-area";
import { useTranslation } from "@plane/i18n";
import type { TIssue } from "@plane/types";
// hooks
import { useProject } from "@/hooks/store/use-project";

type Props = {
  data: Partial<TIssue>;
  isOpen: boolean;
  onClose: () => void;
  /** Declines with the reason, which the person who sent the request sees. */
  onSubmit: (reason: string) => Promise<void>;
};

export function DeclineIssueModal(props: Props) {
  const { isOpen, onClose, data, onSubmit } = props;
  // states
  const [isDeclining, setIsDeclining] = useState(false);
  const [reason, setReason] = useState("");
  const reasonId = useId();
  // store hooks
  const { getProjectById } = useProject();
  const { t } = useTranslation();
  // derived values
  const projectDetails = data.project_id ? getProjectById(data?.project_id) : undefined;
  const trimmedReason = reason.trim();

  const handleClose = () => {
    setIsDeclining(false);
    setReason("");
    onClose();
  };

  const handleDecline = async () => {
    if (!trimmedReason) return;
    setIsDeclining(true);
    try {
      await onSubmit(trimmedReason);
      setReason("");
    } catch (error) {
      console.error("Failed to decline the intake work item", error);
    } finally {
      setIsDeclining(false);
    }
  };

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
    >
      <DialogContent size="md">
        <DialogMain>
          <DialogHeader>
            <DialogHeading>
              <DialogTitle>{t("inbox_issue.modals.decline.title")}</DialogTitle>
            </DialogHeading>
          </DialogHeader>
          <DialogBody tabIndex={0}>
            <div className="flex flex-col gap-3">
              <p className="text-body-xs-regular text-secondary">
                Decline work item{" "}
                <span className="font-medium break-words text-primary">
                  {projectDetails?.identifier}-{data?.sequence_id}
                </span>
                ? The person who sent it sees the reason. This action cannot be undone.
              </p>
              <div className="flex flex-col gap-1.5">
                <label htmlFor={reasonId} className="text-caption-md-medium text-secondary">
                  Reason <span className="text-danger-primary">*</span>
                </label>
                <TextAreaGroup resize="none">
                  <TextArea
                    id={reasonId}
                    size="md"
                    surface="field"
                    autoResize
                    maxRows={8}
                    maxLength={2000}
                    value={reason}
                    placeholder="e.g. Already fixed in version 2.1, or not part of the agreed scope."
                    onChange={(event) => setReason(event.target.value)}
                  />
                </TextAreaGroup>
              </div>
            </div>
          </DialogBody>
        </DialogMain>
        <DialogActions>
          <Button variant="secondary" size="md" stretch="auto" label={t("cancel")} onClick={handleClose} />
          <Button
            variant="danger"
            size="md"
            stretch="auto"
            label={isDeclining ? t("declining") : t("decline")}
            disabled={!trimmedReason || isDeclining}
            onClick={() => void handleDecline()}
          />
        </DialogActions>
      </DialogContent>
    </Dialog>
  );
}
