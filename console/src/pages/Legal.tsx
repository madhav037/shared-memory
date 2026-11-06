import type { ReactNode } from "react";
import { Link } from "react-router";

import { LEGAL_DRAFT, LEGAL_UPDATED, SELLER, SELLER_CONTACT } from "../lib/legal";
import { TRIAL_DAYS } from "../lib/plans";
import "./legal.css";

/*
 * The Terms of Service and the Privacy Policy, in plain language. Every claim is checked against the code; where
 * the code doesn't do it yet (a plan's end, deleting a team's data), the text says "we will", as a commitment.
 */

/** The two links every footer carries. */
export function LegalLinks({ className = "" }: { className?: string }) {
  return (
    <nav className={`legal-links ${className}`.trim()} aria-label="Legal" data-testid="legal-links">
      <Link to="/terms">Terms</Link>
      <Link to="/privacy">Privacy</Link>
    </nav>
  );
}

function Page({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="legal" data-testid="legal-page">
      <article className="legal-inner">
        {LEGAL_DRAFT && (
          <p className="legal-draft" data-testid="legal-draft" role="note">
            <b>Draft, pending legal review.</b> This text has not been reviewed by a lawyer yet. Don’t rely on it as
            final.
          </p>
        )}
        <h1>{title}</h1>
        <p className="legal-updated">
          {SELLER} · Last changed {LEGAL_UPDATED}
        </p>
        {children}
        <LegalLinks className="legal-end" />
      </article>
    </div>
  );
}

export function Terms() {
  return (
    <Page title="Terms of Service">
      <p>
        These terms are between you and {SELLER}, a sole proprietor in India (“we”), who sells Shared Memory. By
        starting a trial, buying a plan or using a Shared Memory server, you agree to them for your team. Write to{" "}
        <a href={`mailto:${SELLER_CONTACT}`}>{SELLER_CONTACT}</a> with any question.
      </p>

      <h2>What you get</h2>
      <p>
        Shared Memory is a memory server that your team’s coding agents read and write, and a console for governing it.
        It runs as a hosted server that we run for your team, or as a self-hosted server that your team runs under a
        license.
      </p>

      <h2>Plans and payment</h2>
      <ul>
        <li>
          A plan covers up to 5, 10 or 15 members. You agree to keep your team within the plan you pay for. The server
          doesn’t enforce that limit yet; we will add it, and until then we rely on you.
        </li>
        <li>
          A hosted server is billed monthly, or yearly up front. A self-hosted server is licensed for twelve months,
          paid up front.
        </li>
        <li>
          A hosted server starts with a {TRIAL_DAYS}-day trial. It needs no card. When the trial ends, the team pays or
          the plan ends.
        </li>
        <li>
          Payments go through Paddle, which is the merchant of record: it collects your payment, handles tax and sends the
          receipt. Paddle’s own terms apply to the payment.
        </li>
        <li>Prices on the landing page are the prices that apply until we change them. A change never touches a period you have already paid for.</li>
      </ul>

      <h2>Cancelling</h2>
      <ul>
        <li>Monthly: cancel any time. The plan runs to the end of the period you paid for.</li>
        <li>Yearly, and self-hosted licenses: these can’t be cancelled partway through, and aren’t refunded partway through.</li>
        <li>Where the law gives you a right to a refund, that right stays.</li>
      </ul>

      <h2>When a plan ends</h2>
      <p>
        When a hosted team’s plan ends, its server is read-only for 7 days, so members can still read memory and make
        a copy. Then the server is stopped. We will delete the team’s data and backups 30 days after the plan ended.
        Today we do that by hand, and we commit to doing it within that time. An admin can download all of the team’s
        data at any time while the plan runs.
      </p>

      <h2>Acceptable use</h2>
      <p>You agree not to:</p>
      <ul>
        <li>break the law, or store what you have no right to store;</li>
        <li>attack, overload or probe the hosted servers, or try to reach another team’s data;</li>
        <li>share a member’s sign-in or a personal token with someone who isn’t that member;</li>
        <li>resell the hosted server, or run a competing service with the source, which the license forbids.</li>
      </ul>
      <p>We may stop a hosted server that breaks these rules, and will say why when we can.</p>

      <h2>The source and its license</h2>
      <p>
        The source code is available under the Functional Source License, FSL-1.1-ALv2. The <code>LICENSE</code> file in
        the repository is the full text. Each release becomes Apache 2.0 two years after we publish it. Running a
        self-hosted server for a team needs a paid license for that team’s plan. These terms don’t replace the license
        for the source; they sit beside it.
      </p>

      <h2>Your team’s memory</h2>
      <p>
        The memory, and everything else your team puts in, stays yours. We don’t read it, except where a problem
        can’t be fixed without it and you have asked us to. You give us only the right to store and run it so the
        server can work for you.
      </p>

      <h2>Backups</h2>
      <p>
        Backups run only when they are switched on. We accept no responsibility for data lost while backups are off, or
        for a backup that wasn’t made, wasn’t kept, or can’t be restored. Check that yours is running.
      </p>

      <h2>No warranty, and limits on our liability</h2>
      <p>
        Shared Memory is provided as it is. We don’t promise that it will always be available or free of errors. To
        the extent the law allows, we aren’t liable for indirect or consequential loss, for lost profit, or for lost
        data, and our total liability for anything arising from Shared Memory is limited to what you paid us in the 12
        months before the claim. Nothing here limits a liability that the law doesn’t let us limit.
      </p>

      <h2>Changes to these terms</h2>
      <p>
        We may change these terms. We will post the new text here with its date, and tell your team’s admins by email
        before a change that matters starts to apply. If you keep using Shared Memory after that, you accept the change;
        if you don’t, you may cancel as above.
      </p>

      <h2>Governing law</h2>
      <p>These terms are governed by the law of India. Courts in India decide any dispute we can’t settle by talking first.</p>
    </Page>
  );
}

