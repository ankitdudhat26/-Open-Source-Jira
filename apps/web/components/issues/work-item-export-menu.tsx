/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useState } from "react";
// plane imports
import { API_BASE_URL } from "@plane/constants";
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
import { Select, SelectContent, SelectItem, SelectList, SelectTrigger } from "@makeplane/propel/components/select";
import { ExportOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";

const EXPORT_FORMATS = [
  { value: "word", label: "Word document", extension: "doc" },
  { value: "excel", label: "Excel (.xlsx)", extension: "xlsx" },
  { value: "csv", label: "CSV", extension: "csv" },
];

// the filters of the export, in the order shown — the names match the query params of the export endpoint
const EXPORT_FILTERS = [
  { name: "feature", label: "Feature", placeholder: "All features" },
  { name: "type", label: "Type", placeholder: "All types" },
  { name: "state", label: "Status", placeholder: "All statuses" },
  { name: "assignee", label: "Assignee", placeholder: "Anyone" },
  { name: "priority", label: "Priority", placeholder: "All priorities" },
  { name: "label", label: "Labels", placeholder: "All labels" },
  { name: "module", label: "Module", placeholder: "All modules" },
  { name: "cycle", label: "Sprint", placeholder: "All sprints" },
  { name: "milestone", label: "Milestone", placeholder: "All milestones" },
] as const;

type TExportFilterName = (typeof EXPORT_FILTERS)[number]["name"];
type TExportOptions = Partial<Record<TExportFilterName, { id: string; name: string }[]>>;
type TExportFilters = Partial<Record<TExportFilterName, string[]>>;

type Props = {
  workspaceSlug: string;
  projectId: string;
};

/**
 * Download the work items (stories) of the project as Word, Excel or CSV — all of them, or only the ones matching the
 * chosen filters (a Feature with everything under it, the bugs of one assignee…) — like Jira's Export.
 */
export function WorkItemExportMenu(props: Props) {
  const { workspaceSlug, projectId } = props;
  const [isOpen, setIsOpen] = useState(false);
  const [options, setOptions] = useState<TExportOptions>();
  const [filters, setFilters] = useState<TExportFilters>({});
  const [exportFormat, setExportFormat] = useState("word");
  const [isExporting, setIsExporting] = useState(false);

  const exportUrl = `${API_BASE_URL}/api/workspaces/${workspaceSlug}/projects/${projectId}/work-items/export/`;

  useEffect(() => {
    if (!isOpen) return;
    let ignore = false;
    const loadOptions = async () => {
      try {
        const response = await fetch(`${exportUrl}options/`, { credentials: "include" });
        if (!response.ok) throw new Error(`Loading the export filters failed with status ${response.status}`);
        const data = (await response.json()) as TExportOptions;
        if (!ignore) setOptions(data);
      } catch (error) {
        console.error(error);
        if (!ignore) setOptions({});
      }
    };
    void loadOptions();
    return () => {
      ignore = true;
    };
  }, [isOpen, exportUrl]);

  const handleClose = () => {
    setIsOpen(false);
    setOptions(undefined);
  };

  const handleExport = async () => {
    const extension = EXPORT_FORMATS.find((option) => option.value === exportFormat)?.extension ?? "doc";
    const query = new URLSearchParams({ file_type: exportFormat });
    for (const [name, values] of Object.entries(filters)) {
      if (values?.length) query.set(name, values.join(","));
    }
    setIsExporting(true);
    try {
      const response = await fetch(`${exportUrl}?${query.toString()}`, { credentials: "include" });
      if (!response.ok) throw new Error(`Export failed with status ${response.status}`);
      const fileName =
        /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? `work-items.${extension}`;
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      link.click();
      URL.revokeObjectURL(url);
      handleClose();
    } catch (error) {
      console.error(error);
      setToast({ type: "error", title: "Export failed", message: "The work items could not be exported. Try again." });
    } finally {
      setIsExporting(false);
    }
  };

  const activeFilterCount = Object.values(filters).filter((values) => values?.length).length;

  return (
    <>
      <Button
        variant="secondary"
        size="md"
        stretch="auto"
        icon={<ExportOutline />}
        label="Export"
        onClick={() => setIsOpen(true)}
      />
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
                <DialogTitle>Export work items</DialogTitle>
              </DialogHeading>
            </DialogHeader>
            <DialogBody tabIndex={0}>
              <div className="flex flex-col gap-4">
                <p className="text-13 text-secondary">
                  Choose filters to export only the matching work items. Leave a filter empty to include all. A Feature
                  is exported with every work item under it.
                </p>
                {options === undefined ? (
                  <p className="text-13 text-tertiary">Loading filters...</p>
                ) : (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {EXPORT_FILTERS.filter((filter) => options[filter.name]?.length).map((filter) => {
                      const items = (options[filter.name] ?? []).map((option) => ({
                        value: option.id,
                        label: option.name,
                      }));
                      return (
                        <div key={filter.name} className="flex min-w-0 flex-col gap-1">
                          <span className="text-12 font-medium text-secondary">{filter.label}</span>
                          <Select<string, true>
                            multiple
                            items={items}
                            value={filters[filter.name] ?? []}
                            onValueChange={(values) => setFilters((current) => ({ ...current, [filter.name]: values }))}
                          >
                            <SelectTrigger size="md" placeholder={filter.placeholder} />
                            <SelectContent side="bottom" align="start">
                              <SelectList>
                                {items.map((item) => (
                                  <SelectItem key={item.value} value={item.value} size="md" label={item.label} />
                                ))}
                              </SelectList>
                            </SelectContent>
                          </Select>
                        </div>
                      );
                    })}
                  </div>
                )}
                <div className="flex flex-col gap-1">
                  <span className="text-12 font-medium text-secondary">Format</span>
                  <Select<string>
                    items={EXPORT_FORMATS}
                    value={exportFormat}
                    onValueChange={(value) => {
                      if (value) setExportFormat(value);
                    }}
                  >
                    <SelectTrigger size="md" />
                    <SelectContent side="bottom" align="start">
                      <SelectList>
                        {EXPORT_FORMATS.map((option) => (
                          <SelectItem key={option.value} value={option.value} size="md" label={option.label} />
                        ))}
                      </SelectList>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </DialogBody>
          </DialogMain>
          <DialogActions>
            {activeFilterCount > 0 && (
              <Button variant="ghost" size="md" stretch="auto" label="Clear filters" onClick={() => setFilters({})} />
            )}
            <Button variant="secondary" size="md" stretch="auto" label="Cancel" onClick={handleClose} />
            <Button
              variant="primary"
              size="md"
              stretch="auto"
              label={isExporting ? "Exporting..." : activeFilterCount > 0 ? "Export filtered" : "Export all"}
              disabled={isExporting || options === undefined}
              onClick={() => void handleExport()}
            />
          </DialogActions>
        </DialogContent>
      </Dialog>
    </>
  );
}
