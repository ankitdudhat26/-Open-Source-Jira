/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect } from "react";
import { observer } from "mobx-react";
import { ChevronLeftOutline, ChevronRightOutline, CloseOutline, DownloadOutline } from "@makeplane/propel/icons";
import { useTranslation } from "@plane/i18n";
import type { TIssueAttachment, TIssueServiceType } from "@plane/types";
import { EIssueServiceType } from "@plane/types";
// ui
import { Button } from "@makeplane/propel/components/button";
import {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogHeader,
  DialogHeading,
  DialogMain,
  DialogTitle,
} from "@makeplane/propel/components/dialog";
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import { convertBytesToSize, getFileExtension, getFilePreviewType, getFileURL } from "@plane/utils";
// components
import { getFileIcon } from "@/components/icons";
// hooks
import { useIssueDetail } from "@/hooks/store/use-issue-detail";

type TIssueAttachmentViewer = {
  issueId: string;
  issueServiceType?: TIssueServiceType;
};

type TAttachmentPreview = {
  attachment: TIssueAttachment;
  /** Serves the file inline so the browser shows it instead of downloading it. */
  previewURL: string;
  onDownload: () => void;
};

function AttachmentPreview(props: TAttachmentPreview) {
  const { attachment, previewURL, onDownload } = props;
  const { t } = useTranslation();
  const fileName = attachment.attributes.name;

  switch (getFilePreviewType(fileName)) {
    case "image":
      return <img src={previewURL} alt={fileName} className="max-h-full max-w-full rounded-md object-contain" />;
    case "video":
      // oxlint-disable-next-line jsx-a11y/media-has-caption -- user-uploaded videos have no caption track
      return <video src={previewURL} controls className="max-h-full max-w-full rounded-md" />;
    case "audio":
      // oxlint-disable-next-line jsx-a11y/media-has-caption -- user-uploaded audio has no caption track
      return <audio src={previewURL} controls className="w-full max-w-xl" />;
    case "pdf":
      return (
        // No sandbox: the browser's PDF viewer does not load inside a sandboxed frame
        // oxlint-disable-next-line react/iframe-missing-sandbox
        <iframe src={previewURL} title={fileName} className="size-full rounded-md border border-subtle bg-white" />
      );
    case "text":
      return (
        <iframe
          src={previewURL}
          title={fileName}
          sandbox=""
          className="size-full rounded-md border border-subtle bg-white"
        />
      );
    default:
      return (
        <div className="flex flex-col items-center gap-3 text-center">
          {getFileIcon(getFileExtension(fileName), 64)}
          <div className="flex flex-col gap-1">
            <p className="text-14 font-medium text-primary">{fileName}</p>
            <p className="text-13 text-tertiary">{convertBytesToSize(attachment.attributes.size)}</p>
          </div>
          <p className="text-13 text-secondary">{t("attachment.preview_not_available")}</p>
          <Button
            variant="primary"
            size="md"
            stretch="auto"
            icon={<Icon icon={DownloadOutline} />}
            label={t("page_navigation_pane.tabs.assets.download_button")}
            onClick={onDownload}
          />
        </div>
      );
  }
}

/**
 * Shows the work item's attachments one at a time in a popup — images, video, audio, PDFs and
 * text in the browser, other files as a card with a download button — with previous / next
 * (buttons or arrow keys) across all of them. Opened through `toggleAttachmentPreview`.
 */
export const IssueAttachmentViewer = observer(function IssueAttachmentViewer(props: TIssueAttachmentViewer) {
  const { issueId, issueServiceType = EIssueServiceType.ISSUES } = props;
  const { t } = useTranslation();
  // store hooks
  const {
    attachment: { getAttachmentsByIssueId, getAttachmentById },
    attachmentPreviewId,
    toggleAttachmentPreview,
  } = useIssueDetail(issueServiceType);
  // derived values
  const attachmentIds = getAttachmentsByIssueId(issueId) ?? [];
  const activeIndex = attachmentPreviewId ? attachmentIds.indexOf(attachmentPreviewId) : -1;
  const isOpen = activeIndex !== -1;
  const attachment = isOpen ? getAttachmentById(attachmentIds[activeIndex]) : undefined;
  // The attachment endpoint serves a download by default
  const fileURL = getFileURL(attachment?.asset_url ?? "");
  const previewURL = fileURL ? `${fileURL}?disposition=inline` : "";
  const hasMultipleAttachments = attachmentIds.length > 1;

  const showAttachmentAt = (index: number) => {
    const count = attachmentIds.length;
    toggleAttachmentPreview(attachmentIds[(index + count) % count]);
  };
  const handleDownload = () => window.open(fileURL, "_blank");

  useEffect(() => {
    if (!isOpen || !hasMultipleAttachments) return undefined;
    const handleKeyDown = (e: KeyboardEvent) => {
      // Leave arrow keys to video / audio controls that have focus
      if (e.target instanceof HTMLMediaElement) return;
      if (e.key === "ArrowLeft") showAttachmentAt(activeIndex - 1);
      if (e.key === "ArrowRight") showAttachmentAt(activeIndex + 1);
    };
    // Capture phase: the dialog popup handles key presses inside it before they bubble to the document.
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  });

  return (
    <Dialog
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) toggleAttachmentPreview(null);
      }}
    >
      <DialogContent size="full" density="compact">
        <DialogMain>
          <DialogHeader>
            <div className="flex w-full items-center justify-between gap-3">
              <div className="flex min-w-0 items-baseline gap-3">
                <DialogHeading>
                  <DialogTitle>{attachment?.attributes.name}</DialogTitle>
                </DialogHeading>
                {hasMultipleAttachments && (
                  <span className="shrink-0 text-13 text-tertiary">
                    {activeIndex + 1} / {attachmentIds.length}
                  </span>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <IconButton
                  variant="ghost"
                  size="sm"
                  aria-label={t("page_navigation_pane.tabs.assets.download_button")}
                  icon={<Icon icon={DownloadOutline} />}
                  onClick={handleDownload}
                />
                <IconButton
                  variant="ghost"
                  size="sm"
                  aria-label={t("close")}
                  icon={<Icon icon={CloseOutline} />}
                  render={<DialogClose />}
                />
              </div>
            </div>
          </DialogHeader>
          <DialogBody>
            <div className="relative flex h-full min-h-0 items-center justify-center px-14">
              {attachment && (
                <AttachmentPreview
                  key={attachment.id}
                  attachment={attachment}
                  previewURL={previewURL}
                  onDownload={handleDownload}
                />
              )}
              {hasMultipleAttachments && (
                <>
                  <div className="absolute top-1/2 left-0 -translate-y-1/2">
                    <IconButton
                      variant="secondary"
                      size="lg"
                      aria-label={t("prev")}
                      icon={<Icon icon={ChevronLeftOutline} />}
                      onClick={() => showAttachmentAt(activeIndex - 1)}
                    />
                  </div>
                  <div className="absolute top-1/2 right-0 -translate-y-1/2">
                    <IconButton
                      variant="secondary"
                      size="lg"
                      aria-label={t("next")}
                      icon={<Icon icon={ChevronRightOutline} />}
                      onClick={() => showAttachmentAt(activeIndex + 1)}
                    />
                  </div>
                </>
              )}
            </div>
          </DialogBody>
        </DialogMain>
      </DialogContent>
    </Dialog>
  );
});