export function Privacy() {
  return (
    <Page title="Privacy Policy">
      <p>
        This policy says what {SELLER} (“we”), a sole proprietor in India, collects when a team uses Shared Memory,
        why, who else receives it, and what you can do about it. It follows India’s Digital Personal Data Protection
        Act 2023 and the basics of the GDPR. Write to <a href={`mailto:${SELLER_CONTACT}`}>{SELLER_CONTACT}</a> for
        anything in it.
      </p>

      <h2>Who is responsible</h2>
      <p>
        For a hosted server, we run the server for your team and process its data on the team’s behalf. The team,
        through its admins, decides what goes into it. For a self-hosted server, the team runs the server and is
        responsible for it; see “A self-hosted server” below.
      </p>

      <h2>What we collect</h2>
      <ul>
        <li>
          <b>Member name and GitHub login.</b> A member signs in with GitHub. Shared Memory reads only the GitHub
          account’s numeric id and login, once, at sign-in, and keeps them with the member’s name. It doesn’t keep the
          GitHub access token it was given.
        </li>
        <li>
          <b>Memories.</b> The memory your team’s coding agents save: Markdown files in a git history on the server,
          with the name of the member who saved each one.
        </li>
        <li>
          <b>Session metadata.</b> Which coding agent session worked on which project and file, when it last did, and
          the files it is editing, while the team works.
        </li>
        <li>
          <b>The audit log.</b> The record of who changed members, roles, access, personal tokens, memory, cards and
          projects, and when.
        </li>
        <li>
          <b>The sign-in cookie.</b> See “Cookies” below. The server stores only a hash of its value.
        </li>
        <li>
          <b>Personal tokens.</b> The server stores a hash of each token, never the token itself.
        </li>
      </ul>
      <p>We don’t collect advertising identifiers, and we don’t run analytics or tracking scripts on the console.</p>

      <h2>Why, and on what basis</h2>
      <p>
        We use this data only to run Shared Memory for the team: to sign members in, to keep and serve the team’s
        memory, to show who did what, and to keep the service safe. The basis is your team’s contract with us, and our
        legitimate interest in running and securing the service. Under the DPDP Act, a member’s data is processed
        because the member’s team asked for it for this purpose. We don’t sell data or use it for advertising.
      </p>

      <h2>Cookies</h2>
      <p>
        The console sets only one cookie: the sign-in cookie that keeps a member signed in. It is strictly necessary,
        it is marked HTTP-only and expires after 7 days (a server’s operator can change that), and it is removed when
        a member signs out. Because it is the only one, there is no cookie banner.
      </p>

      <h2>Who else receives data</h2>
      <p>These are the processors we use for a hosted server. A self-hosted team uses its own.</p>
      <ul>
        <li>
          <b>The hosting provider</b> of our servers holds the server’s data, including memory and backups.
        </li>
        <li>
          <b>GitHub</b> receives the sign-in request. Backups go to GitHub only if the team chooses a GitHub
          repository for them.
        </li>
        <li>
          <b>Sentry</b> receives server errors, only if error reporting is switched on. Before an error leaves the
          server, request details, cookies, exception messages, local variables and member identifiers are removed. What
          stays is the kind of error, the stack, the route and the release.
        </li>
        <li>
          <b>Grafana Labs</b> runs an outside uptime check of the server’s <code>/health</code> address. It receives no
          member or memory data.
        </li>
        <li>
          <b>Paddle</b> collects payments as the merchant of record, and receives what a payment needs: the buyer’s name,
          email and payment details. We never see card details.
        </li>
        <li>
          <b>Mailjet</b> sends emails about a team’s plan (trial, renewal, changes), to the team’s admins.
        </li>
      </ul>
      <p>
        Some of these are outside India, so data can leave India. We choose processors that give written commitments
        to protect it, and we will list any new one here before it receives data.
      </p>

      <h2>Backups</h2>
      <p>
        When backups are switched on, the server copies its memory history and a database dump every night to a private
        git repository its operator chooses. If an encryption key is set, they are encrypted before they leave the
        server. If it isn’t, they are not. Backups can hold everything the server holds, including the names above.
      </p>

      <h2>How long we keep it</h2>
      <p>
        While a team’s plan runs, we keep its data. After a hosted plan ends, the server is read-only for 7 days, then
        stopped, and we will delete the team’s data and backups 30 days after the plan ended. Today this deletion is
        done by hand, and we commit to doing it within that time. Backups are overwritten as new ones are made.
      </p>

      <h2>A removed member’s name</h2>
      <p>
        When an admin removes a member, the member can no longer sign in or use a personal token. Their name stays in
        the memory history and the audit log, as a record of who saved and changed what. That record is kept as an
        audit trail, and the team’s memory would lose its meaning without it. The member’s record (name and GitHub login)
        also stays on the server, marked as removed.
      </p>

      <h2>Your rights</h2>
      <p>
        You can ask for a copy of your personal data, ask us to correct it, ask us to erase it, object to how it is
        used, withdraw consent where we rely on it, and name someone to act for you. To use any of these, write to{" "}
        <a href={`mailto:${SELLER_CONTACT}`}>{SELLER_CONTACT}</a>. We will answer within 30 days. Your team’s admins can
        also download all of the team’s data from the console.
      </p>
      <p>
        If we erase data, we can’t erase what the law or the audit trail above requires us to keep. If you aren’t
        satisfied with our answer, write to us again with “Grievance” in the subject, and we will answer within 30
        days. You may also complain to the Data Protection Board of India, or if you are in the EU or UK, to your local
        data protection authority.
      </p>

      <h2>If something goes wrong</h2>
      <p>
        If personal data on a hosted server is exposed, we will tell the team’s admins by email without undue delay,
        and within 72 hours of learning of it, with what happened, what was involved and what we are doing.
      </p>

      <h2>A self-hosted server</h2>
      <p>
        A self-hosted server sends us nothing. We don’t see its data, and we receive no usage reports from it. Error
        reporting to Sentry is off unless whoever runs the server switches it on. The team that runs it is responsible
        for what it holds, and for its own privacy notice to its members.
      </p>

      <h2>Children</h2>
      <p>Shared Memory is for people at work. It isn’t meant for anyone under 18, and we don’t knowingly collect data about them.</p>

      <h2>Changes to this policy</h2>
      <p>We will post a changed policy here with its date, and tell the team’s admins by email before a change that matters starts to apply.</p>
    </Page>
  );
}
