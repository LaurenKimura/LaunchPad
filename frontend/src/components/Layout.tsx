import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuth } from "../useAuth";
import { DISCLAIMER } from "../disclaimer";

export function Layout({ children }: { children: ReactNode }) {
  const { session, signOut } = useAuth();
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-800 bg-[#0c1824]">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-4">
          <div>
            <p className="text-xs uppercase tracking-[0.2em] text-cyan-300/80">LaunchPad</p>
            <p className="text-lg font-medium text-slate-50">Anomaly desk</p>
          </div>
          <nav className="flex items-center gap-4 text-sm">
            {session ? (
              <>
                <NavLink className={navClass} to="/">
                  Dashboard
                </NavLink>
                <NavLink className={navClass} to="/upload">
                  Upload
                </NavLink>
                <span className="hidden text-slate-400 sm:inline">{session.email}</span>
                <button className="rounded-md border border-slate-600 px-3 py-1.5 text-slate-100" onClick={signOut} type="button">
                  Sign out
                </button>
              </>
            ) : (
              <>
                <NavLink className={navClass} to="/login">
                  Sign in
                </NavLink>
                <NavLink className={navClass} to="/signup">
                  Sign up
                </NavLink>
              </>
            )}
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</main>
      <footer className="sticky bottom-0 border-t border-amber-800/70 bg-amber-950/95 px-6 py-3 text-sm text-amber-100" role="note">
        {DISCLAIMER}
      </footer>
    </div>
  );
}

function navClass({ isActive }: { isActive: boolean }): string {
  return isActive ? "text-cyan-200" : "text-slate-300 hover:text-white";
}
