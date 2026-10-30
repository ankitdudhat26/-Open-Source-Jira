/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { forwardRef } from "react";
// plane imports
import { RichTextEditorWithRef } from "@plane/editor";
import type { EditorRefApi, TFileHandler } from "@plane/editor";

type Props = {
  id: string;
  onChange: (html: string) => void;
  placeholder?: string;
};

const NO_FILES: TFileHandler = {
  assetsUploadStatus: {},
  cancel: () => {},
  checkIfAssetExists: async () => false,
  delete: async () => {},
  getAssetDownloadSrc: async () => "",
  getAssetSrc: async () => "",
  restore: async () => {},
  upload: async () => {
    throw new Error("Add files under Attachments.");
  },
  duplicate: async (assetId: string) => assetId,
  validation: { maxFileSize: 0 },
};

/**
 * The description of a request: the same rich text editor as a work item's (type "/" for headings, lists, tables,
 * quotes, code…). Clients are not members of the project, so images go under Attachments and nobody can be mentioned.
 */
export const IntakeDescriptionEditor = forwardRef(function IntakeDescriptionEditor(
  props: Props,
  ref: React.ForwardedRef<EditorRefApi>
) {
  const { id, onChange, placeholder } = props;
  return (
    <RichTextEditorWithRef
      ref={ref}
      id={id}
      editable
      initialValue="<p></p>"
      onChange={(_json, html) => onChange(html)}
      placeholder={placeholder ?? "Press '/' for commands"}
      disabledExtensions={["image", "ai", "issue-embed"]}
      flaggedExtensions={[]}
      fileHandler={NO_FILES}
      mentionHandler={{ renderComponent: () => null, searchCallback: async () => [] }}
      getEditorMetaData={() => ({ file_assets: [], user_mentions: [] })}
      extendedEditorProps={{}}
      containerClassName="min-h-[160px] rounded-md border border-subtle-1 bg-surface-1 px-3 py-1 focus-within:border-accent-strong"
      editorClassName="min-h-[140px] py-2"
      displayConfig={{ fontSize: "small-font" }}
    />
  );
});
