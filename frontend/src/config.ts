export type AppConfig = {
  userPoolId: string;
  clientId: string;
  apiUrl: string;
};

export function appConfig(): AppConfig {
  return {
    userPoolId: import.meta.env.VITE_USER_POOL_ID ?? "",
    clientId: import.meta.env.VITE_USER_POOL_CLIENT_ID ?? "",
    apiUrl: (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, ""),
  };
}

export function cognitoConfigured(config: AppConfig = appConfig()): boolean {
  return Boolean(config.userPoolId && config.clientId);
}

export function apiConfigured(config: AppConfig = appConfig()): boolean {
  return Boolean(config.apiUrl);
}
