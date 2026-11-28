// What both backends share: the error of a failed call and how it is read from the response.

/** A failed call: the HTTP status and, when the server gave one, its `{detail}` text. */
export class ApiError extends Error {
  status: number;
  detail: string | null;
  constructor(status: number, detail: string | null) {
    super(detail ?? String(status));
    this.status = status;
    this.detail = detail;
  }
}

export async function failure(response: Response): Promise<ApiError> {
  let detail: string | null = null;
  try {
    const body: unknown = await response.json();
    const value = body && typeof body === "object" ? (body as { detail?: unknown }).detail : null;
    if (typeof value === "string") detail = value;
  } catch {
    // no JSON body: the status alone is reported
  }
  return new ApiError(response.status, detail);
}
