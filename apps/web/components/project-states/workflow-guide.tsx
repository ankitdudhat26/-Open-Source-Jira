/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { ArrowNarrowRightOutline, ChevronDownOutline } from "@makeplane/propel/icons";
import { cn } from "@plane/utils";

/** the default flow, as drawn in the guide */
const FLOW = [
  { name: "To Do", color: "#60646C" },
  { name: "In Progress", color: "#2563EB" },
  { name: "In QA", color: "#7C3AED" },
  { name: "Done", color: "#16A34A" },
];
const REOPEN = { name: "Reopen", color: "#EA580C" };

function Status({ name, color }: { name: string; color: string }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-caption-md-medium text-primary"
      style={{ borderColor: color }}
    >
      <span className="size-2 rounded-full" style={{ backgroundColor: color }} />
      {name}
    </span>
  );
}

function Arrow({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-caption-sm-regular text-tertiary">
      {label}
      <ArrowNarrowRightOutline className="size-3.5" aria-hidden />
    </span>
  );
}

const STEPS: { title: string; text: React.ReactNode }[] = [
  {
    title: "Rename a status",
    text: (
      <>
        Click the <b>pencil</b> next to the status in the list below, change its name and save. Its work items and its
        moves stay as they are.
      </>
    ),
  },
  {
    title: "Add a status",
    text: (
      <>
        Click <b>+</b> on the category it belongs to (Unstarted, Started, Completed…), give it a name and save. Then, in{" "}
        <b>Workflow</b> below, add the moves into it (on the statuses that lead to it) and out of it. Until it has
        moves, nothing can move into it.
      </>
    ),
  },
  {
    title: "Change where work can go",
    text: (
      <>
        In <b>Workflow</b>, each status lists where its work items can move next. <b>+ Add permitted state change</b>{" "}
        adds a move, <b>×</b> removes it, and <b>by</b> lets only the people you pick (and project admins) make it.
        Click <b>Save workflow</b> to apply. Any move that is not listed is refused, e.g. To Do straight to Done.
      </>
    ),
  },
  {
    title: "Delete a status",
    text: (
      <>
        Use the <b>×</b> next to it and choose the status its work items move to; then it is deleted. To Do is where new
        work items start, so make another status the default before deleting it.
      </>
    ),
  },
  {
    title: "Start over",
    text: (
      <>
        <b>Reset to default</b> (in Workflow) brings back exactly To Do, In Progress, In QA, Reopen and Done with their
        moves; work items of other statuses move to the one they stand for. Changes here apply to this project only.
      </>
    ),
  },
];

/**
 * How the workflow works and how to change it, at the top of a project's States settings: the default flow (the same
 * for features, tasks and bugs) and step-by-step instructions.
 */
export function WorkflowGuide() {
  const [isOpen, setIsOpen] = useState(true);
  return (
    <section className="rounded-lg border border-subtle bg-layer-1" aria-labelledby="workflow-guide-title">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        aria-expanded={isOpen}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span>
          <span id="workflow-guide-title" className="block text-body-sm-medium text-primary">
            How the workflow works and how to customize it
          </span>
          <span className="block text-caption-md-regular text-tertiary">
            Every project starts with the same flow for features, tasks and bugs. Change it here for this project.
          </span>
        </span>
        <ChevronDownOutline
          className={cn("size-4 shrink-0 text-tertiary transition-transform", isOpen && "rotate-180")}
        />
      </button>
      {isOpen && (
        <div className="flex flex-col gap-4 border-t border-subtle px-4 py-4">
          {/* the default flow */}
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              {FLOW.map((status, index) => (
                <span key={status.name} className="inline-flex items-center gap-2">
                  {index > 0 && <Arrow label={index === 3 ? "QA passed" : undefined} />}
                  <Status {...status} />
                </span>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Status {...FLOW[2]} />
              <Arrow label="QA failed" />
              <Status {...REOPEN} />
              <Arrow label="restart" />
              <Status {...FLOW[1]} />
              <span className="mx-1 text-tertiary">·</span>
              <Status {...FLOW[3]} />
              <Arrow label="issue found later" />
              <Status {...REOPEN} />
            </div>
            <p className="text-caption-md-regular text-tertiary">
              Work can also go back: In Progress → To Do, In QA → In Progress (direct fixes), Reopen → To Do and Done →
              In QA (retest). Example: TASK-101 goes To Do → In Progress → In QA; QA finds an issue → Reopen → In
              Progress → In QA → Done.
            </p>
          </div>
          {/* how to change it */}
          <ol className="grid gap-3 md:grid-cols-2">
            {STEPS.map((step, index) => (
              <li key={step.title} className="flex gap-3">
                <span className="grid size-5 shrink-0 place-items-center rounded-full bg-accent-subtle text-caption-sm-medium text-accent-primary">
                  {index + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-body-xs-medium text-primary">{step.title}</span>
                  <span className="block text-caption-md-regular text-secondary">{step.text}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
