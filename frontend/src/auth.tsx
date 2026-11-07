import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserAttribute,
  CognitoUserPool,
  type CognitoUserSession,
} from "amazon-cognito-identity-js";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { appConfig, cognitoConfigured } from "./config";
import { AuthContext, type AuthValue, type Session } from "./authContext";

export function AuthProvider({ children }: { children: ReactNode }) {
  const configured = cognitoConfigured();
  const [ready, setReady] = useState(!configured);
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    const pool = createPool();
    const current = pool?.getCurrentUser();
    if (!pool || !current) {
      setReady(true);
      return;
    }
    current.getSession((error: Error | null, result: CognitoUserSession | null) => {
      if (!error && result?.isValid()) {
        setSession({ email: current.getUsername(), idToken: result.getIdToken().getJwtToken() });
      }
      setReady(true);
    });
  }, []);

  const value = useMemo<AuthValue>(
    () => ({
      ready,
      configured,
      session,
      async signIn(email: string, password: string) {
        const next = await authenticate(email, password);
        setSession(next);
      },
      signUp,
      confirm,
      signOut() {
        createPool()?.getCurrentUser()?.signOut();
        setSession(null);
      },
    }),
    [configured, ready, session],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

function createPool(): CognitoUserPool | null {
  const config = appConfig();
  if (!cognitoConfigured(config)) {
    return null;
  }
  return new CognitoUserPool({ UserPoolId: config.userPoolId, ClientId: config.clientId });
}

function authenticate(email: string, password: string): Promise<Session> {
  const pool = createPool();
  if (!pool) {
    return Promise.reject(new Error("Set VITE_USER_POOL_ID and VITE_USER_POOL_CLIENT_ID."));
  }
  const username = email.trim();
  const user = new CognitoUser({ Username: username, Pool: pool });
  return new Promise((resolve, reject) => {
    user.authenticateUser(new AuthenticationDetails({ Username: username, Password: password }), {
      onSuccess(result) {
        resolve({ email: username, idToken: result.getIdToken().getJwtToken() });
      },
      onFailure(error: Error) {
        reject(new Error(error.message || "Sign-in failed."));
      },
      newPasswordRequired() {
        reject(new Error("This account still has a temporary password. Ask an admin to set a permanent one."));
      },
    });
  });
}

function signUp(email: string, password: string): Promise<void> {
  const pool = createPool();
  if (!pool) {
    return Promise.reject(new Error("Set VITE_USER_POOL_ID and VITE_USER_POOL_CLIENT_ID."));
  }
  const username = email.trim();
  return new Promise((resolve, reject) => {
    pool.signUp(
      username,
      password,
      [new CognitoUserAttribute({ Name: "email", Value: username })],
      [],
      (error) => {
        if (error) {
          reject(new Error(error.message || "Sign-up failed."));
          return;
        }
        resolve();
      },
    );
  });
}

function confirm(email: string, code: string): Promise<void> {
  const pool = createPool();
  if (!pool) {
    return Promise.reject(new Error("Set VITE_USER_POOL_ID and VITE_USER_POOL_CLIENT_ID."));
  }
  const user = new CognitoUser({ Username: email.trim(), Pool: pool });
  return new Promise((resolve, reject) => {
    user.confirmRegistration(code.trim(), true, (error) => {
      if (error) {
        reject(new Error(error.message || "Confirmation failed."));
        return;
      }
      resolve();
    });
  });
}
