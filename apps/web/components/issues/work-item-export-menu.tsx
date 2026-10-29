/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
// plane imports
import { API_BASE_URL } from "@plane/constants";
import { Button } from "@makeplane/propel/components/button";
import { Menu, MenuContent, MenuItem, MenuTrigger } from "@makeplane/propel/components/menu";
import { ExportOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";

const EXPORT_FORMATS = [
  { format: "word", label: "Word document", extension: "doc" },
  { format: "excel", label: "Excel (.xlsx)", extension: "xlsx" },
  { format: "csv", label: "CSV", extension: "csv" },
];

type Props = {
  workspaceSlug: string;
  projectId: string;
};

/** Download every work item (story) of the project as Word, Excel or CSV — like Jira's Export menu. */
export function WorkItemExportMenu(props: Props) {
  const { workspaceSlug, projectId } = props;
  const [isExporting, setIsExporting] = useState(false);

  const handleExport = async (format: string, extension: string) => {
    setIsExporting(true);
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/workspaces/${workspaceSlug}/projects/${projectId}/work-items/export/?file_type=${format}`,
        { credentials: "include" }
      );
      if (!response.ok) throw new Error(`Export failed with status ${response.status}`);
      const fileName =
        /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? `work-items.${extension}`;
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error(error);
      setToast({ type: "error", title: "Export failed", message: "The work items could not be exported. Try again." });
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <Menu>
      <MenuTrigger
        render={
          <Button
            variant="secondary"
            size="md"
            stretch="auto"
            icon={<ExportOutline />}
            label={isExporting ? "Exporting..." : "Export"}
            disabled={isExporting}
          />
        }
      />
      <MenuContent side="bottom" align="end">
        {EXPORT_FORMATS.map((option) => (
          <MenuItem
            key={option.format}
            label={option.label}
            onClick={() => void handleExport(option.format, option.extension)}
          />
        ))}
      </MenuContent>
    </Menu>
  );
}
