const BASE_URL = import.meta.env.VITE_API_URL ?? "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiFetchOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const { body, headers, ...rest } = options;
  const init: RequestInit = {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
  };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);

  if (!res.ok) {
    // Read the body once as text, then try to parse it as JSON. The Fetch API
    // only lets you consume the body once — calling res.json() and falling
    // back to res.text() would always fail on the second read.
    const text = await res.text().catch(() => "");
    let detail: unknown;
    let message = `${res.status} ${res.statusText}`;
    if (text) {
      try {
        detail = JSON.parse(text);
        if (
          detail &&
          typeof detail === "object" &&
          "detail" in detail &&
          typeof (detail as { detail: unknown }).detail === "string"
        ) {
          message = (detail as { detail: string }).detail;
        }
      } catch {
        message = text;
      }
    }
    throw new ApiError(res.status, message, detail);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}
