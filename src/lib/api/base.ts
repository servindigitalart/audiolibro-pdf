const API_BASE = import.meta.env.PUBLIC_API_URL;

// seguridad: remover slash final
const cleanBase = API_BASE?.replace(/\/$/, "");

// evita doble /api/v1 si ya viene en env
const API_URL = cleanBase?.includes("/api/v1")
  ? cleanBase
  : `${cleanBase}/api/v1`;

export { API_URL };
