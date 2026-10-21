/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useState } from "react";
import { observer } from "mobx-react";
import { usePathname, useSearchParams } from "next/navigation";
import useSWR from "swr";
import { BoxesOutline, CloseOutline, LogOutOutline, TickOutline, UserOutline } from "@makeplane/propel/icons";
import { setToast } from "@plane/blocks/toast";
// components
import { LogoSpinner } from "@/components/common/logo-spinner";
import { EmptySpace, EmptySpaceItem } from "@/components/ui/empty-space";
// constants
import { WORKSPACE_INVITATION } from "@plane/constants";
// helpers
import { EPageTypes } from "@/helpers/authentication.helper";
// hooks
import { useUser } from "@/hooks/store/user";
import { useAppRouter } from "@/hooks/use-app-router";
// wrappers
import { AuthenticationWrapper } from "@/lib/wrappers/authentication-wrapper";
import { WorkspaceService } from "@/services/workspace.service";
// services

// service initialization
const workspaceService = new WorkspaceService();

function WorkspaceInvitationPage() {
  // router
  const router = useAppRouter();
  // query params
  const searchParams = useSearchParams();
  const invitation_id = searchParams.get("invitation_id");
  const slug = searchParams.get("slug");
  const token = searchParams.get("token");
  const pathname = usePathname();
  // store hooks
  const { data: currentUser, signOut } = useUser();
  // states
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { data: invitationDetail, error } = useSWR(
    invitation_id && slug && WORKSPACE_INVITATION(invitation_id.toString()),
    invitation_id && slug
      ? () => workspaceService.getWorkspaceInvitation(slug.toString(), invitation_id.toString())
      : null
  );

  // Only the person signed in with the invited email can accept or ignore the invitation (the server enforces it)
  const invitedEmail = invitationDetail?.email ?? "";
  // the user store holds an empty object while nobody is signed in
  const isSignedIn = !!currentUser?.id;
  const isInvitedUser = isSignedIn && currentUser?.email?.toLowerCase() === invitedEmail.toLowerCase();
  // sign in / sign up as the invited email and come back to this invitation
  const currentPath = `${pathname}?${searchParams.toString()}`;
  const signInUrl = `/?email=${encodeURIComponent(invitedEmail)}&next_path=${encodeURIComponent(currentPath)}`;

  const showError = (err: unknown, fallback: string) => {
    const message = (err as { error?: string } | undefined)?.error;
    setToast({ type: "error", title: "Error!", message: message ?? fallback });
  };

  const respond = async (accepted: boolean) => {
    if (!invitationDetail || !token || isSubmitting) return;
    setIsSubmitting(true);
    try {
      await workspaceService.joinWorkspace(invitationDetail.workspace.slug, invitationDetail.id, {
        accepted,
        token,
      });
      if (accepted) {
        setToast({ type: "success", title: "Success!", message: `You joined ${invitationDetail.workspace.name}.` });
        router.push(`/${invitationDetail.workspace.slug}`);
      } else router.push("/");
    } catch (err) {
      showError(err, accepted ? "The invitation could not be accepted." : "The invitation could not be ignored.");
      setIsSubmitting(false);
    }
  };

  const handleSwitchAccount = async () => {
    try {
      await signOut();
    } finally {
      router.push(signInUrl);
    }
  };

  const renderPendingInvitation = () => {
    if (!invitationDetail) return null;
    const title = `You have been invited to ${invitationDetail.workspace.name}`;
    if (!isSignedIn)
      return (
        <EmptySpace
          title={title}
          description={`This invitation is for ${invitedEmail}. Sign in or create your account with this email to accept it.`}
        >
          <EmptySpaceItem Icon={UserOutline} title={`Continue as ${invitedEmail}`} href={signInUrl} />
        </EmptySpace>
      );
    if (!isInvitedUser)
      return (
        <EmptySpace
          title={title}
          description={`This invitation is for ${invitedEmail}, but you are signed in as ${currentUser?.email}. Sign in as ${invitedEmail} to accept it.`}
        >
          <EmptySpaceItem Icon={LogOutOutline} title={`Switch to ${invitedEmail}`} action={handleSwitchAccount} />
          <EmptySpaceItem Icon={BoxesOutline} title="Go to my workspaces" href="/" />
        </EmptySpace>
      );
    return (
      <EmptySpace
        title={title}
        description="Your workspace is where you'll create projects, collaborate on your work items, and organize different streams of work in your Hlink Sprint account."
      >
        <EmptySpaceItem Icon={TickOutline} title={isSubmitting ? "Joining…" : "Accept"} action={() => respond(true)} />
        <EmptySpaceItem Icon={CloseOutline} title="Ignore" action={() => respond(false)} />
      </EmptySpace>
    );
  };

  return (
    <AuthenticationWrapper pageType={EPageTypes.PUBLIC}>
      <div className="flex h-full w-full flex-col items-center justify-center px-3">
        {invitationDetail && !invitationDetail.responded_at ? (
          error ? (
            <div className="shadow-2xl flex w-full flex-col space-y-4 rounded-sm border border-subtle bg-surface-1 px-4 py-8 text-center md:w-1/3">
              <h2 className="text-18 uppercase">INVITATION NOT FOUND</h2>
            </div>
          ) : (
            renderPendingInvitation()
          )
        ) : error || invitationDetail?.responded_at ? (
          invitationDetail?.accepted ? (
            <EmptySpace
              title={`You are already a member of ${invitationDetail.workspace.name}`}
              description="Your workspace is where you'll create projects, collaborate on your work items, and organize different streams of work in your Hlink Sprint account."
            >
              <EmptySpaceItem Icon={BoxesOutline} title="Continue to home" href="/" />
            </EmptySpace>
          ) : (
            <EmptySpace
              title="This invitation link is not active anymore."
              description="Your workspace is where you'll create projects, collaborate on your work items, and organize different streams of work in your Hlink Sprint account."
              link={{ text: "Or start from an empty project", href: "/" }}
            >
              {!currentUser ? (
                <EmptySpaceItem Icon={UserOutline} title="Sign in to continue" href="/" />
              ) : (
                <EmptySpaceItem Icon={BoxesOutline} title="Continue to home" href="/" />
              )}
            </EmptySpace>
          )
        ) : (
          <div className="flex h-full w-full items-center justify-center">
            <LogoSpinner />
          </div>
        )}
      </div>
    </AuthenticationWrapper>
  );
}

export default observer(WorkspaceInvitationPage);
