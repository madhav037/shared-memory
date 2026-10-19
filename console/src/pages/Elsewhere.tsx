import { IconArrowRight, IconSearch } from "@tabler/icons-react";
import { Link, useLocation, useSearchParams } from "react-router";

import "./landing.css";
import "./elsewhere.css";

/*
 * The pages for addresses that lead nowhere yet: what is coming soon, and what isn't here at all. Both work
 * before and after signing in; inside the console they sit in its reading column on its own paper.
 */

/** What each unbuilt action was for, said plainly. */
const SOON: Record<string, { lead: string; then: string }> = {
  trial: {
    lead: "Trials on a server hosted by us aren’t open yet.",
    then: "We’re building the hosted servers now. The plans and prices on the landing page are what we mean to offer.",
  },
  license: {
    lead: "Licenses for self-hosted servers aren’t on sale yet.",
    then: "We’re building licensing now. The plans and prices on the landing page are what we mean to offer.",
  },
  contact: {
    lead: "A way to talk to us about bigger teams is on its way.",
    then: "Plans for more than fifteen members come after the hosted servers and licenses.",
  },
};
const SOON_ANYTHING = {
  lead: "This part of Shared Memory isn’t built yet.",
  then: "It’s on its way. Everything already built is a click back.",
};

export function ComingSoon({ inConsole = false }: { inConsole?: boolean }) {
  const [query] = useSearchParams();
  const what = SOON[query.get("for") ?? ""] ?? SOON_ANYTHING;
  return (
    <div className={inConsole ? "lp-elsewhere in-console" : "lp-elsewhere"} data-testid="coming-soon">
      <div className="lp-elsewhere-inner">
        <div className="lp-filling" aria-hidden="true">
          {Array.from({ length: 15 }, (_, i) => (
            <i key={i} style={{ "--i": i } as React.CSSProperties} />
          ))}
        </div>
        <h1>
          Coming <em>soon.</em>
        </h1>
        <p className="lead">{what.lead}</p>
        <p className="then">{what.then}</p>
        <div className="lp-actions">
          <Link className="lp-btn go" to={inConsole ? "/" : "/#pricing"}>
            {inConsole ? "Back to the front page" : "Back to the plans"} <IconArrowRight size={18} stroke={2} />
          </Link>
          {!inConsole && (
            <Link className="lp-btn on-night" to="/">
              What Shared Memory does
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}

export function NotFound({ inConsole = false }: { inConsole?: boolean }) {
  const { pathname } = useLocation();
  return (
    <div className={inConsole ? "lp-elsewhere in-console" : "lp-elsewhere"} data-testid="not-found">
      <div className="lp-elsewhere-inner">
        <div className="lp-code" role="img" aria-label="404">
          <span aria-hidden="true">4</span>
          <span className="square" aria-hidden="true" />
          <span aria-hidden="true">4</span>
        </div>
        <h1>There’s no page at this address.</h1>
        <p className="lead">
          <code>{pathname}</code> isn’t part of this console.
        </p>
        <p className="then">The address may be mistyped, or what was here may have moved.</p>
        <div className="lp-actions">
          <Link className="lp-btn go" to="/">
            Go to the front page <IconArrowRight size={18} stroke={2} />
          </Link>
          {inConsole && (
            <Link className="lp-btn plain" to="/search">
              <IconSearch size={18} stroke={1.6} /> Search memory
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
