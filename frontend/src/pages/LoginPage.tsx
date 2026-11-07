import { useState, type FormEvent } from "react";
import { Link, Navigate } from "react-router-dom";
import { useAuth } from "../useAuth";
import { emailIssue } from "../uploadRules";

export function LoginPage() {
  const { configured, ready, session, signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (ready && session) {
    return <Navigate to="/" replace />;
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const emailError = emailIssue(email);
    if (emailError) {
      setError(emailError);
      return;
    }
    if (!password) {
      setError("Enter your password.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await signIn(email, password);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sign-in failed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="mx-auto max-w-md">
      <h1 className="text-2xl font-medium text-slate-50">Sign in</h1>
      <p className="mt-2 text-sm text-slate-400">Use the email address on your operator account.</p>
      {!configured && (
        <p className="mt-4 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300" role="status">
          Set VITE_USER_POOL_ID and VITE_USER_POOL_CLIENT_ID before signing in.
        </p>
      )}
      <form className="mt-6 space-y-4" onSubmit={onSubmit}>
        <label className="block text-sm text-slate-300">
          Email
          <input
            autoComplete="username"
            className={fieldClass}
            onChange={(event) => setEmail(event.target.value)}
            type="email"
            value={email}
          />
        </label>
        <label className="block text-sm text-slate-300">
          Password
          <input
            autoComplete="current-password"
            className={fieldClass}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            value={password}
          />
        </label>
        {error && (
          <p className="rounded-md border border-rose-800 bg-rose-950 px-3 py-2 text-sm text-rose-100" role="alert">
            {error}
          </p>
        )}
        <button className={buttonClass} disabled={pending || !ready} type="submit">
          {pending ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="mt-4 text-sm text-slate-400">
        New operator? <Link className="text-cyan-200" to="/signup">Create an account</Link>
      </p>
    </section>
  );
}

const fieldClass = "mt-1 w-full rounded-md border border-slate-700 bg-[#0c1824] px-3 py-2 text-slate-100";
const buttonClass = "rounded-md bg-cyan-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-60";
