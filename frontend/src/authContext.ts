import { createContext } from "react";

export type Session = {
  email: string;
  idToken: string;
};

export type AuthValue = {
  ready: boolean;
  configured: boolean;
  session: Session | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  confirm: (email: string, code: string) => Promise<void>;
  signOut: () => void;
};

export const AuthContext = createContext<AuthValue | null>(null);
