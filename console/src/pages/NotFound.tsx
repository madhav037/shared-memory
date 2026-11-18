import { Link, useLocation } from "react-router";

/** An address inside the console that leads nowhere. */
export function NotFound() {
  const { pathname } = useLocation();
  return (
    <div data-testid="not-found">
      <h1 className="page-title">There’s no page at this address.</h1>
      <p>
        <code>{pathname}</code> isn’t part of this console. The address may be mistyped, or what was here may have moved.
      </p>
      <p>
        <Link to="/">Go to the contents</Link> or <Link to="/search">search memory</Link>.
      </p>
    </div>
  );
}
