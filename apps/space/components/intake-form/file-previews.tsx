/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useRef, useState } from "react";
// plane imports
import { Icon } from "@makeplane/propel/components/icon";
import { IconButton } from "@makeplane/propel/components/icon-button";
import {
  ChevronLeftOutline,
  ChevronRightOutline,
  CloseOutline,
  FileOutline,
  FileSpreadsheetOutline,
  FileZipOutline,
  NewTabOutline,
  UploadOutline,
} from "@makeplane/propel/icons";
import { cn } from "@plane/utils";
// local imports
import { MAX_FILE_SIZE } from "./portal-shared";

/**
 * Attachments in the client portal: a picker that takes several files at once (click, or drop them on it) and cards
 * that preview each file — a thumbnail for an image, the file's kind for anything else — opening a larger preview
 * (images and PDFs) on click.
 */

/** a file to show: picked (not sent yet) or already attached (with its link) */
export type TPreviewFile = { key: string; name: string; size: number; url: string; type?: string };

const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "avif"]);
const SHEET_EXTENSIONS = new Set(["xls", "xlsx", "csv", "ods"]);
const ARCHIVE_EXTENSIONS = new Set(["zip", "rar", "7z", "tar", "gz"]);

const extension = (name: string) => name.split(".").pop()?.toLowerCase() ?? "";
export const isImage = (file: Pick<TPreviewFile, "name" | "type">) =>
  file.type ? file.type.startsWith("image/") : IMAGE_EXTENSIONS.has(extension(file.name));
const isPdf = (file: Pick<TPreviewFile, "name" | "type">) =>
  file.type ? file.type === "application/pdf" : extension(file.name) === "pdf";
const canPreview = (file: TPreviewFile) => isImage(file) || isPdf(file);

export const sizeLabel = (size: number) =>
  size >= 1024 * 1024 ? `${(size / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(size / 1024))} KB`;

/** the same file (same name and size) picked twice is kept once */
const fileKey = (file: File) => `${file.name}-${file.size}`;

/**
 * Adds the picked files to `current`: one copy of each, none over 5 MB. Returns the new list and an error naming the
 * files that were too big.
 */
export const addFiles = (current: File[], picked: FileList | File[] | null) => {
  const chosen = Array.from(picked ?? []);
  const tooBig = chosen.filter((file) => file.size > MAX_FILE_SIZE);
  const known = new Set(current.map(fileKey));
  const added = chosen.filter((file) => {
    if (file.size > MAX_FILE_SIZE || known.has(fileKey(file))) return false;
    known.add(fileKey(file));
    return true;
  });
  return {
    files: [...current, ...added],
    added,
    error: tooBig.length
      ? `${tooBig.map((file) => file.name).join(", ")} ${tooBig.length === 1 ? "is" : "are"} over 5 MB.`
      : "",
  };
};

/** Picked files as files to show, with a local link for the preview (released when they go). */
export const usePickedPreviews = (files: File[]): TPreviewFile[] => {
  const previews = useMemo(
    () =>
      files.map((file) => ({
        key: fileKey(file),
        name: file.name,
        size: file.size,
        type: file.type || undefined,
        url: URL.createObjectURL(file),
      })),
    [files]
  );
  useEffect(() => () => previews.forEach((preview) => URL.revokeObjectURL(preview.url)), [previews]);
  return previews;
};

type TDropZoneProps = {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
  /** "lg": the form's field; "sm": a compact row (a comment) */
  size?: "lg" | "sm";
  label?: string;
};

/** Click to choose files (several at once) or drop them here. */
export function FileDropZone({ onFiles, disabled, size = "lg", label = "Add files" }: TDropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isOver, setIsOver] = useState(false);

  const input = (
    <input
      ref={inputRef}
      type="file"
      multiple
      className="hidden"
      aria-label={label}
      onChange={(event) => {
        onFiles(Array.from(event.target.files ?? []));
        event.target.value = "";
      }}
    />
  );
  const dropHandlers = {
    onDragOver: (event: React.DragEvent) => {
      if (disabled || !event.dataTransfer.types.includes("Files")) return;
      event.preventDefault();
      setIsOver(true);
    },
    onDragLeave: () => setIsOver(false),
    onDrop: (event: React.DragEvent) => {
      if (disabled) return;
      event.preventDefault();
      setIsOver(false);
      onFiles(Array.from(event.dataTransfer.files));
    },
  };

  if (size === "sm")
    return (
      <>
        {input}
        <button
          type="button"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
          {...dropHandlers}
          className={cn(
            "flex items-center gap-1.5 rounded-sm border border-dashed px-2 py-1 text-caption-md-medium text-secondary hover:bg-layer-1-hover disabled:opacity-60",
            isOver ? "border-accent-strong bg-accent-subtle" : "border-subtle-1"
          )}
        >
          <UploadOutline className="size-3.5" />
          {label}
        </button>
      </>
    );

  return (
    <>
      {input}
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        {...dropHandlers}
        className={cn(
          "flex flex-col items-center gap-1 rounded-md border border-dashed px-4 py-5 text-center transition-colors disabled:opacity-60",
          isOver ? "border-accent-strong bg-accent-subtle" : "border-subtle-1 bg-layer-1 hover:bg-layer-1-hover"
        )}
      >
        <UploadOutline className="size-5 text-tertiary" />
        <span className="text-body-xs-medium text-primary">{isOver ? "Drop the files here" : label}</span>
        <span className="text-caption-sm-regular text-tertiary">
          Click to choose (select several at once) or drag and drop images and documents, up to 5 MB each
        </span>
      </button>
    </>
  );
}

