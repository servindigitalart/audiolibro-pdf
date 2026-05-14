const API_BASE = import.meta.env.PUBLIC_API_URL;

const cleanBase = API_BASE?.replace(/\/$/, "");

const API_URL = cleanBase?.includes("/api/v1")
  ? cleanBase
  : `${cleanBase}/api/v1`;

export { API_URL };
