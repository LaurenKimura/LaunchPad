import { useContext } from "react";
import { AuthContext } from "./authContext";

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("AuthProvider is missing");
  }
  return value;
}
