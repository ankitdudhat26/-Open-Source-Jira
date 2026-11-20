/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { forwardRef, useCallback, useRef, useState } from "react";
// plane imports
import { LiteTextEditorWithRef, RichTextEditorWithRef } from "@plane/editor";
import type { EditorRefApi, TFileHandler } from "@plane/editor";
// components
import { IssueCommentToolbar } from "@/components/editor/toolbar";
// local imports
import { MAX_FILE_SIZE, send } from "./portal-shared";

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

/**
 * Images in the portal's editors: shown through the link (the client is not a member of the project); with `uploadUrl`
 * an image put in a comment is stored with the work item, so it shows in the comment for the team too.
 */
export const portalFileHandler = (base: string, uploadUrl?: string): TFileHandler => {
  const src = (path: string, download = false) =>
    !path ? "" : /^(https?:|blob:|data:)/.test(path) ? path : `${base}assets/${path}/${download ? "?download=1" : ""}`;
  return {
    assetsUploadStatus: {},
    cancel: () => {},
    checkIfAssetExists: async () => true,
    delete: async () => {},
    getAssetDownloadSrc: async (path) => src(path, true),
    getAssetSrc: async (path) => src(path),
    restore: async () => {},
    upload: async (_blockId, file) => {
      if (!uploadUrl) throw new Error("Add files under Attachments.");
      const body = new FormData();
      body.append("file", file);
      return (await send<{ asset_id: string }>(uploadUrl, "POST", body)).asset_id;
    },
    duplicate: async (assetId: string) => assetId,
    validation: { maxFileSize: MAX_FILE_SIZE },
  };
};

type TCommentEditorProps = {
  id: string;
  /** the link's API base, to show images */
  base: string;
  /** where an image put in the comment is uploaded */
  uploadUrl: string;
  onChange: (html: string) => void;
  onSubmit: () => void;
  /** nothing to send yet (no text, image or file) */
  isEmpty: boolean;
  isSubmitting: boolean;
  /** shown between the text and the toolbar (the files picked for the comment) */
  children?: React.ReactNode;
};

/**
 * The comment box, as in the app: the same editor and toolbar (bold, italic, underline, strikethrough, alignment,
 * lists, to-do list, quote, code, image) with the Comment button; Enter sends, Shift + Enter starts a new line.
 */
export function IntakeCommentEditor(props: TCommentEditorProps) {
  const { id, base, uploadUrl, onChange, onSubmit, isEmpty, isSubmitting, children } = props;
  // the toolbar follows the editor's state, so it renders again once the editor is there (the editor hands a new
  // handle on every render: it is kept in a ref, and only the first one causes a render)
  const instanceRef = useRef<EditorRefApi | null>(null);
  const [, setIsReady] = useState(false);
  const editorRef = useCallback((instance: EditorRefApi | null) => {
    instanceRef.current = instance;
    if (instance) setIsReady(true);
  }, []);
  const editor = instanceRef.current;

  return (
    <div className="flex flex-col gap-2">
      <LiteTextEditorWithRef
        ref={editorRef}
        id={id}
        editable
        initialValue="<p></p>"
        onChange={(_json, html) => onChange(html)}
        onEnterKeyPress={() => {
          if (!isEmpty && !isSubmitting) onSubmit();
        }}
        placeholder="Add comment"
        disabledExtensions={["ai", "issue-embed"]}
        flaggedExtensions={[]}
        fileHandler={portalFileHandler(base, uploadUrl)}
        mentionHandler={{ renderComponent: () => null, searchCallback: async () => [] }}
        getEditorMetaData={() => ({ file_assets: [], user_mentions: [] })}
        extendedEditorProps={{}}
        containerClassName="relative min-h-[96px] px-1"
        editorClassName="min-h-[80px] py-1"
        displayConfig={{ fontSize: "small-font" }}
      />
      {children}
      <IssueCommentToolbar
        editorRef={editor}
        executeCommand={(item) => {
          // the toolbar's items carry their own extra props (as in the app)
          // @ts-expect-error type mismatch here
          editor?.executeMenuItemCommand({ itemKey: item.itemKey, ...item.extraProps });
        }}
        handleSubmit={() => onSubmit()}
        isCommentEmpty={isEmpty}
        isSubmitting={isSubmitting}
        showSubmitButton
      />
    </div>
  );
}

/**
 * A description or comment written in the app, shown read only with the same editor (it only keeps what the editor
 * knows how to show, so the HTML cannot run anything).
 */
export function IntakeReadOnlyHtml({ id, html, base }: { id: string; html: string; base?: string }) {
  return (
    <RichTextEditorWithRef
      id={id}
      editable={false}
      initialValue={html || "<p></p>"}
      onChange={() => {}}
      disabledExtensions={["ai", "issue-embed"]}
      flaggedExtensions={[]}
      fileHandler={base ? portalFileHandler(base) : NO_FILES}
      mentionHandler={{ renderComponent: () => null, searchCallback: async () => [] }}
      getEditorMetaData={() => ({ file_assets: [], user_mentions: [] })}
      extendedEditorProps={{}}
      containerClassName="border-none p-0"
      editorClassName="py-0"
      displayConfig={{ fontSize: "small-font" }}
    />
  );
}