function KindIcon({ name }: { name: string }) {
  const ext = extension(name);
  const KindGlyph = SHEET_EXTENSIONS.has(ext)
    ? FileSpreadsheetOutline
    : ARCHIVE_EXTENSIONS.has(ext)
      ? FileZipOutline
      : FileOutline;
  return (
    <span className="flex flex-col items-center gap-1 text-tertiary">
      <KindGlyph className="size-7" />
      {ext && <span className="text-caption-sm-medium uppercase">{ext.slice(0, 5)}</span>}
    </span>
  );
}

type TFileCardsProps = {
  files: TPreviewFile[];
  /** a picked file can be taken off before it is sent */
  onRemove?: (key: string) => void;
  className?: string;
};

/** A grid of cards, one per file: its preview, name and size. A click opens it larger (or in a new tab). */
export function FileCards({ files, onRemove, className }: TFileCardsProps) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  if (files.length === 0) return null;
  const previewable = files.filter(canPreview);

  return (
    <>
      <ul className={cn("grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4", className)}>
        {files.map((file) => {
          const image = isImage(file);
          const thumbnail = image ? (
            <img src={file.url} alt="" className="size-full object-contain p-1" loading="lazy" />
          ) : (
            <KindIcon name={file.name} />
          );
          return (
            <li
              key={file.key}
              className="group relative flex flex-col overflow-hidden rounded-md border border-subtle bg-surface-1"
            >
              {canPreview(file) ? (
                <button
                  type="button"
                  onClick={() => setOpenKey(file.key)}
                  aria-label={`Preview ${file.name}`}
                  className="flex h-28 items-center justify-center overflow-hidden bg-layer-1"
                >
                  {thumbnail}
                </button>
              ) : (
                <a
                  href={file.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  download={file.name}
                  aria-label={`Open ${file.name}`}
                  className="flex h-28 items-center justify-center bg-layer-1"
                >
                  {thumbnail}
                </a>
              )}
              <div className="flex items-center gap-1 border-t border-subtle px-2 py-1.5">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-caption-md-medium text-primary" title={file.name}>
                    {file.name}
                  </span>
                  <span className="block text-caption-sm-regular text-tertiary">{sizeLabel(file.size)}</span>
                </span>
              </div>
              {onRemove && (
                <span className="absolute top-1 right-1 rounded-sm bg-surface-1 shadow-raised-100">
                  <IconButton
                    variant="ghost"
                    size="xs"
                    icon={<Icon icon={CloseOutline} />}
                    aria-label={`Remove ${file.name}`}
                    onClick={() => onRemove(file.key)}
                  />
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {openKey && (
        <FilePreview files={previewable} openKey={openKey} onChange={setOpenKey} onClose={() => setOpenKey(null)} />
      )}
    </>
  );
}

type TFilePreviewProps = {
  files: TPreviewFile[];
  openKey: string;
  onChange: (key: string) => void;
  onClose: () => void;
};

/** A file shown large over the page: an image, or a PDF in a frame; arrows go through the others. */
function FilePreview({ files, openKey, onChange, onClose }: TFilePreviewProps) {
  const index = Math.max(
    0,
    files.findIndex((file) => file.key === openKey)
  );
  const file = files[index];
  const go = (step: number) => {
    if (files.length > 1) onChange(files[(index + step + files.length) % files.length].key);
  };

  useEffect(() => {
    // first, so Escape closes only the preview (not the panel under it)
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
      if (event.key === "ArrowRight") go(1);
      if (event.key === "ArrowLeft") go(-1);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  });

  if (!file) return null;
  return (
    <div role="dialog" aria-modal="true" aria-label={file.name} className="fixed inset-0 z-50 flex flex-col">
      <button type="button" aria-label="Close preview" onClick={onClose} className="absolute inset-0 bg-black/90" />
      <div className="relative flex items-center gap-2 bg-black/60 px-4 py-3 text-white">
        <span className="min-w-0 flex-1 truncate text-body-sm-medium">{file.name}</span>
        {files.length > 1 && (
          <span className="text-caption-md-regular text-white/70">
            {index + 1} / {files.length}
          </span>
        )}
        <a
          href={file.url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1 rounded-sm px-2 py-1 text-caption-md-medium hover:bg-white/10"
        >
          <NewTabOutline className="size-3.5" />
          Open
        </a>
        <button type="button" onClick={onClose} aria-label="Close preview" className="rounded-sm p-1 hover:bg-white/10">
          <CloseOutline className="size-5" />
        </button>
      </div>
      <div className="pointer-events-none relative flex min-h-0 flex-1 items-center justify-center px-4 pb-6 sm:px-16">
        {isImage(file) ? (
          <img
            src={file.url}
            alt={file.name}
            className="pointer-events-auto max-h-full max-w-full rounded-md object-contain shadow-raised-200"
          />
        ) : (
          <object
            data={file.url}
            type="application/pdf"
            aria-label={file.name}
            className="pointer-events-auto size-full max-w-5xl rounded-md bg-white shadow-raised-200"
          >
            <a href={file.url} target="_blank" rel="noopener noreferrer" className="text-body-sm-medium underline">
              Open {file.name}
            </a>
          </object>
        )}
      </div>
      {files.length > 1 && (
        <>
          <button
            type="button"
            aria-label="Previous file"
            onClick={() => go(-1)}
            className="absolute top-1/2 left-2 -translate-y-1/2 rounded-full bg-black/50 p-2 text-white hover:bg-black/70"
          >
            <ChevronLeftOutline className="size-5" />
          </button>
          <button
            type="button"
            aria-label="Next file"
            onClick={() => go(1)}
            className="absolute top-1/2 right-2 -translate-y-1/2 rounded-full bg-black/50 p-2 text-white hover:bg-black/70"
          >
            <ChevronRightOutline className="size-5" />
          </button>
        </>
      )}
    </div>
  );
}
