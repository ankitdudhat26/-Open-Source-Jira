/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

export const generateFileName = (fileName: string) => {
  const date = new Date();
  const timestamp = date.getTime();

  const _fileName = getFileName(fileName);
  const nameWithoutExtension = _fileName.length > 80 ? _fileName.substring(0, 80) : _fileName;
  const extension = getFileExtension(fileName);

  return `${nameWithoutExtension}-${timestamp}.${extension}`;
};

export const getFileExtension = (filename: string) => filename.slice(((filename.lastIndexOf(".") - 1) >>> 0) + 2);

export const getFileName = (fileName: string) => {
  const dotIndex = fileName.lastIndexOf(".");

  const nameWithoutExtension = fileName.substring(0, dotIndex);

  return nameWithoutExtension;
};

export type TFilePreviewType = "image" | "video" | "audio" | "pdf" | "text";

const FILE_PREVIEW_TYPES: Record<string, TFilePreviewType> = {
  ...Object.fromEntries(["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "avif"].map((ext) => [ext, "image"])),
  ...Object.fromEntries(["mp4", "webm", "mov", "m4v", "ogv"].map((ext) => [ext, "video"])),
  ...Object.fromEntries(["mp3", "wav", "ogg", "m4a", "aac", "flac"].map((ext) => [ext, "audio"])),
  pdf: "pdf",
  ...Object.fromEntries(["txt", "csv", "md", "log", "json"].map((ext) => [ext, "text"])),
};

/** How a file can be shown in the browser, judged by the extension of its name; undefined when it can't. */
export const getFilePreviewType = (fileName: string): TFilePreviewType | undefined =>
  FILE_PREVIEW_TYPES[getFileExtension(fileName).toLowerCase()];

export const convertBytesToSize = (bytes: number) => {
  let size;

  if (bytes < 1024 * 1024) {
    size = Math.round(bytes / 1024) + " KB";
  } else {
    size = Math.round(bytes / (1024 * 1024)) + " MB";
  }

  return size;
};
