import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../useAuth";
import { emailIssue, passwordIssue } from "../uploadRules";

export function SignupPage() {
  const { configured, confirm, signUp } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [repeated, setRepeated] = useState("");
  const [code, setCode] = useState("");
  const [stage, setStage] = useState<"form" | "code" | "done">("form");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const emailError = emailIssue(email);
    if (emailError) {
      setError(emailError);
      return;
    }
    const passwordError = passwordIssue(password);
    if (passwordError) {
      setError(passwordError);
      return;
    }
    if (password !== repeated) {
      setError("Passwords do not match.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await signUp(email, password);
      setStage("code");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sign-up failed.");
    } finally {
      setPending(false);
    }
  }

  async function onConfirm(event: FormEvent) {
    event.preventDefault();
    if (!code.trim()) {
      setError("Enter the confirmation code from your email.");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await confirm(email, code);
      setStage("done");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Confirmation failed.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="mx-auto max-w-md">
      <h1 className="text-2xl font-medium text-slate-50">Create an account</h1>
      <p className="mt-2 text-sm text-slate-400">
        Passwords need 12 characters with upper case, lower case, a digit, and a symbol.
      </p>
      {!configured && (
        <p className="mt-4 rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-300" role="status">
          Set VITE_USER_POOL_ID and VITE_USER_POOL_CLIENT_ID before creating an account.
        </p>
      )}
      {stage === "form" && (
        <form className="mt-6 space-y-4" onSubmit={onSubmit}>
          <Field label="Email" onChange={setEmail} type="email" value={email} />
          <Field label="Password" onChange={setPassword} type="password" value={password} />
          <Field label="Repeat password" onChange={setRepeated} type="password" value={repeated} />
          {error && <Alert>{error}</Alert>}
          <button className={buttonClass} disabled={pending} type="submit">
            {pending ? "Creating account…" : "Create account"}
          </button>
        </form>
      )}
      {stage === "code" && (
        <form className="mt-6 space-y-4" onSubmit={onConfirm}>
          <p className="text-sm text-slate-300">Enter the code Cognito sent to {email}.</p>
          <Field label="Confirmation code" onChange={setCode} type="text" value={code} />
          {error && <Alert>{error}</Alert>}
          <button className={buttonClass} disabled={pending} type="submit">
            {pending ? "Confirming…" : "Confirm email"}
          </button>
        </form>
      )}
      {stage === "done" && (
        <p className="mt-6 text-sm text-slate-200" role="status">
          Email confirmed. <Link className="text-cyan-200" to="/login">Sign in</Link>
        </p>
      )}
      {stage !== "done" && (
        <p className="mt-4 text-sm text-slate-400">
          Already registered? <Link className="text-cyan-200" to="/login">Sign in</Link>
        </p>
      )}
    </section>
  );
}

function Field({
  label,
  type,
  value,
  onChange,
}: {
  label: string;
  type: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-sm text-slate-300">
      {label}
      <input
        className="mt-1 w-full rounded-md border border-slate-700 bg-[#0c1824] px-3 py-2 text-slate-100"
        onChange={(event) => onChange(event.target.value)}
        type={type}
        value={value}
      />
    </label>
  );
}

function Alert({ children }: { children: string }) {
  return (
    <p className="rounded-md border border-rose-800 bg-rose-950 px-3 py-2 text-sm text-rose-100" role="alert">
      {children}
    </p>
  );
}

const buttonClass = "rounded-md bg-cyan-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-60";
